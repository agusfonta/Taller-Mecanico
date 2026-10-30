"""Servicios de autenticacion: registro, login y cambio de contrasena (C-05, D7-D9).

Reglas que ordenan este modulo:

* El servicio RECIBE el UoW ya construido por el router y lo abre con ``async with``; nunca lo
  construye ni confirma por su cuenta (la confirmacion es del UoW al salir del bloque).
* bcrypt solo via ``ServicioContrasenas`` y SIEMPRE fuera de una transaccion abierta: el hash
  se calcula antes de abrir el bloque (DD-06), para no retener una conexion del pool ~300 ms.
* Los errores de dominio son excepciones propias; el router las traduce a codigos HTTP.
"""
import math
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError

from app.core.dependencies import UsuarioActual
from app.core.errores import restriccion_violada
from app.core.paginacion import ParametrosPaginacion, verificar_pagina
from app.core.security import ServicioContrasenas
from app.modules.clientes.models import Cliente
from app.modules.usuarios.models import AsignacionRol, EventoSeguridad, Rol, Usuario
from app.modules.usuarios.schemas import AltaPersonalEntrada, AsignarRolEntrada, RegistroEntrada
from app.modules.usuarios.unit_of_work import UsuariosUoW

__all__ = [
    "ConflictoError",
    "CorreoYaRegistradoError",
    "CredencialesInvalidasError",
    "PasswordActualIncorrectaError",
    "DemasiadosIntentosError",
    "DocumentoYaRegistradoError",
    "AsignacionNoEncontradaError",
    "AutoRevocacionAdminError",
    "MAX_FALLOS",
    "NoEncontradoError",
    "RolYaAsignadoError",
    "UltimoAdminError",
    "UsuarioNoEncontradoError",
    "RegistroIntentos",
    "ResultadoLogin",
    "VENTANA",
    "RolesDeUsuario",
    "ahora",
    "asignar_rol",
    "cambiar_password",
    "dar_alta_personal",
    "esta_vigente",
    "iniciar_sesion",
    "listar_eventos",
    "registrar_cliente",
    "revocar_rol",
    "roles_de_usuario",
]

ACCION_REGISTRO = "Registro de cliente"
ACCION_CAMBIO_PASSWORD = "Cambio de contraseña"


def accion_asignacion(email: str, rol: Rol | str, vence_en: datetime | None) -> str:
    texto = f"Asignación de rol {Rol(rol).value} a {email}"
    if vence_en is not None:
        texto += f" hasta {vence_en.astimezone(UTC).isoformat()}"
    return texto


def accion_revocacion(email: str, rol: Rol | str) -> str:
    return f"Revocación de rol {Rol(rol).value} a {email}"


def accion_alta_personal(email: str, rol: Rol | str) -> str:
    return f"Alta de personal: {email} con rol {Rol(rol).value}"

# Fijados por RN-08: no son configurables.
MAX_FALLOS = 5
VENTANA = timedelta(seconds=60)

RegistroIntentos = Callable[[str, str, bool, datetime], Awaitable[None]]
"""``(email, ip, exito, cuando)``: anota un intento en sesion y transaccion PROPIAS."""


def ahora() -> datetime:
    """Reloj unico de la app para intentos y ventana (sustituible en tests).

    No se usa ``now()`` de la base: es la hora de INICIO de la transaccion y mezclaria dos
    relojes con el ``default_factory`` de los modelos.
    """
    return datetime.now(UTC)


class ConflictoError(Exception):
    """Los datos chocan con un registro existente (409)."""

    mensaje = "Los datos chocan con un registro existente"


class NoEncontradoError(Exception):
    """Un recurso nombrado en la ruta no existe (404); espejo de ``ConflictoError``."""

    mensaje = "Recurso no encontrado"


class UsuarioNoEncontradoError(NoEncontradoError):
    mensaje = "Usuario no encontrado"


class AsignacionNoEncontradaError(NoEncontradoError):
    mensaje = "El usuario no tiene ese rol asignado"


class CorreoYaRegistradoError(ConflictoError):
    mensaje = "El correo ya está registrado"


class DocumentoYaRegistradoError(ConflictoError):
    mensaje = "El documento ya pertenece a un cliente del taller"


class RolYaAsignadoError(ConflictoError):
    mensaje = "El usuario ya tiene ese rol asignado"


class AutoRevocacionAdminError(ConflictoError):
    mensaje = "No puede revocarse su propio rol ADMIN"


