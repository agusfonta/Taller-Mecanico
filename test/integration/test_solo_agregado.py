"""Disparador de solo agregado (C-03, spec ``solo-agregado``, RN-15) sobre el esquema migrado."""
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from test.integration.conftest import aplicar_migraciones
from test.integration.filas import (
    acepta,
    cliente,
    estado,
    historial_estado,
    historial_precio,
    movimiento,
    orden,
    repuesto,
    usuario,
    vehiculo,
)

pytestmark = pytest.mark.integration

# SQL fijo por tabla (nunca se arma por concatenacion con datos de entrada).
UPDATES = {
    "historial_estado_orden": "UPDATE historial_estado_orden SET hasta_estado = 'OTRO' WHERE id = :i",
    "movimiento_stock": "UPDATE movimiento_stock SET cantidad = cantidad + 1 WHERE id = :i",
    "historial_precio_repuesto": (
        "UPDATE historial_precio_repuesto SET precio_nuevo = precio_nuevo + 1 WHERE id = :i"
    ),
}
DELETES = {
    "historial_estado_orden": "DELETE FROM historial_estado_orden WHERE id = :i",
    "movimiento_stock": "DELETE FROM movimiento_stock WHERE id = :i",
    "historial_precio_repuesto": "DELETE FROM historial_precio_repuesto WHERE id = :i",
}
CONTADORES = {
    "historial_estado_orden": "SELECT count(*) FROM historial_estado_orden",
    "movimiento_stock": "SELECT count(*) FROM movimiento_stock",
    "historial_precio_repuesto": "SELECT count(*) FROM historial_precio_repuesto",
}
VALOR = {
    "historial_estado_orden": "SELECT hasta_estado FROM historial_estado_orden WHERE id = :i",
    "movimiento_stock": "SELECT cantidad FROM movimiento_stock WHERE id = :i",
    "historial_precio_repuesto": "SELECT precio_nuevo FROM historial_precio_repuesto WHERE id = :i",
}
TABLAS = sorted(UPDATES)


async def _crear_fila(c, tabla):
    """Inserta una fila valida (con sus padres) en la tabla de solo agregado."""
    uid = await usuario(c, tabla + "@example.com")  # valores unicos por tabla
    if tabla == "movimiento_stock":
        return await movimiento(c, await repuesto(c, "M-1"), uid, cantidad=5)
    if tabla == "historial_precio_repuesto":
        return await historial_precio(c, await repuesto(c, "H-1"), uid, Decimal("8000.00"), Decimal("8500.00"))
    await estado(c, "PENDIENTE", 1)
    await estado(c, "OTRO", 2)
    oid = await orden(c, await vehiculo(c, await cliente(c)))
    return await historial_estado(c, oid, uid, hasta="PENDIENTE")


async def _rechazada_por_disparador(c, sql, fila_id, tabla, operacion):
    with pytest.raises(DBAPIError) as exc:
        async with c.begin_nested():
            await c.execute(text(sql), {"i": fila_id})
    mensaje = str(exc.value.orig)
    assert tabla in mensaje and operacion in mensaje
    assert not isinstance(exc.value, IntegrityError)  # no se disfraza de 409 (D7)
    assert exc.value.orig.sqlstate == "P0001"


# --- 9.1 las tres tablas, las dos operaciones -------------------------------------


@pytest.mark.parametrize("tabla", TABLAS)
async def test_update_es_rechazado_y_la_fila_queda_igual(conexion_migrada, tabla):
    c = conexion_migrada
    fila = await _crear_fila(c, tabla)
    antes = (await c.execute(text(VALOR[tabla]), {"i": fila})).scalar_one()

    await _rechazada_por_disparador(c, UPDATES[tabla], fila, tabla, "UPDATE")

    assert (await c.execute(text(VALOR[tabla]), {"i": fila})).scalar_one() == antes


@pytest.mark.parametrize("tabla", TABLAS)
async def test_delete_es_rechazado_y_la_fila_sigue(conexion_migrada, tabla):
    c = conexion_migrada
    fila = await _crear_fila(c, tabla)

    await _rechazada_por_disparador(c, DELETES[tabla], fila, tabla, "DELETE")

    assert (await c.execute(text(CONTADORES[tabla]))).scalar_one() == 1


# --- 9.3 el agregado sigue permitido; DELETE masivo; TRUNCATE ---------------------


async def test_insert_aceptado_en_las_tres_tablas(conexion_migrada):
    c = conexion_migrada
    for tabla in TABLAS:
        assert await acepta(c, _crear_fila(c, tabla))
        assert (await c.execute(text(CONTADORES[tabla]))).scalar_one() == 1


async def test_otras_tablas_no_se_ven_afectadas(conexion_migrada):
    c = conexion_migrada
    rid = await repuesto(c, stock=5)
    await c.execute(text("UPDATE repuesto SET stock = 9 WHERE id = :i"), {"i": rid})
    assert (await c.execute(text("SELECT stock FROM repuesto WHERE id = :i"), {"i": rid})).scalar_one() == 9
    await c.execute(text("DELETE FROM repuesto WHERE id = :i"), {"i": rid})
    assert (await c.execute(text("SELECT count(*) FROM repuesto"))).scalar_one() == 0


async def test_delete_masivo_sin_condicion_sigue_rechazado(conexion_migrada):
    c = conexion_migrada
    uid = await usuario(c)
    rid = await repuesto(c)
    await movimiento(c, rid, uid, 1)
    await movimiento(c, rid, uid, 2)
    with pytest.raises(DBAPIError) as exc:
        async with c.begin_nested():
            await c.execute(text("DELETE FROM movimiento_stock"))
    assert "movimiento_stock" in str(exc.value.orig) and "DELETE" in str(exc.value.orig)
    assert (await c.execute(text("SELECT count(*) FROM movimiento_stock"))).scalar_one() == 2


async def test_delete_sin_filas_no_falla(conexion_migrada):
    c = conexion_migrada
    # Disparador por fila: sin filas afectadas no hay nada que proteger (D7).
    await c.execute(text("DELETE FROM movimiento_stock WHERE id = -1"))
    await c.execute(text("UPDATE historial_precio_repuesto SET precio_nuevo = 1 WHERE id = -1"))


async def test_truncate_cascade_esta_permitido_para_el_seed(settings_db, esquema_prueba):
    await aplicar_migraciones(settings_db, esquema_prueba, "head")
    motor = create_async_engine(
        settings_db.database_url,
        poolclass=NullPool,
        connect_args={"server_settings": {"search_path": esquema_prueba}},
    )
    try:
        async with motor.begin() as c:
            uid = await usuario(c)
            rid = await repuesto(c)
            await movimiento(c, rid, uid, 3)
            await c.execute(text("TRUNCATE movimiento_stock, historial_precio_repuesto, historial_estado_orden CASCADE"))
            assert (await c.execute(text("SELECT count(*) FROM movimiento_stock"))).scalar_one() == 0
            # TRUNCATE ... RESTART IDENTITY CASCADE es el vaciado que usara seed.py (C-11).
            await movimiento(c, rid, uid, 4)
            await c.execute(text("TRUNCATE usuario, repuesto, movimiento_stock RESTART IDENTITY CASCADE"))
            assert (await c.execute(text("SELECT count(*) FROM usuario"))).scalar_one() == 0
    finally:
        await motor.dispose()
