"""POST /ordenes/{id}/iniciar por HTTP contra PostgreSQL real (C-10, tarea 8.2)."""
import pytest

from test.integration.ordenes.ayudantes import (
    conteos_ciclo,
    fila_de_orden,
    sembrar_historial,
    sembrar_orden_completa,
    sembrar_repuesto,
)

pytestmark = pytest.mark.integration

PROHIBIDOS = ("violates", "constraint", "fk_", "uq_", "asyncpg", "sqlalchemy", "UPDATE", "INSERT")


@pytest.fixture
def cab(cookie_de, mundo_ciclo):
    """Cabeceras por usuario del mundo."""
    roles = {"mecanico": "MECANICO", "mecanico2": "MECANICO", "admin": "ADMIN", "recepcion": "RECEPCION"}
    return {k: cookie_de(mundo_ciclo[k], (r,)) for k, r in roles.items()}


# --- 200 -------------------------------------------------------------------------------------------


async def test_iniciar_responde_200_con_el_detalle_y_el_historial_nuevo(http, db_auth, mundo_ciclo, cab):
    m = mundo_ciclo
    rid = await sembrar_repuesto(db_auth, codigo="R1", precio="10.50", stock=5)
    oid = await sembrar_orden_completa(db_auth, m["vehiculo"], items=((rid, 2, "10.50"),))
    await sembrar_historial(db_auth, oid, None, "PENDIENTE", m["recepcion"])
    r = await http.post(f"/ordenes/{oid}/iniciar", headers=cab["mecanico"])
    assert r.status_code == 200, r.text
    datos = r.json()
    assert datos["id"] == oid and datos["estado"] == "EN_REPARACION" and datos["mecanico_id"] == m["mecanico"]
    assert [(i["codigo"], i["cantidad"], i["subtotal"]) for i in datos["items"]] == [("R1", 2, "21.00")]
    assert [(h["desde_estado"], h["hasta_estado"], h["usuario_id"]) for h in datos["historial"]] == [
        (None, "PENDIENTE", m["recepcion"]),
        ("PENDIENTE", "EN_REPARACION", m["mecanico"]),
    ]
    fila = await fila_de_orden(db_auth, oid)
    assert fila["estado"] == "EN_REPARACION" and fila["mecanico_id"] == m["mecanico"]


async def test_tras_iniciar_el_otro_mecanico_ya_no_ve_la_orden_en_su_listado(http, db_auth, mundo_ciclo, cab):
    m = mundo_ciclo
    oid = await sembrar_orden_completa(db_auth, m["vehiculo"])
    antes = await http.get("/ordenes", headers=cab["mecanico"])
    assert [o["id"] for o in antes.json()["items"]] == [oid]
    assert (await http.post(f"/ordenes/{oid}/iniciar", headers=cab["mecanico2"])).status_code == 200
    despues = await http.get("/ordenes", headers=cab["mecanico"])
    assert despues.json()["items"] == []
    suyo = await http.get("/ordenes", headers=cab["mecanico2"])
    assert [o["id"] for o in suyo.json()["items"]] == [oid]


# --- 401 / 403 / 422 / 404 ---------------------------------------------------------------------------


async def test_sin_cookie_es_401(http, db_auth, mundo_ciclo):
    oid = await sembrar_orden_completa(db_auth, mundo_ciclo["vehiculo"])
    assert (await http.post(f"/ordenes/{oid}/iniciar")).status_code == 401


async def test_cambio_de_contrasena_pendiente_es_403(http, db_auth, mundo_ciclo, usuario_con_rol):
    oid = await sembrar_orden_completa(db_auth, mundo_ciclo["vehiculo"])
    _, cab_pend = await usuario_con_rol("MECANICO", "pend@example.com", debe_cambiar_password=True)
    assert (await http.post(f"/ordenes/{oid}/iniciar", headers=cab_pend)).status_code == 403


