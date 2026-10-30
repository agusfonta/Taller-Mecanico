"""database.py: fabricas puras de motor/sesiones y get_session (D1)."""
import importlib
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.config import Settings
from app.core.database import (
    crear_fabrica_sesiones,
    crear_motor,
    get_session,
)

pytestmark = pytest.mark.unit


async def test_crear_motor_valores_por_defecto(secretos_validos):
    motor = crear_motor(Settings(_env_file=None))
    try:
        assert isinstance(motor, AsyncEngine)
        assert motor.pool.size() == 5
        assert motor.pool._max_overflow == 10
        assert motor.echo is False
    finally:
        await motor.dispose()


async def test_crear_motor_valores_del_entorno(secretos_validos):
    motor = crear_motor(
        Settings(_env_file=None, db_pool_size=2, db_max_overflow=0, sql_echo=True)
    )
    try:
        assert motor.pool.size() == 2
        assert motor.pool._max_overflow == 0
        assert motor.echo is True
    finally:
        await motor.dispose()


async def test_crear_motor_lee_variables_de_entorno(secretos_validos, monkeypatch):
    monkeypatch.setenv("DB_POOL_SIZE", "2")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "0")
    monkeypatch.setenv("SQL_ECHO", "true")
    motor = crear_motor(Settings(_env_file=None))
    try:
        assert (motor.pool.size(), motor.pool._max_overflow, motor.echo) == (2, 0, True)
    finally:
        await motor.dispose()


async def test_crear_motor_con_host_inexistente_no_conecta(secretos_validos, monkeypatch):
    monkeypatch.setenv("POSTGRES_HOST", "host-que-no-existe.invalid")
    motor = crear_motor(Settings(_env_file=None))
    try:
        assert isinstance(motor, AsyncEngine)
    finally:
        await motor.dispose()


async def test_fabrica_produce_sesiones_ligadas_al_motor_sin_expirar(secretos_validos):
    motor = crear_motor(Settings(_env_file=None))
    try:
        fabrica = crear_fabrica_sesiones(motor)
        assert fabrica.kw["expire_on_commit"] is False
        assert fabrica.kw["bind"] is motor
        async with fabrica() as sesion:
            assert isinstance(sesion, AsyncSession)
            assert sesion.bind is motor
    finally:
        await motor.dispose()


class SesionFalsa:
    def __init__(self):
        self.cerrada = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.cerrada = True


def _request(fabrica):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(session_factory=fabrica)))


def _fabrica_espia():
    creadas: list[SesionFalsa] = []

    def fabrica():
        s = SesionFalsa()
        creadas.append(s)
        return s

    return fabrica, creadas


async def test_get_session_entrega_y_cierra_al_agotar():
    fabrica, creadas = _fabrica_espia()
    agen = get_session(_request(fabrica))
    sesion = await anext(agen)
    assert sesion is creadas[0]
    assert sesion.cerrada is False
    with pytest.raises(StopAsyncIteration):
        await anext(agen)
    assert sesion.cerrada is True


async def test_get_session_cierra_tambien_con_excepcion():
    fabrica, creadas = _fabrica_espia()
    agen = get_session(_request(fabrica))
    await anext(agen)
    with pytest.raises(RuntimeError):
        await agen.athrow(RuntimeError("boom"))
    assert creadas[0].cerrada is True


async def test_get_session_dos_llamadas_dan_sesiones_distintas():
    fabrica, creadas = _fabrica_espia()
    a = await anext(get_session(_request(fabrica)))
    b = await anext(get_session(_request(fabrica)))
    assert a is not b
    assert len(creadas) == 2


def test_session_dep_es_un_alias_anotado_con_depends():
    from app.core.database import SessionDep

    metadata = SessionDep.__metadata__
    assert metadata[0].dependency is get_session


def test_importar_database_no_crea_recursos(secretos_validos):
    modulo = importlib.import_module("app.core.database")
    modulo = importlib.reload(modulo)
    assert not hasattr(modulo, "engine")
    assert not hasattr(modulo, "SessionLocal")
    assert not [
        nombre
        for nombre, valor in vars(modulo).items()
        if isinstance(valor, AsyncEngine)
    ]
