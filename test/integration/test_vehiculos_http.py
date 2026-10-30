"""Alta y baja de vehiculos sobre HTTP y PostgreSQL real (C-07, tareas 5.6 y 5.7)."""
import pytest

from test.integration.ayudantes_clientes import (
    cabecera,
    personal,
    sembrar_catalogo,
    sembrar_cliente,
    sembrar_orden,
    sembrar_vehiculo,
)

pytestmark = pytest.mark.integration

VEHICULO = {"patente": "AB123CD", "marca": "Fiat", "modelo": "Uno", "anio": 2020}


# --- Alta (5.6) ----------------------------------------------------------------------------


async def test_alta_normaliza_la_patente_y_aparece_en_el_detalle(http, db_auth, settings_auth):
    _, cab = await personal(db_auth, settings_auth)
    cid = await sembrar_cliente(db_auth, "1")
    r = await http.post(f"/clientes/{cid}/vehiculos", json={**VEHICULO, "patente": " ab-123 cd "}, headers=cab)
    assert r.status_code == 201
    cuerpo = r.json()
    assert cuerpo == {"id": cuerpo["id"], "cliente_id": cid, "patente": "AB123CD",
                      "marca": "Fiat", "modelo": "Uno", "anio": 2020}
    assert (await db_auth.filas("SELECT patente FROM vehiculo"))[0]["patente"] == "AB123CD"
    detalle = (await http.get(f"/clientes/{cid}", headers=cab)).json()
    assert [v["id"] for v in detalle["vehiculos"]] == [cuerpo["id"]]


@pytest.mark.parametrize("anio", [1950, 2100])
async def test_anio_en_el_borde_es_201(http, db_auth, settings_auth, anio):
    _, cab = await personal(db_auth, settings_auth)
    cid = await sembrar_cliente(db_auth, "1")
    r = await http.post(f"/clientes/{cid}/vehiculos", json={**VEHICULO, "anio": anio}, headers=cab)
    assert r.status_code == 201 and r.json()["anio"] == anio


async def test_cliente_inexistente_es_404_sin_filas(http, db_auth, settings_auth):
    _, cab = await personal(db_auth, settings_auth)
    r = await http.post("/clientes/999999/vehiculos", json=VEHICULO, headers=cab)
    assert r.status_code == 404 and r.json() == {"detail": "Cliente no encontrado"}
    assert await db_auth.contar("vehiculo") == 0


async def test_patente_vigente_de_otro_cliente_es_409(http, db_auth, settings_auth):
    _, cab = await personal(db_auth, settings_auth)
    a = await sembrar_cliente(db_auth, "1")
    b = await sembrar_cliente(db_auth, "2")
    await sembrar_vehiculo(db_auth, a, "AB123CD")
    r = await http.post(f"/clientes/{b}/vehiculos", json=VEHICULO, headers=cab)
    assert r.status_code == 409
    assert r.json() == {"detail": "Ya hay un vehículo vigente con esa patente"}
    assert await db_auth.contar("vehiculo") == 1


async def test_patente_con_otra_escritura_es_409(http, db_auth, settings_auth):
    _, cab = await personal(db_auth, settings_auth)
    cid = await sembrar_cliente(db_auth, "1")
    await sembrar_vehiculo(db_auth, cid, "AB123CD")
    r = await http.post(f"/clientes/{cid}/vehiculos", json={**VEHICULO, "patente": "ab 123 cd"}, headers=cab)
    assert r.status_code == 409
    assert await db_auth.contar("vehiculo") == 1


@pytest.mark.parametrize(
    "cambio",
    [
        {"anio": 1949},
        {"anio": 2101},
        {"anio": "2020"},
        {"anio": 2020.5},
        {"anio": True},
        {"patente": "AB*123"},
        {"patente": " - "},
        {"marca": "  "},
        {"cliente_id": 5},
        {"borrado_en": "2020-01-01T00:00:00Z"},
    ],
)
async def test_contrato_invalido_es_422_sin_filas(http, db_auth, settings_auth, cambio):
    _, cab = await personal(db_auth, settings_auth)
    cid = await sembrar_cliente(db_auth, "1")
    r = await http.post(f"/clientes/{cid}/vehiculos", json={**VEHICULO, **cambio}, headers=cab)
    assert r.status_code == 422
    assert await db_auth.contar("vehiculo") == 0


async def test_mecanico_no_puede_cargar_vehiculos(http, db_auth, settings_auth):
    _, cab = await personal(db_auth, settings_auth, "MECANICO")
    cid = await sembrar_cliente(db_auth, "1")
    assert (await http.post(f"/clientes/{cid}/vehiculos", json=VEHICULO, headers=cab)).status_code == 403
    assert await db_auth.contar("vehiculo") == 0


async def test_alta_sin_cookie_es_401(http, db_auth):
    cid = await sembrar_cliente(db_auth, "1")
    assert (await http.post(f"/clientes/{cid}/vehiculos", json=VEHICULO)).status_code == 401


# --- Baja (5.7) ------------------------------------------------------------------------------


