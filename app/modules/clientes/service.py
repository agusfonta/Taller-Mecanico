"""Servicios de clientes y vehiculos (C-07, D5, D6, D8).

* El servicio RECIBE el UoW ya construido por el router y lo abre con ``async with`` UNA vez por
  operacion; nunca lo construye ni confirma por su cuenta (lo hace el UoW al salir del bloque).
* La unicidad (documento, patente vigente) la garantiza la base, sin consulta previa (seria una
  carrera): el ``IntegrityError`` atraviesa el bloque, el UoW revierte y aqui se traduce por
  NOMBRE de restriccion, sin exponer jamas el texto de la base (RN-18).
* Los errores de dominio son excepciones propias con ``mensaje``; el router las traduce a HTTP.
"""
from collections.abc import Sequence

from sqlalchemy.exc import IntegrityError

from app.core.errores import restriccion_violada
from app.modules.clientes.models import Cliente, Vehiculo
from app.modules.clientes.schemas import ClienteEntrada, VehiculoEntrada
from app.modules.clientes.unit_of_work import ClientesUoW

__all__ = [
    "ClienteNoEncontradoError",
    "ConflictoError",
    "DocumentoRepetidoError",
    "NoEncontradoError",
    "PatenteVigenteRepetidaError",
    "VehiculoConOrdenesAbiertasError",
    "VehiculoNoEncontradoError",
    "crear_cliente",
    "crear_vehiculo",
    "dar_de_baja_vehiculo",
    "listar_mis_vehiculos",
    "obtener_cliente",
]


class NoEncontradoError(Exception):
    """Un recurso nombrado en la ruta no existe (404)."""

    mensaje = "Recurso no encontrado"


class ClienteNoEncontradoError(NoEncontradoError):
    mensaje = "Cliente no encontrado"


class VehiculoNoEncontradoError(NoEncontradoError):
    mensaje = "Vehículo no encontrado"


class ConflictoError(Exception):
    """Los datos chocan con un registro existente (409)."""

    mensaje = "Los datos chocan con un registro existente"


class DocumentoRepetidoError(ConflictoError):
    mensaje = "El documento ya pertenece a un cliente del taller"


class PatenteVigenteRepetidaError(ConflictoError):
    mensaje = "Ya hay un vehículo vigente con esa patente"


class VehiculoConOrdenesAbiertasError(ConflictoError):
    mensaje = "El vehículo tiene órdenes abiertas"


_CONFLICTOS_POR_RESTRICCION: dict[str, type[ConflictoError]] = {
    "uq_cliente_documento": DocumentoRepetidoError,
    "uq_vehiculo_patente_vigente": PatenteVigenteRepetidaError,
}
_NO_ENCONTRADOS_POR_RESTRICCION: dict[str, type[NoEncontradoError]] = {
    "fk_vehiculo_cliente_id_cliente": ClienteNoEncontradoError,
}


def _error_desde(exc: IntegrityError) -> Exception:
    """Error de dominio segun la restriccion violada; generico si no se la conoce."""
    nombre = restriccion_violada(exc)
    if nombre in _NO_ENCONTRADOS_POR_RESTRICCION:
        return _NO_ENCONTRADOS_POR_RESTRICCION[nombre]()
    return _CONFLICTOS_POR_RESTRICCION.get(nombre or "", ConflictoError)()


async def crear_cliente(uow: ClientesUoW, datos: ClienteEntrada) -> Cliente:
    """Ficha sin usuario vinculado (``usuario_id`` nulo); documento unico por la base."""
    try:
        async with uow:
            return await uow.clientes.add(Cliente(usuario_id=None, **datos.model_dump()))
    except IntegrityError as exc:
        raise _error_desde(exc) from None


async def obtener_cliente(uow: ClientesUoW, cliente_id: int) -> Cliente:
    """Cliente con SOLO sus vehiculos vigentes precargados; ``vehiculos`` queda ordenado por id."""
    async with uow:
        cliente = await uow.clientes.get_con_vehiculos_vigentes(cliente_id)
        if cliente is None:
            raise ClienteNoEncontradoError
        cliente.vehiculos.sort(key=lambda v: v.id)
        return cliente


async def crear_vehiculo(uow: ClientesUoW, cliente_id: int, datos: VehiculoEntrada) -> Vehiculo:
    """Alta de un vehiculo vigente. La existencia del cliente es una lectura (404), no unicidad."""
    try:
        async with uow:
            if await uow.clientes.get_by_id(cliente_id) is None:
                raise ClienteNoEncontradoError
            return await uow.vehiculos.add(Vehiculo(cliente_id=cliente_id, **datos.model_dump()))
    except IntegrityError as exc:
        raise _error_desde(exc) from None


async def dar_de_baja_vehiculo(uow: ClientesUoW, vehiculo_id: int) -> None:
    """Baja logica (RN-16): bloquea la fila, rechaza si hay ordenes abiertas y marca ``borrado_en``."""
    async with uow:
        vehiculo = await uow.vehiculos.get_vigente_para_baja(vehiculo_id)
        if vehiculo is None:
            raise VehiculoNoEncontradoError
        if await uow.vehiculos.tiene_ordenes_abiertas(vehiculo_id):
            raise VehiculoConOrdenesAbiertasError
        await uow.vehiculos.soft_delete(vehiculo)


async def listar_mis_vehiculos(uow: ClientesUoW, usuario_id: int) -> Sequence[Vehiculo]:
    """Vehiculos vigentes de la ficha del usuario (RN-17); sin ficha, lista vacia."""
    async with uow:
        return await uow.vehiculos.listar_vigentes_de_usuario(usuario_id)
