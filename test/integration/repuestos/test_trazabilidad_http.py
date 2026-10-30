"""Consulta de movimientos y precios (C-08, 7.5; specs stock-repuestos / historial-precios)."""
import pytest

from test.integration.repuestos.ayudantes import sembrar_repuesto

pytestmark = pytest.mark.integration

ALTA = {"codigo": "TRZ", "descripcion": "Trazable", "precio": 8000, "stock_inicial": 10}


async def _repuesto_con_trazas(http, admin) -> int:
    rid = (await http.post("/repuestos", json=ALTA, headers=admin)).json()["id"]
    assert (await http.post(f"/repuestos/{rid}/reponer", json={"cantidad": 5}, headers=admin)).status_code == 200
    assert (await http.patch(f"/repuestos/{rid}", json={"precio": 8500}, headers=admin)).status_code == 200
    return rid


async def test_movimientos_en_orden_cronologico(http, admin, admin_id):
    rid = await _repuesto_con_trazas(http, admin)
    r = await http.get(f"/repuestos/{rid}/movimientos", headers=admin)
    assert r.status_code == 200
    cuerpo = r.json()
    assert (cuerpo["total"], cuerpo["pages"], cuerpo["page"]) == (2, 1, 1)
    assert [(i["motivo"], i["cantidad"]) for i in cuerpo["items"]] == [("Stock inicial", 10), ("Reposición", 5)]
    primero = cuerpo["items"][0]
    assert set(primero) == {"id", "repuesto_id", "orden_id", "usuario_id", "cantidad", "motivo", "cuando"}
    assert (primero["repuesto_id"], primero["usuario_id"], primero["orden_id"]) == (rid, admin_id, None)


async def test_precios_con_cadenas_de_dos_decimales(http, admin, admin_id):
    rid = await _repuesto_con_trazas(http, admin)
    r = await http.get(f"/repuestos/{rid}/precios", headers=admin)
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["total"] == 1
    item = cuerpo["items"][0]
    assert (item["precio_anterior"], item["precio_nuevo"]) == ("8000.00", "8500.00")
    assert set(item) == {"id", "repuesto_id", "usuario_id", "precio_anterior", "precio_nuevo", "cuando"}
    assert (item["repuesto_id"], item["usuario_id"]) == (rid, admin_id)


async def test_precios_sin_cambios_es_lista_vacia_de_una_pagina(http, db_auth, admin):
    rid = await sembrar_repuesto(db_auth)
    cuerpo = (await http.get(f"/repuestos/{rid}/precios", headers=admin)).json()
    assert (cuerpo["items"], cuerpo["total"], cuerpo["pages"]) == ([], 0, 1)


async def test_movimientos_sin_ninguno_es_lista_vacia(http, db_auth, admin):
    rid = await sembrar_repuesto(db_auth)
    cuerpo = (await http.get(f"/repuestos/{rid}/movimientos", headers=admin)).json()
    assert (cuerpo["items"], cuerpo["total"], cuerpo["pages"]) == ([], 0, 1)


@pytest.mark.parametrize("ruta", ["movimientos", "precios"])
@pytest.mark.parametrize("rol", ["RECEPCION", "MECANICO"])
async def test_solo_admin_consulta_la_trazabilidad(http, db_auth, usuario_con_rol, ruta, rol):
    rid = await sembrar_repuesto(db_auth)
    _, cab = await usuario_con_rol(rol)
    assert (await http.get(f"/repuestos/{rid}/{ruta}", headers=cab)).status_code == 403


@pytest.mark.parametrize("ruta", ["movimientos", "precios"])
async def test_repuesto_dado_de_baja_o_inexistente_es_404(http, db_auth, admin, ruta):
    baja = await sembrar_repuesto(db_auth, borrado=True)
    assert (await http.get(f"/repuestos/{baja}/{ruta}", headers=admin)).status_code == 404
    assert (await http.get(f"/repuestos/999999/{ruta}", headers=admin)).status_code == 404


@pytest.mark.parametrize("ruta", ["movimientos", "precios"])
async def test_pagina_fuera_de_rango_o_invalida_es_422(http, db_auth, admin, ruta):
    rid = await sembrar_repuesto(db_auth)
    assert (await http.get(f"/repuestos/{rid}/{ruta}", params={"page": 2}, headers=admin)).status_code == 422
    assert (await http.get(f"/repuestos/{rid}/{ruta}", params={"size": 500}, headers=admin)).status_code == 422


async def test_movimientos_se_pagina_por_id(http, admin):
    rid = (await http.post("/repuestos", json=ALTA, headers=admin)).json()["id"]
    for _ in range(2):
        await http.post(f"/repuestos/{rid}/reponer", json={"cantidad": 1}, headers=admin)
    r = await http.get(f"/repuestos/{rid}/movimientos", params={"size": 2, "page": 2}, headers=admin)
    cuerpo = r.json()
    assert (cuerpo["total"], cuerpo["pages"]) == (3, 2)
    assert [i["motivo"] for i in cuerpo["items"]] == ["Reposición"]
