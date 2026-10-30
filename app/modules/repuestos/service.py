"""Servicios de repuestos (C-08, D6/D7/D8).

* El servicio RECIBE el UoW ya construido por el router y lo abre con ``async with`` UNA vez por
  operacion; nunca lo construye ni confirma por su cuenta (lo hace el UoW al salir del bloque).
* El stock solo cambia por ``stock.mover_stock`` (RN-14), nunca por ``update``.
* La unicidad del codigo la garantiza la base (sin consulta previa): el ``IntegrityError``
  atraviesa el bloque, el UoW revierte y aqui se traduce por NOMBRE de restriccion, sin exponer
  jamas el texto de la base (RN-18).
"""
from collections.abc import Sequence

from sqlalchemy.exc import IntegrityError

from app.core.errores import restriccion_violada
from app.core.paginacion import ParametrosPaginacion, verificar_pagina
from app.modules.repuestos.models import (
    HistorialPrecioRepuesto,
    MovimientoStock,
    Repuesto,
)
from app.modules.repuestos.schemas import RepuestoAlta, RepuestoEdicion
from app.modules.repuestos.stock import (
    MOTIVO_REPOSICION,
    MOTIVO_STOCK_INICIAL,
    RepuestoNoEncontradoError,
    mover_stock,
)
from app.modules.repuestos.unit_of_work import RepuestosUoW

__all__ = [
    "CodigoDuplicadoError",
    "ConflictoError",
    "crear_repuesto",
    "dar_de_baja",
    "editar_repuesto",
    "listar_movimientos",
    "listar_precios",
    "listar_repuestos",
    "obtener_repuesto",
    "reponer",
]


class ConflictoError(Exception):
    """Los datos chocan con un registro existente (409)."""

    mensaje = "Los datos chocan con un registro existente"


class CodigoDuplicadoError(ConflictoError):
    mensaje = "Ya existe un repuesto vigente con ese código"


_CONFLICTOS_POR_RESTRICCION: dict[str, type[ConflictoError]] = {
    "uq_repuesto_codigo_vigente": CodigoDuplicadoError,
}


async def crear_repuesto(uow: RepuestosUoW, datos: RepuestoAlta, usuario_id: int) -> Repuesto:
    """Alta atomica: el repuesto nace en 0 y el stock entra SOLO por ``mover_stock`` (D7)."""
    try:
        async with uow:
            repuesto = await uow.repuestos.add(
                Repuesto(
                    codigo=datos.codigo,
                    descripcion=datos.descripcion,
                    precio=datos.precio,
                    stock=0,
                )
            )
            if datos.stock_inicial > 0:
                await mover_stock(
                    uow,
                    repuesto_id=repuesto.id,
                    cantidad=datos.stock_inicial,
                    motivo=MOTIVO_STOCK_INICIAL,
                    usuario_id=usuario_id,
                )
            return repuesto
    except IntegrityError as exc:
        nombre = restriccion_violada(exc) or ""
        raise _CONFLICTOS_POR_RESTRICCION.get(nombre, ConflictoError)() from None


async def obtener_repuesto(uow: RepuestosUoW, repuesto_id: int) -> Repuesto:
    async with uow:
        repuesto = await uow.repuestos.get_by_id(repuesto_id)
        if repuesto is None:
            raise RepuestoNoEncontradoError(repuesto_id)
        return repuesto


async def listar_repuestos(
    uow: RepuestosUoW, q: str | None, params: ParametrosPaginacion
) -> tuple[Sequence[Repuesto], int]:
    """Vigentes filtrados por ``q`` (ya recortado); total contado con el mismo filtro."""
    async with uow:
        total = await uow.repuestos.contar(q)
        verificar_pagina(params, total)
        items = await uow.repuestos.buscar(q, offset=params.offset, limit=params.size)
        return items, total


async def dar_de_baja(uow: RepuestosUoW, repuesto_id: int) -> None:
    """Baja logica (RN-16): no toca movimientos ni historial; con stock > 0 se permite."""
    async with uow:
        repuesto = await uow.repuestos.get_by_id(repuesto_id)
        if repuesto is None:
            raise RepuestoNoEncontradoError(repuesto_id)
        await uow.repuestos.soft_delete(repuesto)


async def editar_repuesto(
    uow: RepuestosUoW, repuesto_id: int, datos: RepuestoEdicion, usuario_id: int
) -> Repuesto:
    """PATCH de ``descripcion``/``precio`` (D6).

    Lee con ``FOR UPDATE`` para que dos cambios de precio concurrentes queden encadenados. La
    comparacion de precios es decimal (``8000 == 8000.00``): un precio igual al vigente no escribe
    ni deja linea de historial. La linea se agrega ANTES del ``update`` con el precio previo.
    """
    cambios = datos.model_dump(exclude_unset=True)
    async with uow:
        repuesto = await uow.repuestos.get_by_id_para_actualizar(repuesto_id)
        if repuesto is None:
            raise RepuestoNoEncontradoError(repuesto_id)
        if "precio" in cambios and cambios["precio"] == repuesto.precio:
            del cambios["precio"]
        if "precio" in cambios:
            await uow.precios.add(
                HistorialPrecioRepuesto(
                    repuesto_id=repuesto.id,
                    usuario_id=usuario_id,
                    precio_anterior=repuesto.precio,
                    precio_nuevo=cambios["precio"],
                )
            )
        if cambios:
            await uow.repuestos.update(repuesto, cambios)
        return repuesto


async def reponer(uow: RepuestosUoW, repuesto_id: int, cantidad: int, usuario_id: int) -> Repuesto:
    """Entrada de stock sobre un repuesto VIGENTE (404 si no); stock y movimiento atomicos."""
    async with uow:
        repuesto = await uow.repuestos.get_by_id(repuesto_id)
        if repuesto is None:
            raise RepuestoNoEncontradoError(repuesto_id)
        await mover_stock(
            uow,
            repuesto_id=repuesto_id,
            cantidad=cantidad,
            motivo=MOTIVO_REPOSICION,
            usuario_id=usuario_id,
        )
        return repuesto  # ``sumar_stock`` ya dejo el stock nuevo en la entidad cargada


async def listar_movimientos(
    uow: RepuestosUoW, repuesto_id: int, params: ParametrosPaginacion
) -> tuple[Sequence[MovimientoStock], int]:
    async with uow:
        if await uow.repuestos.get_by_id(repuesto_id) is None:
            raise RepuestoNoEncontradoError(repuesto_id)
        total = await uow.movimientos.contar_por_repuesto(repuesto_id)
        verificar_pagina(params, total)
        items = await uow.movimientos.listar_por_repuesto(
            repuesto_id, offset=params.offset, limit=params.size
        )
        return items, total


async def listar_precios(
    uow: RepuestosUoW, repuesto_id: int, params: ParametrosPaginacion
) -> tuple[Sequence[HistorialPrecioRepuesto], int]:
    async with uow:
        if await uow.repuestos.get_by_id(repuesto_id) is None:
            raise RepuestoNoEncontradoError(repuesto_id)
        total = await uow.precios.contar_por_repuesto(repuesto_id)
        verificar_pagina(params, total)
        items = await uow.precios.listar_por_repuesto(
            repuesto_id, offset=params.offset, limit=params.size
        )
        return items, total
