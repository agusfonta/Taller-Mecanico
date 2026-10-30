"""GET /mis-vehiculos sobre HTTP y PostgreSQL real (C-07, tarea 5.8): solo lo propio (RN-17)."""
import pytest

from test.integration.ayudantes_clientes import cabecera, personal, sembrar_cliente, sembrar_vehiculo

pytestmark = pytest.mark.integration


async def _cliente_web(db, settings, email, documento):
    uid = await db.crear_usuario(email, "x" * 10, roles=("CLIENTE",))
    cid = await sembrar_cliente(db, documento, uid)
    return uid, cid, cabecera(uid, ("CLIENTE",), settings)


async def test_dos_clientes_ven_solo_sus_vehiculos(http, db_auth, settings_auth):
    _, c1, cab1 = await _cliente_web(db_auth, settings_auth, "a@example.com", "1")
    _, c2, cab2 = await _cliente_web(db_auth, settings_auth, "b@example.com", "2")
    a2 = await sembrar_vehiculo(db_auth, c1, "AAA222")
    a1 = await sembrar_vehiculo(db_auth, c1, "AAA111")
    b1 = await sembrar_vehiculo(db_auth, c2, "BBB111")
    r1 = await http.get("/mis-vehiculos", headers=cab1)
    r2 = await http.get("/mis-vehiculos", headers=cab2)
    assert r1.status_code == r2.status_code == 200
    assert [v["id"] for v in r1.json()] == [a2, a1]
    assert [v["id"] for v in r2.json()] == [b1]
    assert r1.json()[0] == {"id": a2, "cliente_id": c1, "patente": "AAA222",
                            "marca": "Fiat", "modelo": "Uno", "anio": 2020}


async def test_vehiculo_dado_de_baja_no_aparece(http, db_auth, settings_auth):
    _, cid, cab = await _cliente_web(db_auth, settings_auth, "a@example.com", "1")
    vigente = await sembrar_vehiculo(db_auth, cid, "AAA111")
    await sembrar_vehiculo(db_auth, cid, "AAA222", baja=True)
    r = await http.get("/mis-vehiculos", headers=cab)
    assert [v["id"] for v in r.json()] == [vigente]
    assert "borrado_en" not in r.text


async def test_admin_sin_ficha_recibe_lista_vacia(http, db_auth, settings_auth):
    _, cab = await personal(db_auth, settings_auth, "ADMIN")
    await sembrar_vehiculo(db_auth, await sembrar_cliente(db_auth, "1"), "AAA111")
    r = await http.get("/mis-vehiculos", headers=cab)
    assert r.status_code == 200 and r.json() == []


async def test_ficha_sin_usuario_no_aparece_para_otro_cliente(http, db_auth, settings_auth):
    _, _, cab = await _cliente_web(db_auth, settings_auth, "a@example.com", "1")
    huerfana = await sembrar_cliente(db_auth, "2")
    await sembrar_vehiculo(db_auth, huerfana, "ZZZ111")
    assert (await http.get("/mis-vehiculos", headers=cab)).json() == []


async def test_no_acepta_parametros_que_elijan_cliente(http, db_auth, settings_auth):
    _, _, cab = await _cliente_web(db_auth, settings_auth, "a@example.com", "1")
    ajeno = await sembrar_cliente(db_auth, "2")
    await sembrar_vehiculo(db_auth, ajeno, "ZZZ111")
    r = await http.get(f"/mis-vehiculos?cliente_id={ajeno}", headers=cab)
    assert r.status_code == 200 and r.json() == []


async def test_sin_cookie_es_401(http):
    assert (await http.get("/mis-vehiculos")).status_code == 401


async def test_con_cambio_pendiente_es_403(http, db_auth, settings_auth):
    uid = await db_auth.crear_usuario(
        "p@example.com", "x" * 10, roles=("CLIENTE",), debe_cambiar_password=True
    )
    r = await http.get("/mis-vehiculos", headers=cabecera(uid, ("CLIENTE",), settings_auth))
    assert r.status_code == 403
