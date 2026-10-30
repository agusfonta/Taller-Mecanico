"""Casos C-11 y C-12 de la KB 11 sobre el seed real, por HTTP con login real (C-11 del roadmap, 4.4)."""
import pytest

from test.integration.seed.ayudantes import snapshot

pytestmark = pytest.mark.integration

TABLAS_DE_LA_ORDEN = ("orden_trabajo", "item_orden", "repuesto", "movimiento_stock", "historial_estado_orden")


async def test_terminar_la_orden_2_sin_stock_da_409_con_la_bujia_y_no_cambia_nada_c11(
    seed_cargado, sesion_de, db_auth
):
    mecanico = await sesion_de("mecanico@example.com")
    antes = await snapshot(db_auth)

    respuesta = await mecanico.post("/ordenes/2/terminar")

    assert respuesta.status_code == 409
    assert "BUJ-001" in respuesta.json()["detail"]
    despues = await snapshot(db_auth)
    for tabla in TABLAS_DE_LA_ORDEN:
        assert despues[tabla] == antes[tabla], tabla
    assert despues == antes


async def test_el_rollback_deshace_tambien_el_descuento_del_filtro_ya_aplicado_c11(
    seed_cargado, sesion_de, db_auth
):
    mecanico = await sesion_de("mecanico@example.com")
    await mecanico.post("/ordenes/2/terminar")
    stocks = await db_auth.filas("SELECT codigo, stock FROM repuesto ORDER BY id")
    assert [(s["codigo"], s["stock"]) for s in stocks] == [
        ("FIL-001", 10),
        ("FRE-010", 4),
        ("BUJ-001", 2),
        ("ACE-530", 20),
    ]
    assert await db_auth.filas("SELECT 1 FROM movimiento_stock WHERE orden_id IS NOT NULL") == []


async def test_reponer_bujias_y_terminar_la_orden_2_da_200_con_descuentos_c12(seed_cargado, sesion_de, db_auth):
    admin = await sesion_de("admin@example.com")
    mecanico = await sesion_de("mecanico@example.com")

    reposicion = await admin.post("/repuestos/3/reponer", json={"cantidad": 2})
    assert reposicion.status_code == 200
    terminada = await mecanico.post("/ordenes/2/terminar")

    assert terminada.status_code == 200
    assert terminada.json()["estado"] == "TERMINADA"
    stocks = {s["codigo"]: s["stock"] for s in await db_auth.filas("SELECT codigo, stock FROM repuesto")}
    assert stocks["FIL-001"] == 9
    assert stocks["BUJ-001"] == 0
    movimientos = await db_auth.filas(
        "SELECT repuesto_id, cantidad FROM movimiento_stock WHERE orden_id = 2 ORDER BY repuesto_id"
    )
    assert movimientos == [{"repuesto_id": 1, "cantidad": -1}, {"repuesto_id": 3, "cantidad": -4}]
    historial = await db_auth.filas(
        "SELECT desde_estado, hasta_estado FROM historial_estado_orden WHERE orden_id = 2 ORDER BY id DESC LIMIT 1"
    )
    assert historial == [{"desde_estado": "EN_REPARACION", "hasta_estado": "TERMINADA"}]


async def test_reponer_una_sola_bujia_no_alcanza_y_sigue_dando_409_c11(seed_cargado, sesion_de):
    admin = await sesion_de("admin@example.com")
    mecanico = await sesion_de("mecanico@example.com")
    await admin.post("/repuestos/3/reponer", json={"cantidad": 1})
    respuesta = await mecanico.post("/ordenes/2/terminar")
    assert respuesta.status_code == 409
    assert "BUJ-001" in respuesta.json()["detail"]
