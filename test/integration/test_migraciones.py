"""Migraciones reales contra PostgreSQL (C-03, spec ``migraciones``).

Cada test usa su PROPIO esquema efimero (los tests modifican el esquema); el
esquema compartido ``esquema_migrado`` queda para los tests de restricciones.
"""
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from test.integration.conftest import (
    aplicar_migraciones,
    borrar_esquema,
    crear_esquema,
    revertir_migraciones,
)

TABLAS = {
    "usuario", "asignacion_rol", "intento_acceso", "evento_seguridad", "cliente", "vehiculo",
    "repuesto", "movimiento_stock", "historial_precio_repuesto", "estado_orden", "orden_trabajo",
    "item_orden", "historial_estado_orden",
}


@pytest.fixture
async def esquema_limpio(settings_db):
    nombre = await crear_esquema(settings_db, "c03_ciclo")
    try:
        yield nombre
    finally:
        await borrar_esquema(settings_db, nombre)


async def _consultar(settings, esquema, sql, **params):
    motor = create_async_engine(
        settings.database_url,
        poolclass=NullPool,
        connect_args={"server_settings": {"search_path": esquema}},
    )
    try:
        async with motor.connect() as conexion:
            return (await conexion.execute(text(sql), params)).all()
    finally:
        await motor.dispose()


async def _tablas(settings, esquema):
    filas = await _consultar(
        settings, esquema,
        "SELECT table_name FROM information_schema.tables WHERE table_schema = :e", e=esquema,
    )
    return {f[0] for f in filas}


async def test_upgrade_head_crea_las_13_tablas(settings_db, esquema_limpio):
    await aplicar_migraciones(settings_db, esquema_limpio, "head")

    assert await _tablas(settings_db, esquema_limpio) == TABLAS | {"alembic_version"}
    for tabla in sorted(TABLAS):
        filas = await _consultar(settings_db, esquema_limpio, f'SELECT count(*) FROM "{tabla}"')
        assert filas[0][0] == 0, tabla


async def test_revertir_deja_solo_alembic_version_vacia_sin_tablas_de_la_app(settings_db, esquema_limpio):
    await aplicar_migraciones(settings_db, esquema_limpio, "head")
    await revertir_migraciones(settings_db, esquema_limpio, "base")

    assert not (await _tablas(settings_db, esquema_limpio) & TABLAS)


# --- 7.3 sincronia --------------------------------------------------------


async def _diferencias(settings, esquema):
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext

    from app.modules.modelos import metadata

    motor = create_async_engine(
        settings.database_url,
        poolclass=NullPool,
        connect_args={"server_settings": {"search_path": esquema}},
    )

    def _comparar(conexion):
        contexto = MigrationContext.configure(
            conexion, opts={"compare_type": True, "compare_server_default": True}
        )
        return compare_metadata(contexto, metadata)

    try:
        async with motor.connect() as conexion:
            return await conexion.run_sync(_comparar)
    finally:
        await motor.dispose()


async def test_modelos_y_migraciones_sin_diferencias(settings_db, esquema_limpio):
    await aplicar_migraciones(settings_db, esquema_limpio, "head")
    assert await _diferencias(settings_db, esquema_limpio) == []


async def test_la_comparacion_detecta_diferencias_si_falta_migrar(settings_db, esquema_limpio):
    diferencias = await _diferencias(settings_db, esquema_limpio)
    assert sum(1 for d in diferencias if d[0] == "add_table") == 13


# --- 7.4 reversibilidad ---------------------------------------------------


async def _foto(settings, esquema):
    """Tablas, indices, restricciones, funciones y disparadores del esquema (para comparar)."""
    consultas = {
        "tablas": "SELECT table_name FROM information_schema.tables WHERE table_schema = :e ORDER BY 1",
        "indices": "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = :e ORDER BY 1",
        "restricciones": (
            "SELECT c.conname, c.contype::text, pg_get_constraintdef(c.oid) FROM pg_constraint c "
            "JOIN pg_namespace n ON n.oid = c.connamespace WHERE n.nspname = :e ORDER BY 1"
        ),
        "funciones": (
            "SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = :e ORDER BY 1"
        ),
        "disparadores": (
            "SELECT t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = :e AND NOT t.tgisinternal ORDER BY 1"
        ),
    }
    return {
        nombre: [tuple(f) for f in await _consultar(settings, esquema, sql, e=esquema)]
        for nombre, sql in consultas.items()
    }


