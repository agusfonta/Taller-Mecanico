"""Servicios de ordenes de trabajo (C-09, D5/D6/D8/D9).

* El servicio RECIBE el UoW ya construido por el router y lo abre con ``async with`` UNA vez por
  operacion; nunca lo construye ni confirma por su cuenta (lo hace el UoW al salir del bloque).
* Los errores de dominio son excepciones propias con ``mensaje``; el router las traduce a HTTP.
  Un ``IntegrityError`` atraviesa el bloque (el UoW revierte TODO) y aqui se traduce por NOMBRE de
  restriccion, sin exponer jamas el texto de la base (RN-18).
"""
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy.exc import IntegrityError

from app.core.dependencies import UsuarioActual
from app.core.errores import restriccion_violada
from app.core.paginacion import ParametrosPaginacion, verificar_pagina
from app.modules.ordenes.models import (
    EstadoOrden,
    EstadoOrdenCodigo,
    HistorialEstadoOrden,
    ItemOrden,
    OrdenTrabajo,
)
from app.modules.ordenes.schemas import OrdenAlta
from app.modules.ordenes.transiciones import Accion, destino
from app.modules.ordenes.unit_of_work import OrdenesUoW
from app.modules.repuestos.stock import (
    MOTIVO_ORDEN_TERMINADA,
    RepuestoNoEncontradoError,
    StockFueraDeRangoError,
    StockInsuficienteError,
    mover_stock,
)
from app.modules.usuarios.models import Rol

__all__ = [
    "CatalogoSinCargarError",
    "ConflictoError",
    "NoEncontradoError",
    "OrdenAjenaError",
    "OrdenAsignadaAOtroError",
    "OrdenNoEncontradaError",
    "RepuestoNoDisponibleError",
    "SinPermisoSobreOrdenError",
    "StockInsuficienteOrdenError",
    "TotalFueraDeRangoError",
    "TransicionInvalidaError",
    "VehiculoNoDisponibleError",
    "cancelar_orden",
    "crear_orden",
    "iniciar_orden",
    "terminar_orden",
    "listar_estados",
    "listar_mis_ordenes",
    "listar_ordenes",
    "obtener_orden",
]

TOTAL_MAXIMO = Decimal("9999999999.99")  # NUMERIC(12,2)


class NoEncontradoError(Exception):
    """Un recurso nombrado en la ruta no existe (404)."""

    mensaje = "Recurso no encontrado"


class OrdenNoEncontradaError(NoEncontradoError):
    mensaje = "Orden no encontrada"


class OrdenAjenaError(Exception):
    """La orden pertenece a otro cliente (403)."""

    mensaje = "No tiene permiso para ver esta orden"


class ConflictoError(Exception):
    """Los datos chocan con un registro existente o con el estado del sistema (409)."""

    mensaje = "Los datos chocan con un registro existente"


class CatalogoSinCargarError(ConflictoError):
    mensaje = "El catálogo de estados de orden no está cargado"


class VehiculoNoDisponibleError(ConflictoError):
    mensaje = "El vehículo no existe o fue dado de baja"


class RepuestoNoDisponibleError(ConflictoError):
    mensaje = "Algún repuesto no existe o fue dado de baja"


class TotalFueraDeRangoError(ConflictoError):
    mensaje = "El total de la orden supera el máximo admitido"


class SinPermisoSobreOrdenError(OrdenAjenaError):
    """El usuario no puede operar esta orden (no asignado / no dueno) (403, C-10)."""

    mensaje = "No tiene permiso para operar esta orden"


class TransicionInvalidaError(ConflictoError):
    """La accion no es valida desde el estado actual de la orden (409, C-10)."""

    mensaje = "La orden no admite esta acción en su estado actual"

    def __init__(self, estado: str | None = None, accion: str | None = None) -> None:
        super().__init__(estado, accion)
        if estado is not None and accion is not None:
            self.mensaje = f"La orden está {estado} y no admite {accion}"


