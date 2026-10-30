"""Ciclo completo por HTTP contra PostgreSQL real (C-10, tarea 9.2, spec transiciones-orden)."""
import pytest

from test.integration.ordenes.ayudantes import (
    _movimiento_inicial,
    historial_de_orden,
    movimientos_de_orden,
    sembrar_repuesto,
    stock_de,
)

pytestmark = pytest.mark.integration


async def test_ciclo_completo_crear_iniciar_terminar_deja_el_historial_y_descuenta_el_stock(
    http, db_auth, mundo_ciclo, cookie_de
):
    m = mundo_ciclo
    rid = await sembrar_repuesto(db_auth, codigo="R1", precio="10.50", stock=5)
    await _movimiento_inicial(db_auth, rid, m["admin"], 5)
    recepcion, mecanico = cookie_de(m["recepcion"], ("RECEPCION",)), cookie_de(m["mecanico"], ("MECANICO",))

    alta = await http.post(
        "/ordenes",
        json={"vehiculo_id": m["vehiculo"], "falla": "No arranca", "items": [{"repuesto_id": rid, "cantidad": 2}]},
        headers=recepcion,
    )
    assert alta.status_code == 201, alta.text
    oid = alta.json()["id"]
    iniciada = await http.post(f"/ordenes/{oid}/iniciar", headers=mecanico)
    assert iniciada.status_code == 200, iniciada.text
    terminada = await http.post(f"/ordenes/{oid}/terminar", headers=mecanico)
    assert terminada.status_code == 200, terminada.text

    assert terminada.json()["estado"] == "TERMINADA"
    historial = await historial_de_orden(db_auth, oid)
    assert [(h["desde_estado"], h["hasta_estado"], h["usuario_id"]) for h in historial] == [
        (None, "PENDIENTE", m["recepcion"]),
        ("PENDIENTE", "EN_REPARACION", m["mecanico"]),
        ("EN_REPARACION", "TERMINADA", m["mecanico"]),
    ]
    assert await stock_de(db_auth, rid) == 3
    movs = await movimientos_de_orden(db_auth, oid)
    assert [(x["repuesto_id"], x["cantidad"], x["usuario_id"]) for x in movs] == [(rid, -2, m["mecanico"])]
