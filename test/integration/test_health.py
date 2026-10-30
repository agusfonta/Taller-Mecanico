"""Salud contra PostgreSQL real: ready 200 sin tablas y recuperacion sin reiniciar."""
import importlib
import socket

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.database import crear_motor


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def main_real(settings_db):
    """``main`` recargado con el entorno real (``settings_db`` salta o falla sin base)."""
    get_settings.cache_clear()
    import main

    yield importlib.reload(main)
    get_settings.cache_clear()


def test_ready_200_con_base_real_sin_depender_de_tablas(main_real):
    with TestClient(main_real.app) as cliente:
        ready = cliente.get("/health/ready")
        live = cliente.get("/health/live")
    assert ready.status_code == 200
    assert ready.json() == {"estado": "listo"}
    assert live.status_code == 200
    assert live.json() == {"estado": "vivo"}


async def test_ready_recupera_sin_reiniciar_la_app(main_real, settings_db):
    from app.modules.health import router as router_mod

    motor_roto = crear_motor(
        settings_db.model_copy(update={"postgres_port": _puerto_libre()})
    )
    try:
        with TestClient(main_real.app) as cliente:
            main_real.app.dependency_overrides[router_mod.get_motor] = lambda: motor_roto
            caido = cliente.get("/health/ready")
            main_real.app.dependency_overrides.clear()
            recuperado = cliente.get("/health/ready")
    finally:
        await motor_roto.dispose()
    assert caido.status_code == 503
    assert caido.json() == {"estado": "no_listo"}
    assert recuperado.status_code == 200
    assert recuperado.json() == {"estado": "listo"}
