"""Seguridad de la API: contraseñas (bcrypt), token de sesion (JWT) y cookie (C-05).

Contraseñas
    ``ServicioContrasenas`` es el UNICO punto que invoca ``bcrypt``. Cada calculo corre
    en ``asyncio.to_thread`` bajo un semaforo: el bucle de eventos nunca se bloquea y
    nunca corren a la vez mas calculos que ``BCRYPT_MAX_CONCURRENCY``. El semaforo es
    POR INSTANCIA (se crea en el lifespan o en ``seed.py``): uno global de modulo se
    crearia al importar, fuera del bucle, y entre tests con bucles distintos quedaria
    ligado al bucle equivocado.

    Los tipos ``PasswordNueva`` / ``PasswordIngresada`` miden la contraseña en BYTES
    UTF-8 (<= 72): bcrypt trunca o rechaza lo que excede ese tope (``ValueError`` => un
    500) y no admite el caracter nulo. Se validan en el contrato para devolver 422.

Token
    JWT HS256 con ``sub`` (texto: PyJWT >= 2.10 lo exige), ``iat`` FLOTANTE (con
    ``datetime`` PyJWT lo truncaria a entero y el cambio de contraseña del mismo segundo
    no invalidaria la sesion vieja), ``exp`` y ``roles`` (solo informativos: DD-01).

Cookie
    ``access_token`` HttpOnly, SameSite=Lax, Path=/; ``Secure`` segun ``COOKIE_SECURE``.
    Borrarla exige repetir EXACTAMENTE los mismos atributos o el navegador no la reemplaza.
"""
import asyncio
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated

import bcrypt
import jwt
from pydantic import AfterValidator, Field
from starlette.responses import Response

from app.core.config import Settings

__all__ = [
    "COOKIE_SESION",
    "ClaimsToken",
    "PasswordIngresada",
    "PasswordNueva",
    "ServicioContrasenas",
    "TokenInvalidoError",
    "borrar_cookie_sesion",
    "crear_servicio_contrasenas",
    "decodificar_token",
    "emitir_token",
    "poner_cookie_sesion",
]

logger = logging.getLogger(__name__)

COOKIE_SESION = "access_token"
MAX_BYTES_PASSWORD = 72
ALGORITMO_JWT = "HS256"


def _max_72_bytes_sin_nulo(valor: str) -> str:
    if "\x00" in valor:
        raise ValueError("La contraseña no puede contener el carácter nulo")
    if len(valor.encode("utf-8")) > MAX_BYTES_PASSWORD:
        raise ValueError(f"La contraseña no puede superar {MAX_BYTES_PASSWORD} bytes en UTF-8")
    return valor


PasswordIngresada = Annotated[str, Field(min_length=1), AfterValidator(_max_72_bytes_sin_nulo)]
"""Login y contraseña actual: no vacia, sin minimo de 8 (no se revela la politica)."""

PasswordNueva = Annotated[str, Field(min_length=8), AfterValidator(_max_72_bytes_sin_nulo)]
"""Registro y contraseña nueva: minimo 8 caracteres."""


class ServicioContrasenas:
    """Hash y verificacion bcrypt fuera del bucle y bajo un tope de concurrencia."""

    def __init__(self, rondas: int, max_concurrencia: int) -> None:
        self.rondas = rondas
        self.max_concurrencia = max_concurrencia
        self._semaforo = asyncio.Semaphore(max_concurrencia)

    async def hashear(self, password: str) -> str:
        async with self._semaforo:
            return await asyncio.to_thread(self._hashear_bloqueante, password)

    async def verificar(self, password: str, hash_: str) -> bool:
        """``False`` si no coincide o si el hash esta corrupto (un dato roto no es un 500)."""
        async with self._semaforo:
            try:
                return await asyncio.to_thread(self._verificar_bloqueante, password, hash_)
            except ValueError as exc:
                logger.warning("Hash de contraseña ilegible: %s", type(exc).__name__)
                return False

    def _hashear_bloqueante(self, password: str) -> str:
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=self.rondas)).decode("ascii")

    @staticmethod
    def _verificar_bloqueante(password: str, hash_: str) -> bool:
        return bcrypt.checkpw(password.encode("utf-8"), hash_.encode("utf-8"))


def crear_servicio_contrasenas(settings: Settings) -> ServicioContrasenas:
    return ServicioContrasenas(settings.bcrypt_rounds, settings.bcrypt_max_concurrency)


# --- Token de sesion -----------------------------------------------------------------


class TokenInvalidoError(Exception):
    """Token ausente de sentido: firma, algoritmo, vencimiento o claims invalidos."""


@dataclass(frozen=True, slots=True)
class ClaimsToken:
    sub: int
    iat: float
    exp: float
    roles: tuple[str, ...]


def emitir_token(
    usuario_id: int,
    roles: Sequence[str],
    settings: Settings,
    *,
    ahora: float | None = None,
) -> str:
    """Firma un JWT HS256. ``iat`` es flotante (sin truncar); ``roles`` solo informan."""
    iat = time.time() if ahora is None else ahora
    claims = {
        "sub": str(usuario_id),
        "iat": iat,
        "exp": iat + settings.jwt_expire_seconds,
        "roles": sorted(str(rol) for rol in roles),
    }
    return jwt.encode(claims, settings.jwt_secret_key.get_secret_value(), algorithm=ALGORITMO_JWT)


def decodificar_token(token: str, settings: Settings) -> ClaimsToken:
    """Valida firma, algoritmo fijo (rechaza ``none``), vencimiento y claims obligatorios."""
    try:
        datos = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[ALGORITMO_JWT],
            options={"require": ["sub", "iat", "exp"]},
            leeway=0,
        )
        roles = datos.get("roles", [])
        if not isinstance(roles, list) or not all(isinstance(rol, str) for rol in roles):
            raise TokenInvalidoError("roles invalidos")
        return ClaimsToken(
            sub=int(datos["sub"]),
            iat=float(datos["iat"]),
            exp=float(datos["exp"]),
            roles=tuple(roles),
        )
    except (jwt.PyJWTError, ValueError, TypeError) as exc:
        raise TokenInvalidoError(type(exc).__name__) from None


# --- Cookie de sesion ----------------------------------------------------------------


def poner_cookie_sesion(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        COOKIE_SESION,
        token,
        max_age=settings.jwt_expire_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def borrar_cookie_sesion(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        COOKIE_SESION,
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )
