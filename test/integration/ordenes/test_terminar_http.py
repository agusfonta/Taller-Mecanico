"""POST /ordenes/{id}/terminar por HTTP contra PostgreSQL real (C-10, tarea 8.3, casos C-11 y C-12)."""
import pytest

from test.integration.ordenes.ayudantes import (
    _movimiento_inicial,
    conteos_ciclo,
    escenario_c11,
    fila_de_orden,
    historial_de_orden,
    movimientos_de_orden,
    sembrar_historial,
    sembrar_orden_completa,
    sembrar_repuesto,
    stock_de,
)

pytestmark = pytest.mark.integration

PROHIBIDOS = ("violates", "constraint", "fk_", "uq_", "ck_", "asyncpg", "sqlalchemy", "UPDATE", "INSERT")


@pytest.fixture
def cab(cookie_de, mundo_ciclo):
    roles = {"mecanico": "MECANICO", "mecanico2": "MECANICO", "admin": "ADMIN", "recepcion": "RECEPCION"}
    return {k: cookie_de(mundo_ciclo[k], (r,)) for k, r in roles.items()}


# --- 200 y caso C-12 ---------------------------------------------------------------------------------------


async def test_terminar_responde_200_con_el_detalle_y_descuenta_el_stock(http, db_auth, mundo_ciclo, cab):
    m = mundo_ciclo
    rid = await sembrar_repuesto(db_auth, codigo="R1", precio="10.50", stock=5)
    await _movimiento_inicial(db_auth, rid, m["admin"], 5)
    oid = await sembrar_orden_completa(
        db_auth, m["vehiculo"], "EN_REPARACION", mecanico_id=m["mecanico"], items=((rid, 2, "10.50"),)
    )
    await sembrar_historial(db_auth, oid, None, "PENDIENTE", m["recepcion"])
    r = await http.post(f"/ordenes/{oid}/terminar", headers=cab["mecanico"])
    assert r.status_code == 200, r.text
    datos = r.json()
    assert datos["estado"] == "TERMINADA" and datos["mecanico_id"] == m["mecanico"]
    assert [h["hasta_estado"] for h in datos["historial"]] == ["PENDIENTE", "TERMINADA"]
    assert await stock_de(db_auth, rid) == 3
    movs = await movimientos_de_orden(db_auth, oid)
    assert [(x["cantidad"], x["motivo"], x["usuario_id"]) for x in movs] == [(-2, "Terminación de orden", m["mecanico"])]


async def test_un_admin_tambien_termina_y_no_cambia_el_mecanico(http, db_auth, mundo_ciclo, cab):
    m = mundo_ciclo
    oid = await sembrar_orden_completa(db_auth, m["vehiculo"], "EN_REPARACION", mecanico_id=m["mecanico"])
    r = await http.post(f"/ordenes/{oid}/terminar", headers=cab["admin"])
    assert r.status_code == 200 and r.json()["mecanico_id"] == m["mecanico"]
    assert (await historial_de_orden(db_auth, oid))[0]["usuario_id"] == m["admin"]


async def test_c11_y_c12_409_sin_rastro_luego_reponer_y_terminar(http, db_auth, cab, cookie_de):
    e = await escenario_c11(db_auth)
    mec, adm = cookie_de(e["mecanico"], ("MECANICO",)), cookie_de(e["admin"], ("ADMIN",))
    antes, fila = await conteos_ciclo(db_auth), await fila_de_orden(db_auth, e["orden"])
    movs_bujia = (await http.get(f"/repuestos/{e['bujia']}/movimientos", headers=adm)).json()

    r = await http.post(f"/ordenes/{e['orden']}/terminar", headers=mec)  # caso C-11
    assert r.status_code == 409
    assert r.json() == {"detail": "Stock insuficiente para el repuesto BUJ-001"}
    assert not any(p in r.text for p in PROHIBIDOS)
    assert await conteos_ciclo(db_auth) == antes and await fila_de_orden(db_auth, e["orden"]) == fila
    assert (await http.get(f"/repuestos/{e['bujia']}/movimientos", headers=adm)).json() == movs_bujia
    assert (await http.get(f"/repuestos/{e['filtro']}", headers=adm)).json()["stock"] == 10
    assert (await http.get(f"/ordenes/{e['orden']}", headers=adm)).json()["estado"] == "EN_REPARACION"

    rep = await http.post(f"/repuestos/{e['bujia']}/reponer", json={"cantidad": 2}, headers=adm)
    assert rep.status_code == 200
    r = await http.post(f"/ordenes/{e['orden']}/terminar", headers=mec)  # caso C-12
    assert r.status_code == 200 and r.json()["estado"] == "TERMINADA"
    assert await stock_de(db_auth, e["bujia"]) == 0 and await stock_de(db_auth, e["filtro"]) == 9
    movs = (await http.get(f"/repuestos/{e['bujia']}/movimientos", headers=adm)).json()["items"]
    assert [(x["cantidad"], x["orden_id"]) for x in movs] == [(2, None), (2, None), (-4, e["orden"])]
    assert len(await historial_de_orden(db_auth, e["orden"])) == 3


