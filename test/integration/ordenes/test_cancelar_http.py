"""POST /ordenes/{id}/cancelar por HTTP contra PostgreSQL real (C-10, tarea 8.5, caso C-13) y 8.6."""
import pytest

from test.integration.ordenes.ayudantes import (
    conteos_ciclo,
    fila_de_orden,
    historial_de_orden,
    movimientos_de_orden,
    sembrar_cliente,
    sembrar_historial,
    sembrar_orden_completa,
    sembrar_repuesto,
    sembrar_vehiculo,
    stock_de,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def cab(cookie_de, mundo_ciclo):
    roles = {"mecanico": "MECANICO", "mecanico2": "MECANICO", "admin": "ADMIN", "recepcion": "RECEPCION"}
    return {k: cookie_de(mundo_ciclo[k], (r,)) for k, r in roles.items()}


@pytest.fixture
async def duenos(db_auth, cookie_de, mundo_ciclo):
    resultado = {}
    for nombre, doc, patente in (("dueno", "30", "DDD111"), ("otro", "40", "OOO222")):
        uid = await db_auth.crear_usuario(f"{nombre}@example.com", "x" * 10, roles=("CLIENTE",))
        cid = await sembrar_cliente(db_auth, doc, usuario_id=uid)
        resultado[nombre] = {
            "uid": uid,
            "cab": cookie_de(uid, ("CLIENTE",)),
            "vehiculo": await sembrar_vehiculo(db_auth, cid, patente),
        }
    return resultado


# --- 200 (caso C-13) -------------------------------------------------------------------------------------


async def test_el_dueno_cancela_su_pendiente_con_200_y_sin_tocar_el_stock(http, db_auth, mundo_ciclo, duenos):
    rid = await sembrar_repuesto(db_auth, codigo="R1", precio="10.00", stock=5)
    d = duenos["dueno"]
    oid = await sembrar_orden_completa(db_auth, d["vehiculo"], items=((rid, 2, "10.00"),))
    await sembrar_historial(db_auth, oid, None, "PENDIENTE", mundo_ciclo["recepcion"])
    r = await http.post(f"/ordenes/{oid}/cancelar", headers=d["cab"])
    assert r.status_code == 200, r.text
    datos = r.json()
    assert datos["estado"] == "CANCELADA" and datos["mecanico_id"] is None
    assert [(h["desde_estado"], h["hasta_estado"], h["usuario_id"]) for h in datos["historial"]] == [
        (None, "PENDIENTE", mundo_ciclo["recepcion"]),
        ("PENDIENTE", "CANCELADA", d["uid"]),
    ]
    assert await movimientos_de_orden(db_auth, oid) == [] and await stock_de(db_auth, rid) == 5


@pytest.mark.parametrize("quien", ["recepcion", "admin"])
async def test_recepcion_y_admin_cancelan_la_pendiente_de_cualquiera(http, db_auth, mundo_ciclo, cab, duenos, quien):
    oid = await sembrar_orden_completa(db_auth, duenos["dueno"]["vehiculo"])
    r = await http.post(f"/ordenes/{oid}/cancelar", headers=cab[quien])
    assert r.status_code == 200 and r.json()["estado"] == "CANCELADA"
    assert (await historial_de_orden(db_auth, oid))[-1]["usuario_id"] == mundo_ciclo[quien]


# --- 403 ------------------------------------------------------------------------------------------------------


async def test_cliente_ajeno_recibe_403_y_la_orden_queda_igual(http, db_auth, duenos):
    oid = await sembrar_orden_completa(db_auth, duenos["dueno"]["vehiculo"], falla="falla secreta")
    antes, fila = await conteos_ciclo(db_auth), await fila_de_orden(db_auth, oid)
    r = await http.post(f"/ordenes/{oid}/cancelar", headers=duenos["otro"]["cab"])
    assert r.status_code == 403 and "secreta" not in r.text
    assert r.json() == {"detail": "No tiene permiso para operar esta orden"}
    assert await conteos_ciclo(db_auth) == antes and await fila_de_orden(db_auth, oid) == fila


async def test_orden_ajena_ya_terminada_es_403_y_no_409(http, db_auth, duenos):
    oid = await sembrar_orden_completa(db_auth, duenos["dueno"]["vehiculo"], "TERMINADA")
    assert (await http.post(f"/ordenes/{oid}/cancelar", headers=duenos["otro"]["cab"])).status_code == 403


async def test_mecanico_que_no_es_dueno_recibe_403_incluso_sobre_terminada(http, db_auth, cab, duenos):
    for estado in ("PENDIENTE", "TERMINADA"):
        oid = await sembrar_orden_completa(db_auth, duenos["dueno"]["vehiculo"], estado, mecanico_id=None)
        assert (await http.post(f"/ordenes/{oid}/cancelar", headers=cab["mecanico"])).status_code == 403


# --- 409 ----------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("estado", ["EN_REPARACION", "TERMINADA", "CANCELADA"])
@pytest.mark.parametrize("quien", ["recepcion", "dueno"])
async def test_cancelar_una_no_pendiente_es_409_sin_filas(http, db_auth, cab, duenos, estado, quien):
    oid = await sembrar_orden_completa(db_auth, duenos["dueno"]["vehiculo"], estado)
    headers = cab["recepcion"] if quien == "recepcion" else duenos["dueno"]["cab"]
    antes, fila = await conteos_ciclo(db_auth), await fila_de_orden(db_auth, oid)
    r = await http.post(f"/ordenes/{oid}/cancelar", headers=headers)
    assert r.status_code == 409 and r.json() == {"detail": f"La orden está {estado} y no admite cancelar"}
    assert await conteos_ciclo(db_auth) == antes and await fila_de_orden(db_auth, oid) == fila


# --- 404 / 401 / 403 de sesion / 422 ----------------------------------------------------------------------------------


async def test_inexistente_es_404_y_id_no_entero_es_422(http, cab, duenos):
    r = await http.post("/ordenes/999999/cancelar", headers=cab["recepcion"])
    assert r.status_code == 404 and r.json() == {"detail": "Orden no encontrada"}
    assert (await http.post("/ordenes/999999/cancelar", headers=duenos["dueno"]["cab"])).status_code == 404
    assert (await http.post("/ordenes/abc/cancelar", headers=cab["recepcion"])).status_code == 422


async def test_sin_cookie_es_401(http, db_auth, duenos):
    oid = await sembrar_orden_completa(db_auth, duenos["dueno"]["vehiculo"])
    assert (await http.post(f"/ordenes/{oid}/cancelar")).status_code == 401


async def test_cambio_de_contrasena_pendiente_es_403(http, db_auth, duenos, usuario_con_rol):
    oid = await sembrar_orden_completa(db_auth, duenos["dueno"]["vehiculo"])
    _, cab_pend = await usuario_con_rol("RECEPCION", "pend@example.com", debe_cambiar_password=True)
    assert (await http.post(f"/ordenes/{oid}/cancelar", headers=cab_pend)).status_code == 403
    assert (await fila_de_orden(db_auth, oid))["estado"] == "PENDIENTE"


# --- 8.6 interaccion con la baja de vehiculo (D10) ----------------------------------------------------------------------------


async def test_la_baja_del_vehiculo_espera_a_que_la_orden_pendiente_se_cancele(http, db_auth, mundo_ciclo, cab):
    m = mundo_ciclo
    oid = await sembrar_orden_completa(db_auth, m["vehiculo"])
    assert (await http.delete(f"/vehiculos/{m['vehiculo']}", headers=cab["recepcion"])).status_code == 409
    assert (await http.post(f"/ordenes/{oid}/cancelar", headers=cab["recepcion"])).status_code == 200
    assert (await http.delete(f"/vehiculos/{m['vehiculo']}", headers=cab["recepcion"])).status_code == 204


async def test_la_baja_del_vehiculo_espera_a_que_la_orden_en_reparacion_se_termine(http, db_auth, mundo_ciclo, cab):
    m = mundo_ciclo
    oid = await sembrar_orden_completa(db_auth, m["vehiculo"], "EN_REPARACION", mecanico_id=m["mecanico"])
    assert (await http.delete(f"/vehiculos/{m['vehiculo']}", headers=cab["recepcion"])).status_code == 409
    assert (await http.post(f"/ordenes/{oid}/terminar", headers=cab["mecanico"])).status_code == 200
    assert (await http.delete(f"/vehiculos/{m['vehiculo']}", headers=cab["recepcion"])).status_code == 204
