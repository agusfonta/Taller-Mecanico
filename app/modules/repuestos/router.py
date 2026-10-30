"""Router de repuestos (grupo protegido, C-08, D2/D7).

Orden de evaluacion de cada peticion:

1. 401: sin sesion valida. 2. 403: cambio de contrasena pendiente (grupo) o rol insuficiente
(``requiere_rol``, roles de la BASE), SIEMPRE antes de mirar el recurso (404) o validar un cuerpo
JSON bien formado (422). 3. 422: parametros o cuerpo invalidos. 4. 404 / 409: errores de dominio
traducidos aqui, sin exponer jamas texto de la base.
"""
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import StringConstraints

from app.core.tipos import IdRuta
from app.core.dependencies import UsuarioActual, requiere_rol
from app.core.paginacion import Pagina, PaginacionDep
from app.modules.repuestos import service
from app.modules.repuestos.schemas import (
    MovimientoRespuesta,
    PrecioHistorialRespuesta,
    Reposicion,
    RepuestoAlta,
    RepuestoEdicion,
    RepuestoRespuesta,
)
from app.modules.repuestos.stock import (
    RepuestoNoEncontradoError,
    StockFueraDeRangoError,
    StockInsuficienteError,
)
from app.modules.repuestos.unit_of_work import RepuestosUoWDep
from app.modules.usuarios.models import Rol

__all__ = ["router_repuestos"]

router_repuestos = APIRouter(prefix="/repuestos", tags=["repuestos"])

LectorCatalogo = Annotated[
    UsuarioActual, Depends(requiere_rol(Rol.ADMIN, Rol.RECEPCION, Rol.MECANICO))
]
AdminDep = Annotated[UsuarioActual, Depends(requiere_rol(Rol.ADMIN))]

Busqueda = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


def _http_desde(exc: Exception) -> NoReturn:
    """Traduccion UNICA de errores de dominio a HTTP; jamas expone texto de la base."""
    if isinstance(exc, RepuestoNoEncontradoError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Repuesto no encontrado") from None
    if isinstance(exc, StockFueraDeRangoError):
        raise HTTPException(status.HTTP_409_CONFLICT, "La reposición supera el stock máximo admitido") from None
    if isinstance(exc, StockInsuficienteError):
        raise HTTPException(status.HTTP_409_CONFLICT, "Stock insuficiente") from None
    if isinstance(exc, service.ConflictoError):
        raise HTTPException(status.HTTP_409_CONFLICT, exc.mensaje) from None
    raise exc


@router_repuestos.post("", status_code=status.HTTP_201_CREATED)
async def alta_repuesto(datos: RepuestoAlta, usuario: AdminDep, uow: RepuestosUoWDep) -> RepuestoRespuesta:
    try:
        repuesto = await service.crear_repuesto(uow, datos, usuario.id)
    except service.ConflictoError as exc:
        _http_desde(exc)
    return RepuestoRespuesta.model_validate(repuesto)


@router_repuestos.get("")
async def listar_repuestos(
    _: LectorCatalogo,
    uow: RepuestosUoWDep,
    params: PaginacionDep,
    q: Annotated[Busqueda | None, Query(description="Texto literal a buscar en la descripción")] = None,
) -> Pagina[RepuestoRespuesta]:
    items, total = await service.listar_repuestos(uow, q, params)
    return Pagina.crear([RepuestoRespuesta.model_validate(i) for i in items], total, params)


@router_repuestos.get("/{repuesto_id}")
async def detalle_repuesto(repuesto_id: IdRuta, _: LectorCatalogo, uow: RepuestosUoWDep) -> RepuestoRespuesta:
    try:
        repuesto = await service.obtener_repuesto(uow, repuesto_id)
    except RepuestoNoEncontradoError as exc:
        _http_desde(exc)
    return RepuestoRespuesta.model_validate(repuesto)


@router_repuestos.patch("/{repuesto_id}")
async def editar_repuesto(
    repuesto_id: IdRuta, datos: RepuestoEdicion, usuario: AdminDep, uow: RepuestosUoWDep
) -> RepuestoRespuesta:
    try:
        repuesto = await service.editar_repuesto(uow, repuesto_id, datos, usuario.id)
    except RepuestoNoEncontradoError as exc:
        _http_desde(exc)
    return RepuestoRespuesta.model_validate(repuesto)


@router_repuestos.delete("/{repuesto_id}", status_code=status.HTTP_204_NO_CONTENT)
async def baja_repuesto(repuesto_id: IdRuta, _: AdminDep, uow: RepuestosUoWDep) -> Response:
    try:
        await service.dar_de_baja(uow, repuesto_id)
    except RepuestoNoEncontradoError as exc:
        _http_desde(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router_repuestos.post("/{repuesto_id}/reponer")
async def reponer_repuesto(
    repuesto_id: IdRuta, datos: Reposicion, usuario: AdminDep, uow: RepuestosUoWDep
) -> RepuestoRespuesta:
    try:
        repuesto = await service.reponer(uow, repuesto_id, datos.cantidad, usuario.id)
    except (RepuestoNoEncontradoError, StockFueraDeRangoError) as exc:
        _http_desde(exc)
    return RepuestoRespuesta.model_validate(repuesto)


@router_repuestos.get("/{repuesto_id}/movimientos")
async def movimientos_de_repuesto(
    repuesto_id: IdRuta, _: AdminDep, uow: RepuestosUoWDep, params: PaginacionDep
) -> Pagina[MovimientoRespuesta]:
    try:
        items, total = await service.listar_movimientos(uow, repuesto_id, params)
    except RepuestoNoEncontradoError as exc:
        _http_desde(exc)
    return Pagina.crear([MovimientoRespuesta.model_validate(i) for i in items], total, params)


@router_repuestos.get("/{repuesto_id}/precios")
async def precios_de_repuesto(
    repuesto_id: IdRuta, _: AdminDep, uow: RepuestosUoWDep, params: PaginacionDep
) -> Pagina[PrecioHistorialRespuesta]:
    try:
        items, total = await service.listar_precios(uow, repuesto_id, params)
    except RepuestoNoEncontradoError as exc:
        _http_desde(exc)
    return Pagina.crear([PrecioHistorialRespuesta.model_validate(i) for i in items], total, params)
