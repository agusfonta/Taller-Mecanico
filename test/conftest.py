"""Fixtures compartidos: aislan los tests del entorno real del desarrollador."""
import secrets

import pytest


def pytest_addoption(parser):
    # Vive aqui (y no en test/integration/) para que pytest lo registre al arrancar.
    parser.addoption(
        "--exigir-db",
        action="store_true",
        default=False,
        help="Los tests de integracion FALLAN (en vez de saltarse) si PostgreSQL no responde.",
    )


VARIABLES_ENTORNO = [
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "SQL_ECHO",
    "JWT_SECRET_KEY",
    "JWT_EXPIRE_MINUTES",
    "BCRYPT_ROUNDS",
    "BCRYPT_MAX_CONCURRENCY",
    "DB_POOL_SIZE",
    "DB_MAX_OVERFLOW",
    "COOKIE_SECURE",
]


def _limpiar_cache_settings():
    try:
        from app.core.config import get_settings
    except ImportError:  # el modulo aun no existe (ciclo RED)
        return
    get_settings.cache_clear()


@pytest.fixture
def entorno_limpio(monkeypatch):
    """Borra del entorno las 13 variables reconocidas y la cache de get_settings."""
    for variable in VARIABLES_ENTORNO:
        monkeypatch.delenv(variable, raising=False)
    _limpiar_cache_settings()
    yield monkeypatch
    _limpiar_cache_settings()


@pytest.fixture
def secretos_validos(entorno_limpio):
    """Fija los dos secretos obligatorios con valores validos generados en el test."""
    clave = secrets.token_urlsafe(48)
    password = "pw-" + secrets.token_hex(8)
    entorno_limpio.setenv("JWT_SECRET_KEY", clave)
    entorno_limpio.setenv("POSTGRES_PASSWORD", password)
    return {"JWT_SECRET_KEY": clave, "POSTGRES_PASSWORD": password}