class UltimoAdminError(ConflictoError):
    mensaje = "El sistema debe conservar al menos un administrador"


_CONFLICTOS_POR_RESTRICCION: dict[str, type[ConflictoError]] = {
    "uq_usuario_email": CorreoYaRegistradoError,
    "uq_asignacion_rol_abierta": RolYaAsignadoError,
    "uq_cliente_documento": DocumentoYaRegistradoError,
}


async def registrar_cliente(
    uow: UsuariosUoW, contrasenas: ServicioContrasenas, datos: RegistroEntrada
) -> tuple[Usuario, Cliente]:
    """Alta atomica de usuario + rol CLIENTE + ficha + evento (RN-01, RN-02).

    La unicidad la garantiza la base (sin consulta previa, que seria una carrera): un
    ``IntegrityError`` en cualquier ``flush`` atraviesa el bloque, el UoW revierte TODO y aqui
    se traduce por nombre de restriccion, sin exponer nunca el texto de la base (RN-18).
    """
    hash_ = await contrasenas.hashear(datos.password)
    try:
        async with uow:
            usuario = await uow.usuarios.add(
                Usuario(email=datos.email, nombre=datos.nombre, password_hash=hash_)
            )
            await uow.asignaciones.add(
                AsignacionRol(usuario_id=usuario.id, rol=Rol.CLIENTE.value, otorgada_por=None)
            )
            cliente = await uow.clientes.add(
                Cliente(
                    usuario_id=usuario.id,
                    nombre=datos.nombre,
                    documento=datos.documento,
                    telefono=datos.telefono,
                )
            )
            await uow.eventos.add(EventoSeguridad(actor=datos.email, accion=ACCION_REGISTRO))
    except IntegrityError as exc:
        raise _conflicto_desde(exc) from None
    return usuario, cliente


async def _abrir_asignacion(
    uow: UsuariosUoW, usuario: Usuario, rol: Rol, vence_en: datetime | None, actor: UsuarioActual
) -> AsignacionRol:
    """Abre una asignacion de ``rol`` para ``usuario`` (D3); compartida por el alta y ``POST /roles``.

    Sin ``abierta`` -> inserta. ``abierta`` vigente -> ``RolYaAsignadoError``. ``abierta`` vencida
    -> la cierra (``revocada_en``, con flush inmediato: sale del indice parcial ANTES del INSERT)
    y abre la nueva. La unicidad la garantiza ``uq_asignacion_rol_abierta``: en carrera, el
    ``IntegrityError`` del segundo se traduce a 409 aguas arriba.
    """
    momento = ahora()
    abierta = await uow.asignaciones.abierta(usuario.id, rol)
    if abierta is not None:
        if abierta.vence_en is None or abierta.vence_en > momento:
            raise RolYaAsignadoError
        await uow.asignaciones.update(abierta, {"revocada_en": momento})
    return await uow.asignaciones.add(
        AsignacionRol(usuario_id=usuario.id, rol=rol.value, vence_en=vence_en, otorgada_por=actor.id)
    )


async def dar_alta_personal(
    uow: UsuariosUoW,
    contrasenas: ServicioContrasenas,
    actor: UsuarioActual,
    datos: AltaPersonalEntrada,
) -> tuple[Usuario, AsignacionRol]:
    """Alta de personal (D2): usuario + rol inicial + UN evento, en un unico bloque.

    El hash se calcula ANTES de abrir la transaccion (DD-06). El usuario nace activo y con
    ``debe_cambiar_password`` (RN-06). La unicidad del correo la decide la base.
    """
    hash_ = await contrasenas.hashear(datos.password)
    rol = Rol(datos.rol)
    try:
        async with uow:
            usuario = await uow.usuarios.add(
                Usuario(
                    email=datos.email,
                    nombre=datos.nombre,
                    password_hash=hash_,
                    activo=True,
                    debe_cambiar_password=True,
                )
            )
            asignacion = await _abrir_asignacion(uow, usuario, rol, None, actor)
            await uow.eventos.add(
                EventoSeguridad(actor=actor.email, accion=accion_alta_personal(usuario.email, rol))
            )
    except IntegrityError as exc:
        raise _conflicto_desde(exc) from None
    return usuario, asignacion


def esta_vigente(asignacion: AsignacionRol, momento: datetime) -> bool:
    """No revocada y sin vencer a ``momento`` (misma regla que ``roles_vigentes``, RN-04)."""
    return asignacion.revocada_en is None and (
        asignacion.vence_en is None or asignacion.vence_en > momento
    )


async def asignar_rol(
    uow: UsuariosUoW, actor: UsuarioActual, usuario_id: int, datos: AsignarRolEntrada
) -> AsignacionRol:
    """``POST /usuarios/{id}/roles`` (D3): 404 del usuario antes que el 409; un unico evento."""
    try:
        async with uow:
            usuario = await uow.usuarios.get_by_id(usuario_id)
            if usuario is None:
                raise UsuarioNoEncontradoError
            asignacion = await _abrir_asignacion(uow, usuario, datos.rol, datos.vence_en, actor)
            await uow.eventos.add(
                EventoSeguridad(
                    actor=actor.email,
                    accion=accion_asignacion(usuario.email, datos.rol, datos.vence_en),
                )
            )
    except IntegrityError as exc:
        raise _conflicto_desde(exc) from None
    return asignacion


@dataclass(frozen=True, slots=True)
class RolesDeUsuario:
    """Usuario, historial y el ``momento`` con el que se evaluo la vigencia (coherente en todo)."""

    usuario: Usuario
    asignaciones: Sequence[AsignacionRol]
    momento: datetime

    @property
    def roles_vigentes(self) -> list[str]:
        return sorted({a.rol for a in self.asignaciones if esta_vigente(a, self.momento)})


async def roles_de_usuario(uow: UsuariosUoW, usuario_id: int) -> RolesDeUsuario:
    """``GET /usuarios/{id}/roles`` (D8): un bloque, un solo ``ahora()`` para todo."""
    momento = ahora()
    async with uow:
        usuario = await uow.usuarios.get_by_id(usuario_id)
        if usuario is None:
            raise UsuarioNoEncontradoError
        historial = await uow.asignaciones.historial(usuario_id)
    return RolesDeUsuario(usuario=usuario, asignaciones=historial, momento=momento)


async def revocar_rol(uow: UsuariosUoW, actor: UsuarioActual, usuario_id: int, rol: Rol) -> AsignacionRol:
    """``DELETE /usuarios/{id}/roles/{rol}`` (D4, D5): escribe ``revocada_en``; nunca borra la fila.

    Precedencia de errores (D9, SU-C06-10), todos dentro del mismo bloque:
    1. usuario inexistente -> ``UsuarioNoEncontradoError`` (404);
    2. solo con ``rol == ADMIN``: auto-revocacion -> ``AutoRevocacionAdminError`` (409), y luego
       la guarda de ultimo administrador -> ``UltimoAdminError`` (409), que BLOQUEA las filas
       ADMIN vigentes (``FOR UPDATE``) para ser correcta ante dos revocaciones simultaneas;
    3. sin asignacion abierta -> ``AsignacionNoEncontradaError`` (404);
    4. si todo pasa: ``revocada_en`` + UN evento.
    Una asignacion abierta pero vencida tambien se revoca (queda cerrada por un admin).
    """
    async with uow:
        usuario = await uow.usuarios.get_by_id(usuario_id)
        if usuario is None:
            raise UsuarioNoEncontradoError
        momento = ahora()
        if rol == Rol.ADMIN:
            if usuario_id == actor.id:
                raise AutoRevocacionAdminError
            admins = await uow.asignaciones.bloquear_admins_vigentes(momento)
            if not (set(admins) - {usuario_id}):
                raise UltimoAdminError
        abierta = await uow.asignaciones.abierta(usuario_id, rol)
        if abierta is None:
            raise AsignacionNoEncontradaError
        await uow.asignaciones.update(abierta, {"revocada_en": momento})
        await uow.eventos.add(
            EventoSeguridad(actor=actor.email, accion=accion_revocacion(usuario.email, rol))
        )
    return abierta


async def listar_eventos(
    uow: UsuariosUoW, params: ParametrosPaginacion
) -> tuple[Sequence[EventoSeguridad], int]:
    """Historial de seguridad (D7): ``count`` + validacion de pagina + lista en un mismo bloque."""
    async with uow:
        total = await uow.eventos.count()
        verificar_pagina(params, total)
        items = await uow.eventos.listar_recientes(offset=params.offset, limit=params.size)
    return items, total


def _conflicto_desde(exc: IntegrityError) -> ConflictoError:
    clase = _CONFLICTOS_POR_RESTRICCION.get(restriccion_violada(exc) or "", ConflictoError)
    return clase()


class CredencialesInvalidasError(Exception):
    """Correo inexistente, clave incorrecta o usuario inactivo: siempre el mismo 401."""


