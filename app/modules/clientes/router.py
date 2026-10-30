"""Router de clientes y vehiculos (grupo protegido, C-07, D2/D8).

Un solo ``APIRouter`` con rutas absolutas: las cinco van al mismo grupo (protegido).
Orden de evaluacion de cada peticion:

1. 401: sin sesion valida (``leer_claims``).
2. 403: cambio de contrasena pendiente (grupo) o rol insuficiente (``requiere_rol``, roles de la
   BASE, siempre ANTES de mirar el recurso).
3. 422: parametros o cuerpo invalidos (con sesion de personal).
4. 404 / 409: recurso inexistente o conflicto, traducidos desde errores de dominio.

Los handlers son ``async def`` y delgados: el UoW llega construido (sin abrir) y la logica vive
en el servicio.
"""
from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.core.tipos import IdRuta
from app.core.dependencies import UsuarioActualDep, requiere_rol
from app.modules.clientes import service
from app.modules.clientes.schemas import (
    ClienteDetalleRespuesta,
    ClienteEntrada,
    ClienteRespuesta,
    VehiculoEntrada,
    VehiculoRespuesta,
)
from app.modules.clientes.unit_of_work import ClientesUoWDep
from app.modules.usuarios.models import Rol

__all__ = ["router"]

router = APIRouter(tags=["clientes"])

SOLO_PERSONAL = [Depends(requiere_rol(Rol.RECEPCION, Rol.ADMIN))]


def _http_desde(exc: Exception) -> NoReturn:
    """Traduccion UNICA de errores de dominio a HTTP; jamas expone texto de la base."""
    if isinstance(exc, service.NoEncontradoError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.mensaje) from None
    if isinstance(exc, service.ConflictoError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.mensaje) from None
    raise exc


@router.post("/clientes", status_code=status.HTTP_201_CREATED, dependencies=SOLO_PERSONAL)
async def alta_cliente(datos: ClienteEntrada, uow: ClientesUoWDep) -> ClienteRespuesta:
    try:
        cliente = await service.crear_cliente(uow, datos)
    except service.ConflictoError as exc:
        _http_desde(exc)
    return ClienteRespuesta.model_validate(cliente)


@router.get("/clientes/{cliente_id}", dependencies=SOLO_PERSONAL)
async def detalle_cliente(cliente_id: IdRuta, uow: ClientesUoWDep) -> ClienteDetalleRespuesta:
    try:
        cliente = await service.obtener_cliente(uow, cliente_id)
    except service.NoEncontradoError as exc:
        _http_desde(exc)
    return ClienteDetalleRespuesta.model_validate(cliente)


@router.post(
    "/clientes/{cliente_id}/vehiculos", status_code=status.HTTP_201_CREATED, dependencies=SOLO_PERSONAL
)
async def alta_vehiculo(cliente_id: IdRuta, datos: VehiculoEntrada, uow: ClientesUoWDep) -> VehiculoRespuesta:
    try:
        vehiculo = await service.crear_vehiculo(uow, cliente_id, datos)
    except (service.NoEncontradoError, service.ConflictoError) as exc:
        _http_desde(exc)
    return VehiculoRespuesta.model_validate(vehiculo)


@router.delete(
    "/vehiculos/{vehiculo_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=SOLO_PERSONAL
)
async def baja_vehiculo(vehiculo_id: IdRuta, uow: ClientesUoWDep) -> Response:
    try:
        await service.dar_de_baja_vehiculo(uow, vehiculo_id)
    except (service.NoEncontradoError, service.ConflictoError) as exc:
        _http_desde(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/mis-vehiculos")
async def mis_vehiculos(usuario: UsuarioActualDep, uow: ClientesUoWDep) -> list[VehiculoRespuesta]:
    """Solo lo propio (RN-17): el dueño sale de la sesion, nunca de un parametro."""
    vehiculos = await service.listar_mis_vehiculos(uow, usuario.id)
    return [VehiculoRespuesta.model_validate(v) for v in vehiculos]