class OrdenAsignadaAOtroError(ConflictoError):
    mensaje = "La orden ya está asignada a otro mecánico"


class StockInsuficienteOrdenError(ConflictoError):
    """Algun repuesto de la orden no tiene stock suficiente (409, C-10, D5-b)."""

    mensaje = "Stock insuficiente para terminar la orden"

    def __init__(self, codigo: str | None = None) -> None:
        super().__init__(codigo)
        if codigo is not None:
            self.mensaje = f"Stock insuficiente para el repuesto {codigo}"


_CONFLICTOS_POR_RESTRICCION: dict[str, type[ConflictoError]] = {
    "fk_orden_trabajo_vehiculo_id_vehiculo": VehiculoNoDisponibleError,
    "fk_item_orden_repuesto_id_repuesto": RepuestoNoDisponibleError,
    # C-10: la FK del estado destino es la red de seguridad de la lectura previa del catalogo (D4-d).
    "fk_orden_trabajo_estado_estado_orden": CatalogoSinCargarError,
    "fk_historial_estado_orden_hasta_estado_estado_orden": CatalogoSinCargarError,
}


def _error_desde(exc: IntegrityError) -> ConflictoError:
    """Error de dominio segun la restriccion violada; generico si no se la conoce."""
    return _CONFLICTOS_POR_RESTRICCION.get(restriccion_violada(exc) or "", ConflictoError)()


async def crear_orden(uow: OrdenesUoW, datos: OrdenAlta, usuario_id: int) -> OrdenTrabajo:
    """Alta atomica de una orden PENDIENTE con sus items, precios copiados e historial (D5).

    Todo dentro de UN ``async with uow``: cualquier excepcion revierte orden, items e historial.
    Las lecturas toman ``FOR SHARE`` (vehiculo y repuestos por ``id``) para coordinarse con la baja
    del vehiculo y con el cambio de precio concurrentes (D6).
    """
    ids = sorted(i.repuesto_id for i in datos.items)
    cantidades = {i.repuesto_id: i.cantidad for i in datos.items}
    try:
        async with uow:
            pendiente = EstadoOrdenCodigo.PENDIENTE.value
            if await uow.estados.get_por_codigo(pendiente) is None:
                raise CatalogoSinCargarError
            if await uow.vehiculos.get_vigente_para_orden(datos.vehiculo_id) is None:
                raise VehiculoNoDisponibleError
            repuestos = await uow.repuestos.listar_vigentes_para_orden(ids)
            if len(repuestos) != len(ids):
                raise RepuestoNoDisponibleError

            total = sum((cantidades[r.id] * r.precio for r in repuestos), Decimal("0"))
            if total > TOTAL_MAXIMO:
                raise TotalFueraDeRangoError

            orden = await uow.ordenes.add(
                OrdenTrabajo(
                    vehiculo_id=datos.vehiculo_id,
                    mecanico_id=None,
                    estado=pendiente,
                    falla=datos.falla,
                    total=total,
                )
            )
            await uow.items.add_todos(
                [
                    ItemOrden(
                        orden_id=orden.id,
                        repuesto_id=r.id,
                        cantidad=cantidades[r.id],
                        precio_unitario=r.precio,
                    )
                    for r in repuestos
                ]
            )
            await uow.historial.add(
                HistorialEstadoOrden(
                    orden_id=orden.id,
                    desde_estado=None,
                    hasta_estado=pendiente,
                    usuario_id=usuario_id,
                )
            )
            return await uow.ordenes.get_detalle(orden.id)
    except IntegrityError as exc:
        raise _error_desde(exc) from None


_PERSONAL = frozenset({Rol.ADMIN, Rol.RECEPCION, Rol.MECANICO})
_VE_TODAS = frozenset({Rol.ADMIN, Rol.RECEPCION})