class DemasiadosIntentosError(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__("Demasiados intentos fallidos")
        self.retry_after = retry_after


@dataclass(frozen=True, slots=True)
class ResultadoLogin:
    usuario_id: int
    roles: tuple[str, ...]
    debe_cambiar_password: bool


@dataclass(frozen=True, slots=True)
class _Cuenta:
    """Lo minimo que el login necesita del usuario (copia plana: nada del ORM cruza el bcrypt)."""

    id: int
    password_hash: str
    activo: bool
    debe_cambiar_password: bool
    roles: tuple[str, ...]


async def iniciar_sesion(
    uow: UsuariosUoW,
    registrar_intento: RegistroIntentos,
    contrasenas: ServicioContrasenas,
    hash_ficticio: str,
    email: str,
    password: str,
    ip: str,
) -> ResultadoLogin:
    """Login (D7): limite -> verificacion unica -> anotacion -> resultado.

    ``email`` llega normalizado por el esquema. Siempre hay EXACTAMENTE una verificacion bcrypt
    (contra el hash ficticio si el correo no existe) para que el tiempo no revele cuentas
    (RN-09); con el limite alcanzado no hay ninguna (RN-08).
    """
    momento = ahora()
    # 1. Lectura en su propio bloque: al salir la conexion vuelve al pool ANTES del bcrypt.
    async with uow:
        fallos = await uow.intentos.fallos_bloqueantes(email, ip, desde=momento - VENTANA, limite=MAX_FALLOS)
        cuenta: _Cuenta | None = None
        if len(fallos) < MAX_FALLOS:
            usuario = await uow.usuarios.get_by_email(email)
            if usuario is not None:
                roles = await uow.asignaciones.roles_vigentes(usuario.id, momento)
                cuenta = _Cuenta(
                    id=usuario.id,
                    password_hash=usuario.password_hash,
                    activo=usuario.activo,
                    debe_cambiar_password=usuario.debe_cambiar_password,
                    roles=tuple(rol.value for rol in roles),
                )
    if len(fallos) >= MAX_FALLOS:
        # El 5.o fallo mas reciente (el mas viejo de los 5) sale de la ventana en este instante.
        espera = (fallos[-1] + VENTANA - momento).total_seconds()
        raise DemasiadosIntentosError(max(1, math.ceil(espera)))

    # 2. Verificacion (fuera de toda transaccion) contra el hash real o el ficticio.
    verificado = await contrasenas.verificar(password, cuenta.password_hash if cuenta else hash_ficticio)
    exito = verificado and cuenta is not None and cuenta.activo

    # 3. Anotacion en transaccion propia (la fila queda aunque la peticion termine en 401).
    await registrar_intento(email, ip, exito, ahora())
    if not exito:
        raise CredencialesInvalidasError
    return ResultadoLogin(
        usuario_id=cuenta.id, roles=cuenta.roles, debe_cambiar_password=cuenta.debe_cambiar_password
    )


class PasswordActualIncorrectaError(Exception):
    """La contraseña actual no coincide (401, SU-C05-1)."""


async def cambiar_password(
    uow: UsuariosUoW,
    contrasenas: ServicioContrasenas,
    usuario_actual: UsuarioActual,
    actual: str,
    nueva: str,
) -> None:
    """Cambio de contrasena en tres fases (D9); el token nuevo lo emite el router DESPUES.

    Lectura -> bcrypt (verificar + hashear) SIN transaccion abierta -> escritura en un unico
    bloque. Dos bloques del mismo UoW son la consecuencia directa de no retener la conexion
    durante dos bcrypt (DD-06); la escritura de RN-07 sigue siendo atomica.
    """
    async with uow:
        usuario = await uow.usuarios.get_by_id(usuario_actual.id)
        hash_vigente = usuario.password_hash if usuario is not None else None
    if hash_vigente is None or not await contrasenas.verificar(actual, hash_vigente):
        raise PasswordActualIncorrectaError
    nuevo_hash = await contrasenas.hashear(nueva)

    async with uow:
        usuario = await uow.usuarios.get_by_id(usuario_actual.id)
        if usuario is None:
            raise PasswordActualIncorrectaError
        await uow.usuarios.update(
            usuario,
            {
                "password_hash": nuevo_hash,
                "password_cambiada_en": ahora(),
                "debe_cambiar_password": False,
            },
        )
        await uow.eventos.add(EventoSeguridad(actor=usuario.email, accion=ACCION_CAMBIO_PASSWORD))
