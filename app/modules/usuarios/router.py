"""Router ``/auth`` (grupo abierto, C-05): registro, login, logout, yo y cambio de contrasena.

Cada handler es ``async def`` y delgado: construye lo que el servicio necesita (UoW sin abrir,
servicio de contrasenas), llama al servicio y traduce errores de dominio a HTTP. C-06 agregara
en este archivo ``router_usuarios`` (grupo protegido): son dos ``APIRouter`` porque van a
grupos distintos.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.core.tipos import IdRuta
from app.core.dependencies import (
    ContrasenasDep,
    HashFicticioDep,
    SettingsDep,
    UsuarioActualDep,
    requiere_rol,
)
from app.core.paginacion import PaginacionDep, Pagina
from app.core.security import borrar_cookie_sesion, emitir_token, poner_cookie_sesion
from app.modules.usuarios import service
from app.modules.usuarios.models import IntentoAcceso, Rol
from app.modules.usuarios.schemas import (
    AltaPersonalEntrada,
    AsignacionRespuesta,
    AsignarRolEntrada,
    CambioPasswordEntrada,
    EventoRespuesta,
    LoginEntrada,
    LoginRespuesta,
    MensajeRespuesta,
    RegistroEntrada,
    RegistroRespuesta,
    RolesUsuarioRespuesta,
    UsuarioCreadoRespuesta,
    YoRespuesta,
)
from app.modules.usuarios.unit_of_work import UsuariosUoW, UsuariosUoWDep

__all__ = ["get_registro_intentos", "router_auth", "router_eventos", "router_usuarios"]

router_auth = APIRouter(prefix="/auth", tags=["auth"])

MENSAJE_CREDENCIALES = "Correo o contraseña incorrectos"
MENSAJE_DEMASIADOS_INTENTOS = "Demasiados intentos fallidos; intente más tarde"


def get_registro_intentos(request: Request) -> service.RegistroIntentos:
    """Colaborador que anota un intento de login en sesion y transaccion PROPIAS (DD-05).

    Es la UNICA escritura fuera de la transaccion de su peticion, y es deliberada: la fila de
    ``intento_acceso`` debe quedar confirmada aunque la peticion termine en 401 o en error,
    porque es lo que alimenta el limite de 5 fallos. Costo: una conexion extra del pool durante
    un INSERT breve por cada login verificado, y filas que persisten aunque el resto falle.
    """
    fabrica = request.app.state.session_factory

    async def registrar(email: str, ip: str, exito: bool, cuando: datetime) -> None:
        async with fabrica() as sesion:
            async with UsuariosUoW(sesion) as uow:
                await uow.intentos.add(IntentoAcceso(email=email, ip=ip, exito=exito, cuando=cuando))

    return registrar


@router_auth.post("/registro", status_code=status.HTTP_201_CREATED)
async def registro(
    datos: RegistroEntrada, uow: UsuariosUoWDep, contrasenas: ContrasenasDep
) -> RegistroRespuesta:
    try:
        usuario, cliente = await service.registrar_cliente(uow, contrasenas, datos)
    except service.ConflictoError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.mensaje) from None
    return RegistroRespuesta(
        id=usuario.id,
        email=usuario.email,
        nombre=usuario.nombre,
        cliente_id=cliente.id,
        roles=["CLIENTE"],
    )


@router_auth.post("/login")
async def login(
    datos: LoginEntrada,
    request: Request,
    response: Response,
    uow: UsuariosUoWDep,
    contrasenas: ContrasenasDep,
    hash_ficticio: HashFicticioDep,
    settings: SettingsDep,
) -> LoginRespuesta:
    # Sin X-Forwarded-For: es falsificable (SU-C05-4). Detras de un proxy, usar --proxy-headers.
    ip = request.client.host if request.client else "desconocida"
    registrar = get_registro_intentos(request)
    try:
        resultado = await service.iniciar_sesion(
            uow, registrar, contrasenas, hash_ficticio, datos.email, datos.password, ip
        )
    except service.DemasiadosIntentosError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=MENSAJE_DEMASIADOS_INTENTOS,
            headers={"Retry-After": str(exc.retry_after)},
        ) from None
    except service.CredencialesInvalidasError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=MENSAJE_CREDENCIALES) from None
    token = emitir_token(resultado.usuario_id, resultado.roles, settings)
    poner_cookie_sesion(response, token, settings)
    return LoginRespuesta(
        mensaje="Sesión iniciada",
        debe_cambiar_password=resultado.debe_cambiar_password,
        expira_en_segundos=settings.jwt_expire_seconds,
    )


@router_auth.post("/logout")
async def logout(response: Response, settings: SettingsDep) -> MensajeRespuesta:
    """Idempotente y sin sesion requerida: siempre borra la cookie y responde 200 (IN-04)."""
    borrar_cookie_sesion(response, settings)
    return MensajeRespuesta(mensaje="Sesión cerrada")


@router_auth.get("/yo")
async def yo(usuario: UsuarioActualDep) -> YoRespuesta:
    """Disponible aun con el cambio de contrasena pendiente (grupo abierto, sin ``exigir_acceso``)."""
    return YoRespuesta(
        id=usuario.id,
        email=usuario.email,
        nombre=usuario.nombre,
        debe_cambiar_password=usuario.debe_cambiar_password,
        roles_vigentes=sorted(rol.value for rol in usuario.roles_vigentes),
        roles_token=sorted(usuario.roles_token),
    )


@router_auth.post("/cambiar-password")
async def cambiar_password(
    datos: CambioPasswordEntrada,
    usuario: UsuarioActualDep,
    response: Response,
    uow: UsuariosUoWDep,
    contrasenas: ContrasenasDep,
    settings: SettingsDep,
) -> MensajeRespuesta:
    """Grupo abierto (con ``UsuarioActualDep``, sin ``exigir_acceso``): funciona con el cambio pendiente."""
    try:
        await service.cambiar_password(uow, contrasenas, usuario, datos.password_actual, datos.password_nueva)
    except service.PasswordActualIncorrectaError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="La contraseña actual no es correcta"
        ) from None
    # Despues del commit: su iat es posterior a password_cambiada_en, asi que esta sesion vale
    # y toda anterior (aun del mismo segundo) queda invalida (RN-07).
    token = emitir_token(usuario.id, sorted(rol.value for rol in usuario.roles_vigentes), settings)
    poner_cookie_sesion(response, token, settings)
    return MensajeRespuesta(mensaje="Contraseña actualizada")


# --- C-06: administracion de personal, roles y eventos (grupo protegido, solo ADMIN, D1) -------
# ``requiere_rol`` a nivel de router: FastAPI resuelve las dependencias antes de validar ruta y
# cuerpo, asi que un no-ADMIN con cuerpo invalido recibe 403 (no 422) y jamas se calcula un hash.
_solo_admin = [Depends(requiere_rol(Rol.ADMIN))]
router_usuarios = APIRouter(prefix="/usuarios", tags=["usuarios"], dependencies=_solo_admin)
router_eventos = APIRouter(prefix="/eventos", tags=["eventos"], dependencies=_solo_admin)


def _http_desde(exc: Exception) -> HTTPException:
    """Traduccion UNICA de errores de dominio a HTTP (D9); jamas expone texto de la base."""
    if isinstance(exc, service.NoEncontradoError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.mensaje)
    if isinstance(exc, service.ConflictoError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.mensaje)
    raise exc


@router_usuarios.post("", status_code=status.HTTP_201_CREATED)
async def alta_personal(
    datos: AltaPersonalEntrada,
    actor: UsuarioActualDep,
    uow: UsuariosUoWDep,
    contrasenas: ContrasenasDep,
) -> UsuarioCreadoRespuesta:
    try:
        usuario, asignacion = await service.dar_alta_personal(uow, contrasenas, actor, datos)
    except service.ConflictoError as exc:
        raise _http_desde(exc) from None
    return UsuarioCreadoRespuesta(
        id=usuario.id,
        email=usuario.email,
        nombre=usuario.nombre,
        debe_cambiar_password=usuario.debe_cambiar_password,
        roles=[asignacion.rol],
    )


def _asignacion_respuesta(asignacion, momento: datetime) -> AsignacionRespuesta:
    return AsignacionRespuesta(
        id=asignacion.id,
        usuario_id=asignacion.usuario_id,
        rol=asignacion.rol,
        desde=asignacion.desde,
        vence_en=asignacion.vence_en,
        revocada_en=asignacion.revocada_en,
        otorgada_por=asignacion.otorgada_por,
        vigente=service.esta_vigente(asignacion, momento),
    )


@router_usuarios.get("/{usuario_id}/roles")
async def roles_de_usuario(usuario_id: IdRuta, uow: UsuariosUoWDep) -> RolesUsuarioRespuesta:
    try:
        resultado = await service.roles_de_usuario(uow, usuario_id)
    except service.NoEncontradoError as exc:
        raise _http_desde(exc) from None
    return RolesUsuarioRespuesta(
        usuario_id=resultado.usuario.id,
        email=resultado.usuario.email,
        roles_vigentes=resultado.roles_vigentes,
        asignaciones=[_asignacion_respuesta(a, resultado.momento) for a in resultado.asignaciones],
    )


@router_usuarios.post("/{usuario_id}/roles", status_code=status.HTTP_201_CREATED)
async def asignar_rol(
    usuario_id: IdRuta, datos: AsignarRolEntrada, actor: UsuarioActualDep, uow: UsuariosUoWDep
) -> AsignacionRespuesta:
    try:
        asignacion = await service.asignar_rol(uow, actor, usuario_id, datos)
    except (service.NoEncontradoError, service.ConflictoError) as exc:
        raise _http_desde(exc) from None
    return _asignacion_respuesta(asignacion, service.ahora())


@router_usuarios.delete("/{usuario_id}/roles/{rol}")
async def revocar_rol(
    usuario_id: IdRuta, rol: Rol, actor: UsuarioActualDep, uow: UsuariosUoWDep
) -> AsignacionRespuesta:
    """Efecto en la peticion siguiente: ``get_usuario_actual`` relee los roles de la base (DD-01)."""
    try:
        asignacion = await service.revocar_rol(uow, actor, usuario_id, rol)
    except (service.NoEncontradoError, service.ConflictoError) as exc:
        raise _http_desde(exc) from None
    return _asignacion_respuesta(asignacion, service.ahora())


@router_eventos.get("")
async def listar_eventos(uow: UsuariosUoWDep, params: PaginacionDep) -> Pagina[EventoRespuesta]:
    """Mas reciente primero (``cuando DESC, id DESC``); ve TODOS los eventos, sin filtros (D7)."""
    items, total = await service.listar_eventos(uow, params)
    return Pagina.crear(
        [EventoRespuesta(id=e.id, cuando=e.cuando, actor=e.actor, accion=e.accion) for e in items],
        total,
        params,
    )