async def test_downgrade_base_no_deja_nada(settings_db, esquema_limpio):
    await aplicar_migraciones(settings_db, esquema_limpio, "head")
    await revertir_migraciones(settings_db, esquema_limpio, "base")

    foto = await _foto(settings_db, esquema_limpio)
    assert foto["tablas"] == [("alembic_version",)]
    assert foto["indices"] == [("alembic_version_pkc", foto["indices"][0][1])]
    assert [r for r in foto["restricciones"] if not r[0].startswith("alembic_version")] == []
    assert foto["funciones"] == [] and foto["disparadores"] == []
    filas = await _consultar(settings_db, esquema_limpio, "SELECT count(*) FROM alembic_version")
    assert filas[0][0] == 0


async def test_ida_vuelta_ida(settings_db, esquema_limpio):
    await aplicar_migraciones(settings_db, esquema_limpio, "head")
    primera = await _foto(settings_db, esquema_limpio)
    await revertir_migraciones(settings_db, esquema_limpio, "base")
    await aplicar_migraciones(settings_db, esquema_limpio, "head")
    segunda = await _foto(settings_db, esquema_limpio)

    assert primera == segunda
    assert len(primera["tablas"]) == 14
    assert len(primera["indices"]) > 20


# --- 9.4 migraciones con la segunda ---------------------------------------------


async def test_head_instala_funcion_y_tres_disparadores(settings_db, esquema_limpio):
    await aplicar_migraciones(settings_db, esquema_limpio, "head")
    foto = await _foto(settings_db, esquema_limpio)
    assert foto["funciones"] == [("rechazar_modificacion_solo_agregado",)]
    assert foto["disparadores"] == [
        ("solo_agregado_historial_estado_orden",),
        ("solo_agregado_historial_precio_repuesto",),
        ("solo_agregado_movimiento_stock",),
    ]


async def test_revertir_solo_la_segunda(settings_db, esquema_limpio):
    await aplicar_migraciones(settings_db, esquema_limpio, "head")
    await revertir_migraciones(settings_db, esquema_limpio, "-1")

    assert TABLAS <= await _tablas(settings_db, esquema_limpio)
    foto = await _foto(settings_db, esquema_limpio)
    assert foto["funciones"] == [] and foto["disparadores"] == []
    version = await _consultar(settings_db, esquema_limpio, "SELECT version_num FROM alembic_version")
    assert version == [("acf6d613aa1c",)]
    # La proteccion ya no esta: modificar una fila de historial es aceptado.
    from test.integration.filas import movimiento, repuesto, usuario

    motor = create_async_engine(
        settings_db.database_url,
        poolclass=NullPool,
        connect_args={"server_settings": {"search_path": esquema_limpio}},
    )
    try:
        async with motor.begin() as c:
            fila = await movimiento(c, await repuesto(c), await usuario(c), cantidad=5)
            await c.execute(text("UPDATE movimiento_stock SET cantidad = 9 WHERE id = :i"), {"i": fila})
            cantidad = (await c.execute(text("SELECT cantidad FROM movimiento_stock WHERE id = :i"), {"i": fila})).scalar_one()
        assert cantidad == 9
    finally:
        await motor.dispose()


def test_historial_tiene_dos_migraciones_identificables():
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    raiz = Path(__file__).resolve().parents[2]
    scripts = ScriptDirectory.from_config(Config(str(raiz / "alembic.ini")))
    revisiones = list(scripts.walk_revisions(base="base", head="heads"))[::-1]  # de la primera a la ultima
    assert len(revisiones) == 2
    primera, segunda = revisiones
    assert primera.down_revision is None
    assert segunda.down_revision == primera.revision
    doc1 = Path(primera.path).read_text(encoding="utf-8").lower()
    doc2 = Path(segunda.path).read_text(encoding="utf-8").lower()
    assert "autogenerate" in doc1 and "revisada" in doc1
    assert "escrita a mano" in doc2
    for modulo in (scripts.get_revision(primera.revision).module, scripts.get_revision(segunda.revision).module):
        assert callable(modulo.upgrade) and callable(modulo.downgrade)