async def obtener_orden(uow: OrdenesUoW, orden_id: int, usuario: UsuarioActual) -> OrdenTrabajo:
    """Detalle de una orden para el personal o para el dueno del vehiculo (D8).

    404 ANTES que 403 (D8-a): el detalle debe cargarse para conocer al dueno. Cualquier MECANICO
    ve cualquier orden (D8-b); DD-18 restringe solo el listado.
    """
    async with uow:
        orden = await uow.ordenes.get_detalle(orden_id)
        if orden is None:
            raise OrdenNoEncontradaError
        if not (usuario.roles_vigentes & _PERSONAL) and orden.vehiculo.cliente.usuario_id != usuario.id:
            raise OrdenAjenaError
        orden.items.sort(key=lambda i: i.repuesto_id)
        orden.historial.sort(key=lambda h: h.id)
        return orden


async def listar_ordenes(
    uow: OrdenesUoW,
    estado: EstadoOrdenCodigo | None,
    usuario: UsuarioActual,
    params: ParametrosPaginacion,
) -> tuple[Sequence[OrdenTrabajo], int]:
    """ADMIN/RECEPCION ven todas; quien es solo MECANICO, las suyas y las sin asignar (DD-18)."""
    visible = None if usuario.roles_vigentes & _VE_TODAS else usuario.id
    codigo = None if estado is None else estado.value
    async with uow:
        total = await uow.ordenes.contar(codigo, visible)
        verificar_pagina(params, total)
        items = await uow.ordenes.buscar(codigo, visible, offset=params.offset, limit=params.size)
        return items, total


async def listar_mis_ordenes(
    uow: OrdenesUoW, usuario_id: int, params: ParametrosPaginacion
) -> tuple[Sequence[OrdenTrabajo], int]:
    """Ordenes de los vehiculos de la ficha del usuario (RN-17), incluidos los dados de baja."""
    async with uow:
        total = await uow.ordenes.contar_de_usuario(usuario_id)
        verificar_pagina(params, total)
        items = await uow.ordenes.listar_de_usuario(usuario_id, offset=params.offset, limit=params.size)
        return items, total


async def listar_estados(uow: OrdenesUoW) -> Sequence[EstadoOrden]:
    """Catalogo de estados por ``posicion`` (RN-19: solo lectura)."""
    async with uow:
        return await uow.estados.listar_por_posicion()


# --- C-10: ciclo de vida -------------------------------------------------------------------------


async def _detalle_ordenado(uow: OrdenesUoW, orden_id: int) -> OrdenTrabajo:
    """Detalle precargado (con el historial recien escrito), con items e historial ordenados."""
    orden = await uow.ordenes.get_detalle(orden_id)
    assert orden is not None  # la fila esta bloqueada por esta misma transaccion
    orden.items.sort(key=lambda i: i.repuesto_id)
    orden.historial.sort(key=lambda h: h.id)
    return orden


async def _exigir_estado_en_catalogo(uow: OrdenesUoW, codigo: EstadoOrdenCodigo) -> None:
    if await uow.estados.get_por_codigo(codigo.value) is None:
        raise CatalogoSinCargarError


async def _registrar_transicion(
    uow: OrdenesUoW,
    orden: OrdenTrabajo,
    hasta: EstadoOrdenCodigo,
    usuario_id: int,
    cambios: dict | None = None,
) -> None:
    """Actualiza el estado de la orden y agrega la linea de historial firmada por el actor."""
    desde = orden.estado
    await uow.ordenes.update(orden, {"estado": hasta.value, **(cambios or {})})
    await uow.historial.add(
        HistorialEstadoOrden(
            orden_id=orden.id, desde_estado=desde, hasta_estado=hasta.value, usuario_id=usuario_id
        )
    )


