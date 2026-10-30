"""Humo de los ayudantes del ciclo de vida: el escenario C-11 coincide con la KB 04 (C-10, 4.1)."""
import pytest

from test.integration.ordenes.ayudantes import (
    conteos_ciclo,
    escenario_c11,
    historial_de_orden,
    items_de_orden,
    movimientos_de_orden,
    stock_de,
)

pytestmark = pytest.mark.integration


async def test_escenario_c11_deja_la_orden_en_reparacion_con_cuatro_bujias_y_stock_dos(db_auth):
    e = await escenario_c11(db_auth)
    fila = (await db_auth.filas("SELECT estado, mecanico_id FROM orden_trabajo WHERE id = :i", i=e["orden"]))[0]
    assert fila == {"estado": "EN_REPARACION", "mecanico_id": e["mecanico"]}
    assert [(i["repuesto_id"], i["cantidad"]) for i in await items_de_orden(db_auth, e["orden"])] == [
        (e["filtro"], 1),
        (e["bujia"], 4),
    ]
    assert await stock_de(db_auth, e["bujia"]) == 2
    assert await stock_de(db_auth, e["filtro"]) == 10
    assert e["filtro"] < e["bujia"], "el filtro se procesa antes que la bujia"


async def test_escenario_c11_trae_historial_previo_y_stock_inicial_como_movimientos(db_auth):
    e = await escenario_c11(db_auth)
    assert [(h["desde_estado"], h["hasta_estado"]) for h in await historial_de_orden(db_auth, e["orden"])] == [
        (None, "PENDIENTE"),
        ("PENDIENTE", "EN_REPARACION"),
    ]
    assert await movimientos_de_orden(db_auth, e["orden"]) == []
    for clave, stock in (("bujia", 2), ("filtro", 10)):
        movs = await db_auth.filas(
            "SELECT cantidad, motivo FROM movimiento_stock WHERE repuesto_id = :i", i=e[clave]
        )
        assert movs == [{"cantidad": stock, "motivo": "Stock inicial"}]


async def test_conteos_ciclo_cuenta_tablas_y_stocks_y_cambia_con_los_datos(db_auth):
    e = await escenario_c11(db_auth)
    antes = await conteos_ciclo(db_auth)
    assert antes["orden_trabajo"] == 1 and antes["historial_estado_orden"] == 2
    assert antes["movimiento_stock"] == 2
    assert antes["stocks"] == {e["filtro"]: 10, e["bujia"]: 2}
    await db_auth.ejecutar("UPDATE repuesto SET stock = stock + 1 WHERE id = :i", i=e["bujia"])
    despues = await conteos_ciclo(db_auth)
    assert despues != antes and despues["stocks"][e["bujia"]] == 3
