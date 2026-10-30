"""Errores del nucleo del seed traducidos a excepciones propias (C-11, 5.2).

Corren sobre esquemas efimeros: el esquema vacio (sin Alembic) para "base sin migrar".
"""
import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

import seed
from app.core.database import crear_fabrica_sesiones
from app.core.security import crear_servicio_contrasenas
from test.integration.conftest import _motor_en, borrar_esquema, crear_esquema
from test.integration.seed.ayudantes import snapshot

pytestmark = pytest.mark.integration


async def _tablas_del_esquema(motor) -> int:
    async with motor.connect() as c:
        return (
            await c.execute(
                text("SELECT count(*) FROM information_schema.tables WHERE table_schema = current_schema()")
            )
        ).scalar_one()


@pytest.fixture
async def esquema_vacio(settings_db):
    nombre = await crear_esquema(settings_db, "c11_vacio")
    motor = _motor_en(settings_db, nombre)
    try:
        yield motor
    finally:
        await motor.dispose()
        await borrar_esquema(settings_db, nombre)


async def test_base_sin_migrar_levanta_el_error_propio_y_no_crea_tablas(esquema_vacio, settings_auth):
    fabrica = crear_fabrica_sesiones(esquema_vacio)
    with pytest.raises(seed.BaseSinMigrarError) as exc:
        await seed.cargar_datos_iniciales(fabrica, crear_servicio_contrasenas(settings_auth))
    assert "alembic upgrade head" in str(exc.value)
    assert await _tablas_del_esquema(esquema_vacio) == 0


async def test_base_sin_migrar_es_repetible(esquema_vacio, settings_auth):
    fabrica = crear_fabrica_sesiones(esquema_vacio)
    contrasenas = crear_servicio_contrasenas(settings_auth)
    for _ in range(2):  # la primera falla no deja una transaccion abierta que rompa la segunda
        with pytest.raises(seed.BaseSinMigrarError):
            await seed.cargar_datos_iniciales(fabrica, contrasenas)


async def test_un_bloqueo_que_no_se_libera_da_timeout_propio_y_no_cambia_nada(
    seed_cargado, motor_auth, fabrica_seed, contrasenas_seed, monkeypatch, db_auth
):
    antes = await snapshot(db_auth)
    monkeypatch.setattr(seed, "LOCK_TIMEOUT", "300ms")
    async with motor_auth.connect() as retenedor:
        await retenedor.execute(text("LOCK TABLE usuario IN ACCESS SHARE MODE"))  # bloquea el TRUNCATE
        with pytest.raises(seed.BloqueoTimeoutError) as exc:
            await seed.cargar_datos_iniciales(fabrica_seed, contrasenas_seed)
        assert "reintentar" in str(exc.value)
        await retenedor.rollback()
    assert await snapshot(db_auth) == antes


async def test_base_inalcanzable_levanta_el_error_propio(settings_auth):
    muerto = settings_auth.model_copy(update={"postgres_port": 1})
    motor = create_async_engine(muerto.database_url, poolclass=NullPool)
    try:
        with pytest.raises(seed.BaseInalcanzableError):
            await asyncio.wait_for(
                seed.cargar_datos_iniciales(crear_fabrica_sesiones(motor), crear_servicio_contrasenas(muerto)),
                timeout=30,
            )
    finally:
        await motor.dispose()