async def iniciar_orden(uow: OrdenesUoW, orden_id: int, usuario: UsuarioActual) -> OrdenTrabajo:
    """PENDIENTE -> EN_REPARACION asignando al mecanico que inicia (DD-18, D4).

    Un unico bloque: ``bloquear`` (404) -> transicion valida (409) -> no preasignada a otro (409)
    -> estado en el catalogo (409) -> escrituras -> detalle. Cualquier rechazo no escribe nada.
    """
    try:
        async with uow:
            orden = await uow.ordenes.bloquear(orden_id)
            if orden is None:
                raise OrdenNoEncontradaError
            hasta = destino(Accion.INICIAR, orden.estado)
            if orden.mecanico_id is not None and orden.mecanico_id != usuario.id:
                raise OrdenAsignadaAOtroError
            await _exigir_estado_en_catalogo(uow, hasta)
            await _registrar_transicion(uow, orden, hasta, usuario.id, {"mecanico_id": usuario.id})
            return await _detalle_ordenado(uow, orden_id)
    except IntegrityError as exc:
        raise _error_desde(exc) from None


async def terminar_orden(uow: OrdenesUoW, orden_id: int, usuario: UsuarioActual) -> OrdenTrabajo:
    """EN_REPARACION -> TERMINADA descontando el stock de cada item, todo en un bloque (RN-13, D4/D5).

    Orden de evaluacion: 404 -> 403 (ADMIN o el mecanico asignado) -> 409 transicion -> 409 catalogo.
    Los items se procesan por ``repuesto_id`` ascendente (contrato de ``mover_stock``, sin
    interbloqueos). ``StockInsuficienteError`` atraviesa el ``async with`` (el UoW revierte stock,
    movimientos, estado e historial) y se traduce AQUI FUERA: capturarla dentro dejaria la
    transaccion abortada de PostgreSQL y daria 500.
    """
    codigos: dict[int, str] = {}
    try:
        async with uow:
            orden = await uow.ordenes.bloquear(orden_id)
            if orden is None:
                raise OrdenNoEncontradaError
            if Rol.ADMIN not in usuario.roles_vigentes and orden.mecanico_id != usuario.id:
                raise SinPermisoSobreOrdenError
            hasta = destino(Accion.TERMINAR, orden.estado)
            await _exigir_estado_en_catalogo(uow, hasta)

            detalle = await uow.ordenes.get_detalle(orden_id)
            assert detalle is not None
            codigos = {i.repuesto_id: i.repuesto.codigo for i in detalle.items}
            for item in sorted(detalle.items, key=lambda i: i.repuesto_id):
                await mover_stock(
                    uow,
                    repuesto_id=item.repuesto_id,
                    cantidad=-item.cantidad,
                    motivo=MOTIVO_ORDEN_TERMINADA,
                    usuario_id=usuario.id,
                    orden_id=orden.id,
                )
            await _registrar_transicion(uow, orden, hasta, usuario.id)
            return await _detalle_ordenado(uow, orden_id)
    except StockInsuficienteError as exc:
        raise StockInsuficienteOrdenError(codigos.get(exc.repuesto_id)) from None
    except (StockFueraDeRangoError, RepuestoNoEncontradoError):
        raise ConflictoError from None
    except IntegrityError as exc:
        raise _error_desde(exc) from None


async def cancelar_orden(uow: OrdenesUoW, orden_id: int, usuario: UsuarioActual) -> OrdenTrabajo:
    """PENDIENTE -> CANCELADA por RECEPCION, ADMIN o el dueno de la orden (RN-12, D4-b/c).

    404 -> 403 -> 409: el permiso se decide antes que el estado. Un MECANICO que no sea ademas
    RECEPCION/ADMIN ni dueno recibe 403. No toca stock ni mecanico.
    """
    try:
        async with uow:
            orden = await uow.ordenes.bloquear(orden_id)
            if orden is None:
                raise OrdenNoEncontradaError
            if not (usuario.roles_vigentes & _VE_TODAS):
                detalle = await uow.ordenes.get_detalle(orden_id)
                assert detalle is not None
                if detalle.vehiculo.cliente.usuario_id != usuario.id:
                    raise SinPermisoSobreOrdenError
            hasta = destino(Accion.CANCELAR, orden.estado)
            await _exigir_estado_en_catalogo(uow, hasta)
            await _registrar_transicion(uow, orden, hasta, usuario.id)
            return await _detalle_ordenado(uow, orden_id)
    except IntegrityError as exc:
        raise _error_desde(exc) from None
