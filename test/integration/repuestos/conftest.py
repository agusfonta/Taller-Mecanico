"""Infraestructura HTTP de integracion de repuestos (C-08, D10/D11).

Sobrescribe ``app_auth`` SOLO en este subdirectorio para montar ``router_repuestos`` en el grupo
protegido sin editar el ``conftest.py`` compartido. ``fabrica_http`` y ``http`` del conftest
padre usan este override (resuelven ``app_auth`` por nombre desde el directorio del test).
"""
import secrets

import pytest

from app.core.database import crear_fabrica_sesiones
from test.integration.ayudantes_clientes import cabecera


@pytest.fixture
async def app_auth(settings_auth, motor_auth):
    """App como el lifespan (motor del esquema migrado, bcrypt de 4 rondas, hash ficticio)."""
    from app.core.config import get_settings
    from app.core.security import crear_servicio_contrasenas
    from app.modules.health.router import router as router_health
    from app.modules.repuestos.router import router_repuestos
    from app.modules.usuarios.router import router_auth
    from main import crear_app

    app = crear_app(abiertos=[router_health, router_auth], protegidos=[router_repuestos])
    app.dependency_overrides[get_settings] = lambda: settings_auth
    app.state.engine = motor_auth
    app.state.session_factory = crear_fabrica_sesiones(motor_auth)
    app.state.contrasenas = crear_servicio_contrasenas(settings_auth)
    app.state.hash_ficticio = await app.state.contrasenas.hashear(secrets.token_urlsafe(32))
    return app


@pytest.fixture
def cookie_de(settings_auth):
    """``cookie_de(uid, roles)`` -> cabecera con la cookie de sesion firmada (roles informativos)."""

    def construir(uid: int, roles=("ADMIN",)) -> dict[str, str]:
        return cabecera(uid, roles, settings_auth)

    return construir


@pytest.fixture
async def admin_id(db_auth) -> int:
    return await db_auth.crear_usuario("admin@example.com", "x" * 10, roles=("ADMIN",))


@pytest.fixture
async def admin(admin_id, cookie_de) -> dict[str, str]:
    """Cabecera de un ADMIN sembrado (su id queda en ``admin_id``)."""
    return cookie_de(admin_id, ("ADMIN",))


@pytest.fixture
def usuario_con_rol(db_auth, cookie_de):
    """``await usuario_con_rol("RECEPCION")`` -> ``(id, cabecera)``."""

    async def crear(rol: str, **kwargs):
        uid = await db_auth.crear_usuario(f"{rol.lower()}@example.com", "x" * 10, roles=(rol,), **kwargs)
        return uid, cookie_de(uid, (rol,))

    return crear
