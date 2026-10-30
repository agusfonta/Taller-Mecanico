"""Dependencias comunes de las rutas: usuario actual, control del grupo protegido y roles (C-05).

Orden de resolucion (D5/D6) y por que importa:

1. ``leer_claims``: lee SOLO la cookie ``access_token`` (jamas ``Authorization``) y valida el
   token. Sin cookie o con token invalido responde 401 AQUI, antes de pedir la sesion de base
   de datos: una peticion anonima no toca la base (ni necesita ``app.state.session_factory``).
   ``claims`` se declara ANTES que ``uow`` en ``get_usuario_actual``: FastAPI resuelve los
   parametros en orden y corta con la primera excepcion. Un test falla si alguien los reordena.
2. ``get_usuario_actual``: una lectura (usuario + roles vigentes) dentro de ``async with uow``.
   Al salir se confirma una transaccion de solo lectura y la conexion vuelve al pool: no queda
   una transaccion abierta mientras despues corre bcrypt o el handler. Devuelve un
   ``UsuarioActual`` inmutable, nunca la entidad ORM (sin carga perezosa ni ``password_hash``).
3. ``exigir_acceso``: control del grupo protegido (DD-07), montado UNA vez en ``crear_app``:
   403 si hay cambio de contrasena pendiente (RN-06).
4. ``requiere_rol``: 403 si ningun rol vigente en la BASE coincide (los del token son solo
   informativos, DD-01). Depende de ``exigir_acceso`` para que el 403 por cambio pendiente se
   evalue antes que el de rol aunque se use fuera del grupo protegido.

FastAPI cachea cada dependencia por peticion: el usuario se resuelve una sola vez aunque
intervengan el grupo y la ruta. Este modulo reemplaza el gancho de C-02, que fallaba cerrado.
"""
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from app.core.config import Settings, get_settings
from app.core.security import (
    COOKIE_SESION,
    ClaimsToken,
    ServicioContrasenas,
    TokenInvalidoError,
    decodificar_token,
)
from app.modules.usuarios.models import Rol
from app.modules.usuarios.unit_of_work import UsuariosUoWDep

__all__ = [
    "ClaimsDep",
    "ContrasenasDep",
    "HashFicticioDep",
    "MENSAJE_CAMBIO_PENDIENTE",
    "MENSAJE_SIN_PERMISO",
    "MENSAJE_SIN_SESION",
    "SettingsDep",
    "UsuarioActual",
    "UsuarioActualDep",
    "exigir_acceso",
    "get_contrasenas",
    "get_hash_ficticio",
    "get_usuario_actual",
    "leer_claims",
    "requiere_rol",
]

MENSAJE_SIN_SESION = "Se requiere iniciar sesión"
MENSAJE_CAMBIO_PENDIENTE = "Debe cambiar la contraseña antes de continuar"
MENSAJE_SIN_PERMISO = "No tiene permiso para esta operación"

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_contrasenas(request: Request) -> ServicioContrasenas:
    """Servicio bcrypt publicado por el lifespan en ``app.state`` (semaforo por proceso)."""
    return request.app.state.contrasenas


def get_hash_ficticio(request: Request) -> str:
    """Hash ficticio calculado una vez en el arranque (RN-09)."""
    return request.app.state.hash_ficticio


ContrasenasDep = Annotated[ServicioContrasenas, Depends(get_contrasenas)]
HashFicticioDep = Annotated[str, Depends(get_hash_ficticio)]


@dataclass(frozen=True, slots=True)
class UsuarioActual:
    id: int
    email: str
    nombre: str
    debe_cambiar_password: bool
    roles_vigentes: frozenset[Rol]
    roles_token: tuple[str, ...]


def _sin_sesion() -> HTTPException:
    # Mismo mensaje en todos los casos: no revela si fallo el token, el usuario o el cambio.
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=MENSAJE_SIN_SESION)


async def leer_claims(request: Request, settings: SettingsDep) -> ClaimsToken:
    token = request.cookies.get(COOKIE_SESION)
    if not token:
        raise _sin_sesion()
    try:
        return decodificar_token(token, settings)
    except TokenInvalidoError:
        raise _sin_sesion() from None


ClaimsDep = Annotated[ClaimsToken, Depends(leer_claims)]


async def get_usuario_actual(claims: ClaimsDep, uow: UsuariosUoWDep) -> UsuarioActual:
    """Resuelve el usuario de la cookie; 401 si no existe, esta inactivo o la sesion es vieja."""
    ahora = datetime.now(UTC)
    async with uow:
        usuario = await uow.usuarios.get_by_id(claims.sub)
        if usuario is None or not usuario.activo:
            raise _sin_sesion()
        # Microsegundos de PostgreSQL, SIN truncar a segundos (DD-08): un cambio de
        # contrasena en el mismo segundo del login igual invalida la sesion anterior.
        cambio = usuario.password_cambiada_en
        if cambio is not None and datetime.fromtimestamp(claims.iat, UTC) < cambio:
            raise _sin_sesion()
        roles = await uow.asignaciones.roles_vigentes(usuario.id, ahora)
        return UsuarioActual(
            id=usuario.id,
            email=usuario.email,
            nombre=usuario.nombre,
            debe_cambiar_password=usuario.debe_cambiar_password,
            roles_vigentes=frozenset(roles),
            roles_token=claims.roles,
        )


UsuarioActualDep = Annotated[UsuarioActual, Depends(get_usuario_actual)]


async def exigir_acceso(usuario: UsuarioActualDep) -> UsuarioActual:
    """Control del grupo protegido: usuario valido y sin cambio de contrasena pendiente."""
    if usuario.debe_cambiar_password:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=MENSAJE_CAMBIO_PENDIENTE)
    return usuario


def requiere_rol(*roles: Rol):
    """Dependencia que exige AL MENOS UNO de ``roles`` vigente en la base (403 si no).

    Valida al declararse (un typo falla al importar, no en produccion).
    """
    if not roles:
        raise ValueError("requiere_rol necesita al menos un rol")
    if not all(isinstance(rol, Rol) for rol in roles):
        raise TypeError("requiere_rol solo acepta miembros de Rol")
    permitidos = frozenset(roles)

    async def dependencia(usuario: Annotated[UsuarioActual, Depends(exigir_acceso)]) -> UsuarioActual:
        if not (usuario.roles_vigentes & permitidos):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=MENSAJE_SIN_PERMISO)
        return usuario

    return dependencia
