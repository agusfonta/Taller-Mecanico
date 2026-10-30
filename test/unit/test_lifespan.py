"""Lifespan: publica motor/fabrica en app.state y libera el pool al apagar (D2)."""
import importlib

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.unit


@pytest.fixture
def main_mod(secretos_validos, monkeypatch):
    monkeypatch.setenv("POSTGRES_HOST", "host-que-no-existe.invalid")
    monkeypatch.setenv("BCRYPT_ROUNDS", "4")
    import main

    return importlib.reload(main)


@pytest.fixture
def dispose_espiado(monkeypatch):
    """Cuenta los dispose de AsyncEngine (el atributo de instancia es de solo lectura)."""
    estado = {"dispose": 0}
    real = AsyncEngine.dispose

    async def dispose(self, *args, **kwargs):
        estado["dispose"] += 1
        return await real(self, *args, **kwargs)

    monkeypatch.setattr(AsyncEngine, "dispose", dispose)
    return estado


async def test_lifespan_publica_motor_y_fabrica_y_libera_una_vez(main_mod, dispose_espiado):
    app = FastAPI()
    assert not hasattr(app.state, "engine")
    assert not hasattr(app.state, "session_factory")
    async with main_mod.lifespan(app):
        assert isinstance(app.state.engine, AsyncEngine)
        assert app.state.session_factory.kw["bind"] is app.state.engine
        assert dispose_espiado["dispose"] == 0
    assert dispose_espiado["dispose"] == 1


async def test_lifespan_con_excepcion_igual_libera_una_vez(main_mod, dispose_espiado):
    app = FastAPI()
    with pytest.raises(RuntimeError):
        async with main_mod.lifespan(app):
            raise RuntimeError("falla de la app")
    assert dispose_espiado["dispose"] == 1


def test_importar_main_no_publica_recursos_en_app_state(main_mod):
    assert not hasattr(main_mod.app.state, "engine")
    assert not hasattr(main_mod.app.state, "session_factory")


async def test_lifespan_publica_servicio_de_contrasenas_y_hash_ficticio(main_mod):
    from app.core.security import ServicioContrasenas

    app = FastAPI()
    assert not hasattr(app.state, "contrasenas")
    async with main_mod.lifespan(app):
        assert isinstance(app.state.contrasenas, ServicioContrasenas)
        assert app.state.contrasenas.rondas == 4
        assert app.state.hash_ficticio.startswith("$2b$04$")


async def test_dos_arranques_producen_hashes_ficticios_distintos(main_mod):
    hashes = []
    for _ in range(2):
        app = FastAPI()
        async with main_mod.lifespan(app):
            hashes.append(app.state.hash_ficticio)
    assert hashes[0] != hashes[1]


async def test_hash_ficticio_toma_el_costo_configurado(main_mod, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("BCRYPT_ROUNDS", "5")
    get_settings.cache_clear()
    app = FastAPI()
    async with main_mod.lifespan(app):
        assert app.state.hash_ficticio.startswith("$2b$05$")


async def test_hash_ficticio_no_verifica_con_cadenas_obvias(main_mod):
    app = FastAPI()
    async with main_mod.lifespan(app):
        for candidata in ("", "password", "ficticio"):
            assert await app.state.contrasenas.verificar(candidata, app.state.hash_ficticio) is False


def test_importar_main_no_calcula_hash_ficticio(main_mod):
    assert not hasattr(main_mod.app.state, "hash_ficticio")
    assert not hasattr(main_mod.app.state, "contrasenas")
