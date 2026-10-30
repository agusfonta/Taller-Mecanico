"""GET /ordenes/{id} y /mis-ordenes por HTTP contra PostgreSQL real (C-09, tarea 6.4)."""
import pytest

from test.integration.ordenes.ayudantes import (
    sembrar_catalogo,
    sembrar_cliente,
    sembrar_orden_completa,
    sembrar_repuesto,
    sembrar_vehiculo,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def mundo(db_auth, usuario_con_rol):
    await sembrar_catalogo(db_auth)
    dueno, cab_dueno = await usuario_con_rol("CLIENTE", "dueno@example.com")
    otro, cab_otro = await usuario_con_rol("CLIENTE", "otro@example.com")
    c1 = await sembrar_cliente(db_auth, "1", usuario_id=dueno)
    c2 = await sembrar_cliente(db_auth, "2", usuario_id=otro)
    v1 = await sembrar_vehiculo(db_auth, c1, "AAA111")
    v1b = await sembrar_vehiculo(db_auth, c1, "AAA222", baja=True)
    v2 = await sembrar_vehiculo(db_auth, c2, "BBB111")
    rep = await sembrar_repuesto(db_auth, codigo="R1")
    return {
        "dueno": cab_dueno,
        "otro": cab_otro,
        "propia": await sembrar_orden_completa(db_auth, v1, "PENDIENTE", items=((rep, 2, "10.50"),)),
        "propia_baja": await sembrar_orden_completa(db_auth, v1b, "TERMINADA"),
        "ajena": await sembrar_orden_completa(db_auth, v2, "PENDIENTE", falla="falla secreta del otro"),
    }


async def test_el_dueno_ve_el_detalle_de_su_orden(http, mundo):
    r = await http.get(f"/ordenes/{mundo['propia']}", headers=mundo["dueno"])
    assert r.status_code == 200
    datos = r.json()
    assert datos["id"] == mundo["propia"] and datos["total"] == "21.00"
    assert datos["items"][0]["subtotal"] == "21.00" and datos["historial"] == []


async def test_cliente_ajeno_recibe_403_sin_datos_de_la_orden_caso_c06(http, mundo):
    r = await http.get(f"/ordenes/{mundo['ajena']}", headers=mundo["dueno"])
    assert r.status_code == 403
    assert "falla secreta" not in r.text and "BBB111" not in r.text
    assert r.json() == {"detail": "No tiene permiso para ver esta orden"}


@pytest.mark.parametrize("rol", ["ADMIN", "RECEPCION", "MECANICO"])
async def test_el_personal_ve_cualquier_orden(http, usuario_con_rol, mundo, rol):
    _, cab = await usuario_con_rol(rol)
    for clave in ("propia", "ajena", "propia_baja"):
        assert (await http.get(f"/ordenes/{mundo[clave]}", headers=cab)).status_code == 200


async def test_orden_inexistente_es_404_y_id_no_numerico_es_422(http, mundo):
    r = await http.get("/ordenes/999999", headers=mundo["dueno"])
    assert r.status_code == 404 and r.json() == {"detail": "Orden no encontrada"}
    assert (await http.get("/ordenes/abc", headers=mundo["dueno"])).status_code == 422
    assert (await http.get(f"/ordenes/{mundo['propia']}")).status_code == 401


async def test_mis_ordenes_solo_las_propias_incluso_de_vehiculos_dados_de_baja(http, mundo):
    r = await http.get("/mis-ordenes", headers=mundo["dueno"])
    assert r.status_code == 200
    assert [o["id"] for o in r.json()["items"]] == [mundo["propia"], mundo["propia_baja"]]
    assert r.json()["total"] == 2
    r = await http.get("/mis-ordenes", headers=mundo["otro"])
    assert [o["id"] for o in r.json()["items"]] == [mundo["ajena"]]


async def test_mis_ordenes_de_personal_sin_ficha_es_pagina_vacia(http, usuario_con_rol, mundo):
    _, cab = await usuario_con_rol("RECEPCION")
    r = await http.get("/mis-ordenes", headers=cab)
    assert r.status_code == 200
    assert r.json() == {"items": [], "total": 0, "page": 1, "size": 20, "pages": 1}


async def test_mis_ordenes_pagina_invalida_y_sin_sesion(http, mundo):
    assert (await http.get("/mis-ordenes", params={"page": 2}, headers=mundo["dueno"])).status_code == 422
    assert (await http.get("/mis-ordenes", params={"size": 101}, headers=mundo["dueno"])).status_code == 422
    assert (await http.get("/mis-ordenes")).status_code == 401


@pytest.mark.parametrize("ruta", ["/ordenes", "/ordenes/{orden}", "/mis-ordenes"])
async def test_usuario_con_cambio_de_password_pendiente_recibe_403_en_consultas(
    http, usuario_con_rol, mundo, ruta
):
    _, cab = await usuario_con_rol("RECEPCION", "pendiente@example.com", debe_cambiar_password=True)
    url = ruta.format(orden=mundo["propia"])
    r = await http.get(url, headers=cab)
    assert r.status_code == 403
    assert "AAA111" not in r.text and "items" not in r.json()


async def test_detalle_conserva_codigo_y_descripcion_de_un_repuesto_dado_de_baja(
    http, db_auth, usuario_con_rol, mundo
):
    from sqlalchemy import text

    _, cab = await usuario_con_rol("RECEPCION", "baja@example.com")
    async with db_auth.motor.begin() as c:
        await c.execute(text("UPDATE repuesto SET borrado_en = now() WHERE codigo = 'R1'"))
    r = await http.get(f"/ordenes/{mundo['propia']}", headers=cab)
    assert r.status_code == 200
    item = r.json()["items"][0]
    assert item["codigo"] == "R1" and item["descripcion"] == "Filtro de aceite"
