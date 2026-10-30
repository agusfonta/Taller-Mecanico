"""Humo de la infraestructura de migraciones en tests (C-03, D8/D9).

Verifica los helpers de ``conftest.py`` (``aplicar_migraciones``, ``revertir_migraciones``,
``crear_esquema``/``borrar_esquema``) y las fixtures ``esquema_migrado`` / ``conexion_migrada``.
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from test.integration.conftest import (
    aplicar_migraciones,
    borrar_esquema,
    crear_esquema,
    revertir_migraciones,
)


async def _tablas(settings, esquema):
    motor = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with motor.connect() as conexion:
            filas = await conexion.execute(
                text("SELECT table_name FROM information_schema.tables WHERE table_schema = :e"),
                {"e": esquema},
            )
            return {f[0] for f in filas}
    finally:
        await motor.dispose()


async def _existe_esquema(settings, esquema):
    motor = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with motor.connect() as conexion:
            filas = await conexion.execute(
                text("SELECT 1 FROM information_schema.schemata WHERE schema_name = :e"),
                {"e": esquema},
            )
            return filas.first() is not None
    finally:
        await motor.dispose()


async def test_aplicar_head_deja_alembic_version_y_el_esquema_se_borra(settings_db):
    esquema = await crear_esquema(settings_db)
    try:
        await aplicar_migraciones(settings_db, esquema, "head")
        assert "alembic_version" in await _tablas(settings_db, esquema)
    finally:
        await borrar_esquema(settings_db, esquema)
    assert not await _existe_esquema(settings_db, esquema)


async def test_aplicar_y_revertir_no_tocan_otros_esquemas(settings_db):
    a = await crear_esquema(settings_db)
    b = await crear_esquema(settings_db)
    try:
        await aplicar_migraciones(settings_db, a, "head")
        await revertir_migraciones(settings_db, a, "base")
        assert await _tablas(settings_db, b) == set()
    finally:
        await borrar_esquema(settings_db, a)
        await borrar_esquema(settings_db, b)


async def test_conexion_migrada_revierte_lo_que_escribe(conexion_migrada, esquema_migrado, settings_db):
    await conexion_migrada.execute(text("SELECT 1"))
    assert esquema_migrado.startswith("c03_mig_")
    assert await _existe_esquema(settings_db, esquema_migrado)
