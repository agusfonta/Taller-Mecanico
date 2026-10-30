"""Infraestructura de los tests del seed (C-11, D8).

El seed SOLO corre sobre ``esquema_auth`` (esquema efimero migrado con Alembic, ``search_path`` fijo):
nunca sobre ``public``. ``app_auth`` se sobrescribe aqui para montar todos los routers, como el
lifespan de ``main.py``.
"""
import secrets

import pytest

import seed
from app.core.database import crear_fabrica_sesiones
from app.core.security import crear_servicio_contrasenas


@pytest.fixture
def fabrica_seed(motor_auth):
    return crear_fabrica_sesiones(motor_auth)


@pytest.fixture
def contrasenas_seed(settings_auth):
    return crear_servicio_contrasenas(settings_auth)


@pytest.fixture
async def seed_cargado(fabrica_seed, contrasenas_seed):
    """Ejecuta el nucleo del seed sobre el esquema efimero y devuelve su resumen."""
    return await seed.cargar_datos_iniciales(fabrica_seed, contrasenas_seed)


@pytest.fixture
async def app_auth(settings_auth, motor_auth):
    """App como el lifespan, con TODOS los routers (abiertos: health y auth; el resto, protegidos)."""
    from app.core.config import get_settings
    from app.modules.clientes.router import router as router_clientes
    from app.modules.health.router import router as router_health
    from app.modules.ordenes.router import router_ordenes
    from app.modules.repuestos.router import router_repuestos
    from app.modules.usuarios.router import router_auth, router_eventos, router_usuarios
    from main import crear_app

    app = crear_app(
        abiertos=[router_health, router_auth],
        protegidos=[router_usuarios, router_eventos, router_clientes, router_repuestos, router_ordenes],
    )
    app.dependency_overrides[get_settings] = lambda: settings_auth
    app.state.engine = motor_auth
    app.state.session_factory = crear_fabrica_sesiones(motor_auth)
    app.state.contrasenas = crear_servicio_contrasenas(settings_auth)
    app.state.hash_ficticio = await app.state.contrasenas.hashear(secrets.token_urlsafe(32))
    return app


@pytest.fixture
async def sesion_de(fabrica_http):
    """``await sesion_de(email)`` -> cliente HTTP con la sesion iniciada con la contraseña del seed."""

    async def abrir(email: str):
        cliente = fabrica_http()
        respuesta = await cliente.post(
            "/auth/login", json={"email": email, "password": seed.CONTRASENAS_SEED[email]}
        )
        assert respuesta.status_code == 200, email
        return cliente

    return abrir
