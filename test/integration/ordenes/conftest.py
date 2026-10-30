"""Infraestructura HTTP de integracion de ordenes (C-09, D13).

Sobrescribe ``app_auth`` SOLO en este subdirectorio para montar ``router_ordenes`` (y
``router_repuestos``, para el cambio de precio posterior, y ``router_clientes``, para la baja de
vehiculo, C-10) en el grupo protegido sin editar
el ``conftest.py`` compartido.
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
    from app.modules.clientes.router import router as router_clientes
    from app.modules.health.router import router as router_health
    from app.modules.ordenes.router import router_ordenes
    from app.modules.repuestos.router import router_repuestos
    from app.modules.usuarios.router import router_auth
    from main import crear_app

    app = crear_app(
        abiertos=[router_health, router_auth], protegidos=[router_ordenes, router_repuestos, router_clientes]
    )
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
def usuario_con_rol(db_auth, cookie_de):
    """``await usuario_con_rol("RECEPCION", email=None)`` -> ``(id, cabecera)``."""

    async def crear(rol: str, email: str | None = None, **kwargs):
        uid = await db_auth.crear_usuario(
            email or f"{rol.lower()}@example.com", "x" * 10, roles=(rol,), **kwargs
        )
        return uid, cookie_de(uid, (rol,))

    return crear


@pytest.fixture
def fabrica(motor_auth):
    return crear_fabrica_sesiones(motor_auth)


@pytest.fixture
async def mundo_ciclo(db_auth):
    """Catalogo, un cliente con vehiculo y usuarios de cada rol del ciclo de vida (C-10)."""
    from test.integration.ordenes.ayudantes import sembrar_catalogo, sembrar_cliente, sembrar_vehiculo

    await sembrar_catalogo(db_auth)
    cliente = await sembrar_cliente(db_auth, "10")
    return {
        "cliente": cliente,
        "vehiculo": await sembrar_vehiculo(db_auth, cliente, "AAA111"),
        "mecanico": await db_auth.crear_usuario("mec1@example.com", "x" * 10, roles=("MECANICO",)),
        "mecanico2": await db_auth.crear_usuario("mec2@example.com", "x" * 10, roles=("MECANICO",)),
        "admin": await db_auth.crear_usuario("admin-t@example.com", "x" * 10, roles=("ADMIN",)),
        "recepcion": await db_auth.crear_usuario("recep-t@example.com", "x" * 10, roles=("RECEPCION",)),
    }
