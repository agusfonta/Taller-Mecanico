"""Router de ordenes de trabajo (grupo protegido, C-09, D11).

Un solo ``APIRouter`` con rutas absolutas (como el de clientes): las ocho van al grupo protegido.
Orden de evaluacion de cada peticion:

1. 401: sin sesion valida. 2. 403: cambio de contrasena pendiente (grupo) o rol insuficiente
(``requiere_rol``, roles de la BASE), SIEMPRE antes de validar el cuerpo o los parametros (422) y
de mirar el recurso. 3. 422: parametros o cuerpo invalidos. 4. 404 / 403 de dueno / 409: errores de
dominio traducidos aqui, sin exponer jamas texto de la base.

El detalle, "mis ordenes" y ``cancelar`` no usan ``requiere_rol``: el control de dueno (D8) vive en el
servicio. ``iniciar`` exige MECANICO y ``terminar`` MECANICO o ADMIN ya en la ruta (403 antes que 404);
el control fino "asignado o ADMIN" lo hace el servicio. Las transiciones no tienen cuerpo (SU-C10-2).
"""
from typing import Annotated, NoReturn

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from app.core.tipos import IdRuta
from app.core.dependencies import UsuarioActual, UsuarioActualDep, requiere_rol
from app.core.paginacion import Pagina, PaginacionDep
from app.modules.ordenes import service
from app.modules.ordenes.avisos import avisar_cliente
from app.modules.ordenes.models import EstadoOrdenCodigo
from app.modules.ordenes.schemas import EstadoOrdenRespuesta, OrdenAlta, OrdenDetalle, OrdenResumen
from app.modules.ordenes.unit_of_work import OrdenesUoWDep
from app.modules.usuarios.models import Rol

__all__ = ["router_ordenes"]

router_ordenes = APIRouter(tags=["ordenes"])

AbreOrdenes = Annotated[UsuarioActual, Depends(requiere_rol(Rol.RECEPCION, Rol.ADMIN))]
Iniciador = Annotated[UsuarioActual, Depends(requiere_rol(Rol.MECANICO))]
Terminador = Annotated[UsuarioActual, Depends(requiere_rol(Rol.MECANICO, Rol.ADMIN))]
LectorPersonal = Annotated[UsuarioActual, Depends(requiere_rol(Rol.ADMIN, Rol.RECEPCION, Rol.MECANICO))]


def _http_desde(exc: Exception) -> NoReturn:
    """Traduccion UNICA de errores de dominio a HTTP; jamas expone texto de la base."""
    if isinstance(exc, service.NoEncontradoError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.mensaje) from None
    if isinstance(exc, service.OrdenAjenaError):
        raise HTTPException(status.HTTP_403_FORBIDDEN, exc.mensaje) from None
    if isinstance(exc, service.ConflictoError):
        raise HTTPException(status.HTTP_409_CONFLICT, exc.mensaje) from None
    raise exc


@router_ordenes.post("/ordenes", status_code=status.HTTP_201_CREATED)
async def alta_orden(datos: OrdenAlta, usuario: AbreOrdenes, uow: OrdenesUoWDep) -> OrdenDetalle:
    try:
        orden = await service.crear_orden(uow, datos, usuario.id)
    except service.ConflictoError as exc:
        _http_desde(exc)
    return OrdenDetalle.model_validate(orden)


@router_ordenes.get("/ordenes")
async def listar_ordenes(
    usuario: LectorPersonal,
    uow: OrdenesUoWDep,
    params: PaginacionDep,
    estado: EstadoOrdenCodigo | None = None,
) -> Pagina[OrdenResumen]:
    items, total = await service.listar_ordenes(uow, estado, usuario, params)
    return Pagina.crear([OrdenResumen.model_validate(o) for o in items], total, params)


@router_ordenes.get("/ordenes/{orden_id}")
async def detalle_orden(orden_id: IdRuta, usuario: UsuarioActualDep, uow: OrdenesUoWDep) -> OrdenDetalle:
    try:
        orden = await service.obtener_orden(uow, orden_id, usuario)
    except (service.NoEncontradoError, service.OrdenAjenaError) as exc:
        _http_desde(exc)
    return OrdenDetalle.model_validate(orden)


@router_ordenes.get("/mis-ordenes")
async def mis_ordenes(usuario: UsuarioActualDep, uow: OrdenesUoWDep, params: PaginacionDep) -> Pagina[OrdenResumen]:
    """Solo lo propio (RN-17): el dueno sale de la sesion, nunca de un parametro."""
    items, total = await service.listar_mis_ordenes(uow, usuario.id, params)
    return Pagina.crear([OrdenResumen.model_validate(o) for o in items], total, params)


@router_ordenes.get("/estados-orden")
async def estados_orden(_: UsuarioActualDep, uow: OrdenesUoWDep) -> list[EstadoOrdenRespuesta]:
    estados = await service.listar_estados(uow)
    return [EstadoOrdenRespuesta.model_validate(e) for e in estados]


@router_ordenes.post("/ordenes/{orden_id}/iniciar", status_code=status.HTTP_200_OK)
async def iniciar_orden(orden_id: IdRuta, usuario: Iniciador, uow: OrdenesUoWDep) -> OrdenDetalle:
    try:
        orden = await service.iniciar_orden(uow, orden_id, usuario)
    except (service.NoEncontradoError, service.ConflictoError) as exc:
        _http_desde(exc)
    return OrdenDetalle.model_validate(orden)


@router_ordenes.post("/ordenes/{orden_id}/terminar", status_code=status.HTTP_200_OK)
async def terminar_orden(
    orden_id: IdRuta, usuario: Terminador, uow: OrdenesUoWDep, background_tasks: BackgroundTasks
) -> OrdenDetalle:
    try:
        orden = await service.terminar_orden(uow, orden_id, usuario)
    except (service.NoEncontradoError, service.OrdenAjenaError, service.ConflictoError) as exc:
        _http_desde(exc)
    # El servicio ya retorno: el UoW confirmo al salir del bloque. Recien ahora se agenda el aviso;
    # si el servicio hubiera lanzado, esta linea no se alcanza (D7).
    background_tasks.add_task(avisar_cliente, orden.vehiculo.cliente_id, orden.id)
    return OrdenDetalle.model_validate(orden)


@router_ordenes.post("/ordenes/{orden_id}/cancelar", status_code=status.HTTP_200_OK)
async def cancelar_orden(orden_id: IdRuta, usuario: UsuarioActualDep, uow: OrdenesUoWDep) -> OrdenDetalle:
    try:
        orden = await service.cancelar_orden(uow, orden_id, usuario)
    except (service.NoEncontradoError, service.OrdenAjenaError, service.ConflictoError) as exc:
        _http_desde(exc)
    return OrdenDetalle.model_validate(orden)