async def test_baja_204_sin_cuerpo_conserva_fila_y_desaparece_del_detalle(http, db_auth, settings_auth):
    _, cab = await personal(db_auth, settings_auth)
    cid = await sembrar_cliente(db_auth, "1")
    vid = await sembrar_vehiculo(db_auth, cid, "AAA111")
    r = await http.delete(f"/vehiculos/{vid}", headers=cab)
    assert r.status_code == 204 and r.content == b""
    filas = await db_auth.filas("SELECT borrado_en FROM vehiculo WHERE id = :i", i=vid)
    assert len(filas) == 1 and filas[0]["borrado_en"] is not None
    assert (await http.get(f"/clientes/{cid}", headers=cab)).json()["vehiculos"] == []


async def test_segunda_baja_es_404(http, db_auth, settings_auth):
    _, cab = await personal(db_auth, settings_auth)
    vid = await sembrar_vehiculo(db_auth, await sembrar_cliente(db_auth, "1"), "AAA111")
    assert (await http.delete(f"/vehiculos/{vid}", headers=cab)).status_code == 204
    r = await http.delete(f"/vehiculos/{vid}", headers=cab)
    assert r.status_code == 404 and r.json() == {"detail": "Vehículo no encontrado"}


async def test_baja_de_inexistente_es_404_y_de_id_no_entero_422(http, db_auth, settings_auth):
    _, cab = await personal(db_auth, settings_auth, "ADMIN")
    assert (await http.delete("/vehiculos/999999", headers=cab)).status_code == 404
    assert (await http.delete("/vehiculos/abc", headers=cab)).status_code == 422


@pytest.mark.parametrize("estado", ["PENDIENTE", "EN_REPARACION"])
async def test_baja_con_orden_abierta_es_409_y_no_modifica(http, db_auth, settings_auth, estado):
    await sembrar_catalogo(db_auth)
    _, cab = await personal(db_auth, settings_auth)
    vid = await sembrar_vehiculo(db_auth, await sembrar_cliente(db_auth, "1"), "AAA111")
    await sembrar_orden(db_auth, vid, estado)
    r = await http.delete(f"/vehiculos/{vid}", headers=cab)
    assert r.status_code == 409 and r.json() == {"detail": "El vehículo tiene órdenes abiertas"}
    assert (await db_auth.filas("SELECT borrado_en FROM vehiculo"))[0]["borrado_en"] is None


async def test_baja_con_solo_ordenes_finales_es_204_y_conserva_las_ordenes(http, db_auth, settings_auth):
    await sembrar_catalogo(db_auth)
    _, cab = await personal(db_auth, settings_auth)
    vid = await sembrar_vehiculo(db_auth, await sembrar_cliente(db_auth, "1"), "AAA111")
    await sembrar_orden(db_auth, vid, "TERMINADA")
    await sembrar_orden(db_auth, vid, "CANCELADA")
    assert (await http.delete(f"/vehiculos/{vid}", headers=cab)).status_code == 204
    assert await db_auth.contar("orden_trabajo") == 2


async def test_el_catalogo_decide_estado_final_de_nombre_arbitrario(http, db_auth, settings_auth):
    await sembrar_catalogo(db_auth, (("ARCHIVADA_X", 9, True),))
    _, cab = await personal(db_auth, settings_auth)
    vid = await sembrar_vehiculo(db_auth, await sembrar_cliente(db_auth, "1"), "AAA111")
    await sembrar_orden(db_auth, vid, "ARCHIVADA_X")
    assert (await http.delete(f"/vehiculos/{vid}", headers=cab)).status_code == 204


async def test_cliente_no_puede_dar_de_baja_su_vehiculo(http, db_auth, settings_auth):
    uid = await db_auth.crear_usuario("c@example.com", "x" * 10, roles=("CLIENTE",))
    vid = await sembrar_vehiculo(db_auth, await sembrar_cliente(db_auth, "1", uid), "AAA111")
    r = await http.delete(f"/vehiculos/{vid}", headers=cabecera(uid, ("CLIENTE",), settings_auth))
    assert r.status_code == 403
    assert (await db_auth.filas("SELECT borrado_en FROM vehiculo"))[0]["borrado_en"] is None


async def test_baja_sin_cookie_es_401(http, db_auth):
    vid = await sembrar_vehiculo(db_auth, await sembrar_cliente(db_auth, "1"), "AAA111")
    assert (await http.delete(f"/vehiculos/{vid}")).status_code == 401


async def test_c19_baja_libera_la_patente_para_otro_cliente(http, db_auth, settings_auth):
    _, cab = await personal(db_auth, settings_auth)
    a = await sembrar_cliente(db_auth, "1")
    b = await sembrar_cliente(db_auth, "2")
    vid = await sembrar_vehiculo(db_auth, a, "AB123CD")
    assert (await http.delete(f"/vehiculos/{vid}", headers=cab)).status_code == 204
    nuevo = await http.post(f"/clientes/{b}/vehiculos", json=VEHICULO, headers=cab)
    assert nuevo.status_code == 201 and nuevo.json()["id"] != vid
    assert (await http.post(f"/clientes/{a}/vehiculos", json=VEHICULO, headers=cab)).status_code == 409
    assert await db_auth.contar("vehiculo") == 2
