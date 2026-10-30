"""GET /ordenes por HTTP contra PostgreSQL real (C-09, tarea 6.3, spec consulta-ordenes)."""
import pytest

from test.integration.ordenes.ayudantes import (
    sembrar_catalogo,
    sembrar_cliente,
    sembrar_orden_completa,
    sembrar_vehiculo,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def mundo(db_auth, usuario_con_rol):
    await sembrar_catalogo(db_auth)
    v = await sembrar_vehiculo(db_auth, await sembrar_cliente(db_auth, "1"), "AAA111")
    m1, cab_m1 = await usuario_con_rol("MECANICO", "mecanico@example.com")
    m2, cab_m2 = await usuario_con_rol("MECANICO", "mecanico2@example.com")
    return {
        "m1": cab_m1,
        "m2": cab_m2,
        "sin": await sembrar_orden_completa(db_auth, v, "PENDIENTE"),
        "de_m1": await sembrar_orden_completa(db_auth, v, "EN_REPARACION", mecanico_id=m1),
        "de_m2": await sembrar_orden_completa(db_auth, v, "TERMINADA", mecanico_id=m2),
    }


def ids(respuesta):
    return [o["id"] for o in respuesta.json()["items"]]


@pytest.mark.parametrize("rol", ["RECEPCION", "ADMIN"])
async def test_recepcion_y_admin_ven_todas(http, usuario_con_rol, mundo, rol):
    _, cab = await usuario_con_rol(rol)
    r = await http.get("/ordenes", headers=cab)
    assert r.status_code == 200
    assert ids(r) == [mundo["sin"], mundo["de_m1"], mundo["de_m2"]]
    cuerpo = r.json()
    assert (cuerpo["total"], cuerpo["page"], cuerpo["size"], cuerpo["pages"]) == (3, 1, 20, 1)
    assert set(cuerpo["items"][0]) == {"id", "vehiculo_id", "mecanico_id", "estado", "falla", "creada_en", "total"}
    assert cuerpo["items"][0]["total"] == "0.00"


async def test_mecanico2_no_ve_la_orden_de_mecanico_dd18(http, mundo):
    r = await http.get("/ordenes", headers=mundo["m2"])
    assert ids(r) == [mundo["sin"], mundo["de_m2"]] and r.json()["total"] == 2
    r = await http.get("/ordenes", headers=mundo["m1"])
    assert ids(r) == [mundo["sin"], mundo["de_m1"]]


async def test_filtro_por_estado_y_total_coincide(http, usuario_con_rol, mundo):
    _, cab = await usuario_con_rol("RECEPCION")
    r = await http.get("/ordenes", params={"estado": "PENDIENTE"}, headers=cab)
    assert ids(r) == [mundo["sin"]] and r.json()["total"] == 1
    r = await http.get("/ordenes", params={"estado": "CANCELADA"}, headers=cab)
    assert r.status_code == 200 and r.json()["items"] == [] and r.json()["total"] == 0


@pytest.mark.parametrize("estado", ["ARCHIVADA", "pendiente", ""])
async def test_estado_fuera_del_catalogo_es_422(http, usuario_con_rol, mundo, estado):
    _, cab = await usuario_con_rol("RECEPCION")
    assert (await http.get("/ordenes", params={"estado": estado}, headers=cab)).status_code == 422


async def test_pagina_fuera_de_rango_con_filtro_es_422(http, usuario_con_rol, mundo):
    _, cab = await usuario_con_rol("RECEPCION")
    # hay 3 ordenes en total (2 paginas de 2), pero con el filtro solo 1 (1 pagina)
    assert (await http.get("/ordenes", params={"size": 2, "page": 2}, headers=cab)).status_code == 200
    r = await http.get("/ordenes", params={"estado": "PENDIENTE", "size": 2, "page": 2}, headers=cab)
    assert r.status_code == 422
    assert (await http.get("/ordenes", params={"page": 0}, headers=cab)).status_code == 422


async def test_cliente_recibe_403_y_sin_sesion_401(http, usuario_con_rol, mundo):
    _, cab = await usuario_con_rol("CLIENTE")
    assert (await http.get("/ordenes", headers=cab)).status_code == 403
    assert (await http.get("/ordenes")).status_code == 401


async def test_usuario_con_roles_mecanico_y_admin_ve_todas_incluidas_las_de_otro_mecanico(
    http, db_auth, cookie_de, mundo
):
    uid = await db_auth.crear_usuario(
        "doble@example.com", "x" * 10, roles=("MECANICO", "ADMIN")
    )
    r = await http.get("/ordenes", headers=cookie_de(uid, ("MECANICO", "ADMIN")))
    assert r.status_code == 200
    # incluye la sin asignar, la de m1 y la de m2 (con solo MECANICO no veria la de otro)
    assert ids(r) == [mundo["sin"], mundo["de_m1"], mundo["de_m2"]]
    assert r.json()["total"] == 3