# --- 401 / 403 / 404 / 422 -------------------------------------------------------------------------------------


async def test_sin_cookie_es_401(http, db_auth, mundo_ciclo):
    oid = await sembrar_orden_completa(db_auth, mundo_ciclo["vehiculo"], "EN_REPARACION")
    assert (await http.post(f"/ordenes/{oid}/terminar")).status_code == 401


async def test_cambio_de_contrasena_pendiente_es_403(http, db_auth, mundo_ciclo, usuario_con_rol):
    oid = await sembrar_orden_completa(db_auth, mundo_ciclo["vehiculo"], "EN_REPARACION")
    _, cab_pend = await usuario_con_rol("MECANICO", "pend@example.com", debe_cambiar_password=True)
    assert (await http.post(f"/ordenes/{oid}/terminar", headers=cab_pend)).status_code == 403
    _, cab_pend_adm = await usuario_con_rol("ADMIN", "pendadm@example.com", debe_cambiar_password=True)
    assert (await http.post(f"/ordenes/{oid}/terminar", headers=cab_pend_adm)).status_code == 403


async def test_cliente_y_recepcion_reciben_403_antes_de_404_y_de_422(http, db_auth, mundo_ciclo, cab, usuario_con_rol):
    m = mundo_ciclo
    oid = await sembrar_orden_completa(db_auth, m["vehiculo"], "EN_REPARACION", mecanico_id=m["mecanico"])
    _, cab_cliente = await usuario_con_rol("CLIENTE", "cli@example.com")
    antes = await conteos_ciclo(db_auth)
    for quien in (cab["recepcion"], cab_cliente):
        for destino in (oid, 999999, "abc"):
            assert (await http.post(f"/ordenes/{destino}/terminar", headers=quien)).status_code == 403
    assert await conteos_ciclo(db_auth) == antes


@pytest.mark.parametrize("estado", ["PENDIENTE", "EN_REPARACION", "TERMINADA"])
async def test_mecanico_no_asignado_recibe_403_incluso_sobre_terminada(http, db_auth, mundo_ciclo, cab, estado):
    m = mundo_ciclo
    oid = await sembrar_orden_completa(db_auth, m["vehiculo"], estado, mecanico_id=m["mecanico"])
    antes, fila = await conteos_ciclo(db_auth), await fila_de_orden(db_auth, oid)
    r = await http.post(f"/ordenes/{oid}/terminar", headers=cab["mecanico2"])
    assert r.status_code == 403 and r.json() == {"detail": "No tiene permiso para operar esta orden"}
    assert await conteos_ciclo(db_auth) == antes and await fila_de_orden(db_auth, oid) == fila


async def test_inexistente_es_404_y_id_no_entero_es_422(http, mundo_ciclo, cab):
    r = await http.post("/ordenes/999999/terminar", headers=cab["mecanico"])
    assert r.status_code == 404 and r.json() == {"detail": "Orden no encontrada"}
    assert (await http.post("/ordenes/999999/terminar", headers=cab["admin"])).status_code == 404
    assert (await http.post("/ordenes/abc/terminar", headers=cab["mecanico"])).status_code == 422


# --- 409 estado -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("estado", ["PENDIENTE", "TERMINADA", "CANCELADA"])
@pytest.mark.parametrize("quien", ["mecanico", "admin"])
async def test_terminar_desde_otro_estado_es_409_sin_filas(http, db_auth, mundo_ciclo, cab, estado, quien):
    m = mundo_ciclo
    oid = await sembrar_orden_completa(db_auth, m["vehiculo"], estado, mecanico_id=m["mecanico"])
    antes, fila = await conteos_ciclo(db_auth), await fila_de_orden(db_auth, oid)
    r = await http.post(f"/ordenes/{oid}/terminar", headers=cab[quien])
    assert r.status_code == 409
    assert r.json() == {"detail": f"La orden está {estado} y no admite terminar"}
    assert await conteos_ciclo(db_auth) == antes and await fila_de_orden(db_auth, oid) == fila
