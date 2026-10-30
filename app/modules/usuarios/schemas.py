"""Contratos de /auth (C-05, D10): entradas con ``extra="forbid"``, separados de los modelos de tabla.

Ningun esquema de respuesta tiene ``password_hash`` ni contrasena.

C-06: "sin zona" y "pasado" en ``vence_en`` son incumplimientos del CONTRATO (KB 03: 422, no
409), por eso se validan aqui y no en el servicio. El correo se normaliza
(sin espacios en los extremos, en minusculas) en la entrada, igual en registro y login, porque
``uq_usuario_email`` es exacto: ``Ana@x.com`` y ``ana@x.com`` serian cuentas distintas.
"""
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    StringConstraints,
)

from app.core.security import PasswordIngresada, PasswordNueva
from app.modules.usuarios.models import Rol

__all__ = [
    "AltaPersonalEntrada",
    "AsignacionRespuesta",
    "AsignarRolEntrada",
    "CambioPasswordEntrada",
    "EmailNormalizado",
    "EventoRespuesta",
    "LoginEntrada",
    "LoginRespuesta",
    "MensajeRespuesta",
    "RegistroEntrada",
    "RegistroRespuesta",
    "RolPersonal",
    "RolesUsuarioRespuesta",
    "UsuarioCreadoRespuesta",
    "YoRespuesta",
]


def _recortar(valor: object) -> object:
    return valor.strip() if isinstance(valor, str) else valor


EmailNormalizado = Annotated[
    EmailStr,
    BeforeValidator(_recortar),
    AfterValidator(lambda correo: correo.lower()),
]

TextoNoVacio = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class _Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegistroEntrada(_Entrada):
    email: EmailNormalizado
    password: PasswordNueva
    nombre: TextoNoVacio
    documento: TextoNoVacio
    telefono: TextoNoVacio


class RegistroRespuesta(BaseModel):
    id: int
    email: str
    nombre: str
    cliente_id: int
    roles: list[str]


class LoginEntrada(_Entrada):
    email: EmailNormalizado
    password: PasswordIngresada


class LoginRespuesta(BaseModel):
    """El token NUNCA va en el cuerpo: solo en la cookie HttpOnly."""

    mensaje: str
    debe_cambiar_password: bool
    expira_en_segundos: int


class MensajeRespuesta(BaseModel):
    mensaje: str


class YoRespuesta(BaseModel):
    """Roles de la BASE en esta peticion y roles que dice el token (informativos, DD-19)."""

    id: int
    email: str
    nombre: str
    debe_cambiar_password: bool
    roles_vigentes: list[str]
    roles_token: list[str]


class CambioPasswordEntrada(_Entrada):
    password_actual: PasswordIngresada
    password_nueva: PasswordNueva


# --- C-06: alta de personal, roles y eventos (D2, D3, D8) ----------------------------------

RolPersonal = Literal[Rol.ADMIN, Rol.RECEPCION, Rol.MECANICO]
"""Rol inicial del alta de personal: ``CLIENTE`` -> 422 (los clientes se auto-registran)."""


class AltaPersonalEntrada(_Entrada):
    email: EmailNormalizado
    nombre: TextoNoVacio
    password: PasswordNueva
    rol: RolPersonal


class UsuarioCreadoRespuesta(BaseModel):
    id: int
    email: str
    nombre: str
    debe_cambiar_password: bool
    roles: list[str]


def _futuro(valor: datetime) -> datetime:
    """``AwareDatetime`` ya rechaza la fecha sin zona; aqui se exige que sea posterior a ahora."""
    if valor <= datetime.now(UTC):
        raise ValueError("El vencimiento debe ser una fecha futura")
    return valor


class AsignarRolEntrada(_Entrada):
    rol: Rol
    vence_en: Annotated[AwareDatetime, AfterValidator(_futuro)] | None = None


class AsignacionRespuesta(BaseModel):
    id: int
    usuario_id: int
    rol: str
    desde: datetime
    vence_en: datetime | None
    revocada_en: datetime | None
    otorgada_por: int | None
    vigente: bool


class RolesUsuarioRespuesta(BaseModel):
    usuario_id: int
    email: str
    roles_vigentes: list[str]
    asignaciones: list[AsignacionRespuesta]


class EventoRespuesta(BaseModel):
    id: int
    cuando: datetime
    actor: str
    accion: str