@pytest.mark.parametrize("quien", ["admin", "recepcion"])
async def test_solo_el_mecanico_inicia_admin_y_recepcion_reciben_403_incluso_sin_orden(
    http, db_auth, mundo_ciclo, cab, quien
):
    oid = await sembrar_orden_completa(db_auth, mundo_ciclo["vehiculo"])
    antes = await conteos_ciclo(db_auth)
    for destino in (oid, 999999):
        r = await http.post(f"/ordenes/{destino}/iniciar", headers=cab[quien])
        assert r.status_code == 403, r.text
    assert (await http.post("/ordenes/abc/iniciar", headers=cab[quien])).status_code == 403  # 403 antes que 422
    assert (await fila_de_orden(db_auth, oid))["estado"] == "PENDIENTE"
    assert await conteos_ciclo(db_auth) == antes


async def test_un_cliente_recibe_403_incluso_sobre_id_inexistente(http, db_auth, mundo_ciclo, usuario_con_rol):
    _, cab_cliente = await usuario_con_rol("CLIENTE", "cli@example.com")
    assert (await http.post("/ordenes/999999/iniciar", headers=cab_cliente)).status_code == 403


async def test_id_no_entero_es_422_y_inexistente_es_404(http, mundo_ciclo, cab):
    assert (await http.post("/ordenes/abc/iniciar", headers=cab["mecanico"])).status_code == 422
    r = await http.post("/ordenes/999999/iniciar", headers=cab["mecanico"])
    assert r.status_code == 404 and r.json() == {"detail": "Orden no encontrada"}


# --- 409 ---------------------------------------------------------------------------------------------------


async def test_iniciar_una_orden_ya_iniciada_es_409_con_mensaje_propio_y_sin_filas(
    http, db_auth, mundo_ciclo, cab
):
    m = mundo_ciclo
    oid = await sembrar_orden_completa(db_auth, m["vehiculo"], "EN_REPARACION", mecanico_id=m["mecanico"])
    antes, fila = await conteos_ciclo(db_auth), await fila_de_orden(db_auth, oid)
    r = await http.post(f"/ordenes/{oid}/iniciar", headers=cab["mecanico2"])
    assert r.status_code == 409
    assert r.json() == {"detail": "La orden está EN_REPARACION y no admite iniciar"}
    assert not any(p in r.text for p in PROHIBIDOS)
    assert await conteos_ciclo(db_auth) == antes and await fila_de_orden(db_auth, oid) == fila


@pytest.mark.parametrize("estado", ["TERMINADA", "CANCELADA"])
async def test_iniciar_una_orden_finalizada_es_409(http, db_auth, mundo_ciclo, cab, estado):
    oid = await sembrar_orden_completa(db_auth, mundo_ciclo["vehiculo"], estado)
    r = await http.post(f"/ordenes/{oid}/iniciar", headers=cab["mecanico"])
    assert r.status_code == 409 and estado in r.json()["detail"]


async def test_iniciar_una_pendiente_preasignada_a_otro_es_409_con_su_propio_mensaje(
    http, db_auth, mundo_ciclo, cab
):
    m = mundo_ciclo
    oid = await sembrar_orden_completa(db_auth, m["vehiculo"], "PENDIENTE", mecanico_id=m["mecanico2"])
    antes, fila = await conteos_ciclo(db_auth), await fila_de_orden(db_auth, oid)
    r = await http.post(f"/ordenes/{oid}/iniciar", headers=cab["mecanico"])
    assert r.status_code == 409 and r.json() == {"detail": "La orden ya está asignada a otro mecánico"}
    assert not any(p in r.text for p in PROHIBIDOS)
    assert await conteos_ciclo(db_auth) == antes and await fila_de_orden(db_auth, oid) == fila


async def test_un_cuerpo_enviado_se_ignora(http, db_auth, mundo_ciclo, cab):
    m = mundo_ciclo
    oid = await sembrar_orden_completa(db_auth, m["vehiculo"])
    r = await http.post(f"/ordenes/{oid}/iniciar", json={"mecanico_id": m["mecanico2"]}, headers=cab["mecanico"])
    assert r.status_code == 200 and r.json()["mecanico_id"] == m["mecanico"]
