"""Garantias de la base intactas tras el seed (C-11, 3.7)."""
import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError

import seed

pytestmark = pytest.mark.integration

UPDATES = {
    "historial_estado_orden": "UPDATE historial_estado_orden SET hasta_estado = 'OTRO' WHERE id = 1",
    "movimiento_stock": "UPDATE movimiento_stock SET cantidad = cantidad + 1 WHERE id = 1",
    "historial_precio_repuesto": "UPDATE historial_precio_repuesto SET precio_nuevo = precio_nuevo + 1 WHERE id = 1",
}
DELETES = {
    "historial_estado_orden": "DELETE FROM historial_estado_orden WHERE id = 1",
    "movimiento_stock": "DELETE FROM movimiento_stock WHERE id = 1",
    "historial_precio_repuesto": "DELETE FROM historial_precio_repuesto WHERE id = 1",
}


async def test_el_primer_insert_tras_el_truncate_es_en_estado_orden(motor_auth, fabrica_seed, contrasenas_seed):
    sentencias: list[str] = []

    def capturar(conn, cursor, statement, parameters, context, executemany):
        sentencias.append(statement)

    event.listen(motor_auth.sync_engine, "before_cursor_execute", capturar)
    try:
        await seed.cargar_datos_iniciales(fabrica_seed, contrasenas_seed)
    finally:
        event.remove(motor_auth.sync_engine, "before_cursor_execute", capturar)

    posicion = next(i for i, s in enumerate(sentencias) if s.lstrip().upper().startswith("TRUNCATE"))
    inserts = [s for s in sentencias[posicion + 1 :] if s.lstrip().upper().startswith("INSERT")]
    assert inserts[0].startswith("INSERT INTO estado_orden")
    # el catalogo precede a cualquier insercion de ordenes y de historial de estados
    primero = {t: next(i for i, s in enumerate(inserts) if f"INSERT INTO {t} " in s) for t in ("estado_orden", "orden_trabajo", "historial_estado_orden")}
    assert primero["estado_orden"] < primero["orden_trabajo"] < primero["historial_estado_orden"]


async def test_set_local_lock_timeout_precede_al_truncate(motor_auth, fabrica_seed, contrasenas_seed):
    sentencias: list[str] = []

    def capturar(conn, cursor, statement, parameters, context, executemany):
        sentencias.append(statement.strip().upper())

    event.listen(motor_auth.sync_engine, "before_cursor_execute", capturar)
    try:
        await seed.cargar_datos_iniciales(fabrica_seed, contrasenas_seed)
    finally:
        event.remove(motor_auth.sync_engine, "before_cursor_execute", capturar)

    lock = next(i for i, s in enumerate(sentencias) if s.startswith("SET LOCAL LOCK_TIMEOUT"))
    truncate = next(i for i, s in enumerate(sentencias) if s.startswith("TRUNCATE"))
    assert lock < truncate
    assert "RESTART IDENTITY" in sentencias[truncate] and "CASCADE" in sentencias[truncate]
    assert "ALEMBIC_VERSION" not in sentencias[truncate]


@pytest.mark.parametrize("tabla", sorted(UPDATES))
async def test_update_sigue_rechazado_por_el_disparador(seed_cargado, motor_auth, tabla):
    async with motor_auth.connect() as conexion:
        with pytest.raises(DBAPIError) as exc:
            async with conexion.begin_nested():
                await conexion.execute(text(UPDATES[tabla]))
        assert tabla in str(exc.value.orig)


@pytest.mark.parametrize("tabla", sorted(DELETES))
async def test_delete_sigue_rechazado_por_el_disparador(seed_cargado, motor_auth, tabla):
    async with motor_auth.connect() as conexion:
        with pytest.raises(DBAPIError) as exc:
            async with conexion.begin_nested():
                await conexion.execute(text(DELETES[tabla]))
        assert tabla in str(exc.value.orig)
        cuenta = (await conexion.execute(text(f"SELECT count(*) FROM {tabla}"))).scalar_one()  # tabla fija
        assert cuenta > 0
