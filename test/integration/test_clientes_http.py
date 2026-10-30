"""POST /clientes y GET /clientes/{id} sobre HTTP y PostgreSQL real (C-07, tareas 5.2, 5.4, 5.5).

Orden de evaluacion documentado: 401 (sin sesion) -> 403 (cambio pendiente / rol) -> 422/404 -> 409.
"""
import re
from datetime import UTC, datetime

import pytest
from sqlalchemy import event

from test.integration.ayudantes_clientes import (
    cabecera,
    personal,
    sembrar_cliente,
    sembrar_vehiculo,
)

pytestmark = pytest.mark.integration

CUERPO = {"nombre": "Ana Perez", "documento": "30111222", "telefono": "3815550000"}


# --- Acceso (5.2) --------------------------------------------------------------------


async def test_sin_cookie_es_401_y_no_crea_filas(http, db_auth):
    r = await http.post("/clientes", json=CUERPO)
    assert r.status_code == 401
    assert await db_auth.contar("cliente") == 0


async def test_cambio_de_password_pendiente_es_403(http, db_auth, settings_auth):
    uid = await db_auth.crear_usuario(
        "nuevo@example.com", "x" * 10, roles=("RECEPCION",), debe_cambiar_password=True
    )
    r = await http.post("/clientes", json=CUERPO, headers=cabecera(uid, ("RECEPCION",), settings_auth))
    assert r.status_code == 403
    assert await db_auth.contar("cliente") == 0


async def test_cliente_consultando_su_propia_ficha_es_403(http, db_auth, settings_auth):
    uid = await db_auth.crear_usuario("c@example.com", "x" * 10, roles=("CLIENTE",))
    cid = await sembrar_cliente(db_auth, "99", uid)
    r = await http.get(f"/clientes/{cid}", headers=cabecera(uid, ("CLIENTE",), settings_auth))
    assert r.status_code == 403


async def test_mecanico_sobre_id_inexistente_es_403_no_404(http, db_auth, settings_auth):
    _, cab = await personal(db_auth, settings_auth, "MECANICO")
    assert (await http.get("/clientes/999999", headers=cab)).status_code == 403


async def test_cliente_no_puede_dar_de_alta(http, db_auth, settings_auth):
    _, cab = await personal(db_auth, settings_auth, "CLIENTE")
    assert (await http.post("/clientes", json=CUERPO, headers=cab)).status_code == 403
    assert await db_auth.contar("cliente") == 0


async def test_rol_recepcion_revocado_en_la_base_es_403_aunque_el_token_lo_diga(
    http, db_auth, settings_auth
):
    uid = await db_auth.crear_usuario("r@example.com", "x" * 10, roles=("CLIENTE",))
    await db_auth.asignar_rol(uid, "RECEPCION", revocada_en=datetime.now(UTC))
    r = await http.post("/clientes", json=CUERPO, headers=cabecera(uid, ("RECEPCION",), settings_auth))
    assert r.status_code == 403
    assert await db_auth.contar("cliente") == 0


@pytest.mark.parametrize("rol", ["RECEPCION", "ADMIN"])
async def test_recepcion_y_admin_dan_de_alta(http, db_auth, settings_auth, rol):
    _, cab = await personal(db_auth, settings_auth, rol)
    r = await http.post("/clientes", json=CUERPO, headers=cab)
    assert r.status_code == 201
    assert r.json() == {"id": r.json()["id"], **CUERPO, "usuario_id": None}
    filas = await db_auth.filas("SELECT usuario_id, documento FROM cliente")
    assert filas == [{"usuario_id": None, "documento": "30111222"}]
    assert await db_auth.contar("vehiculo") == 0


# --- Contrato y 409 (5.4) ----------------------------------------------------------------


async def test_campo_extra_es_422_sin_filas(http, db_auth, settings_auth):
    _, cab = await personal(db_auth, settings_auth)
    r = await http.post("/clientes", json={**CUERPO, "usuario_id": 1}, headers=cab)
    assert r.status_code == 422
    assert await db_auth.contar("cliente") == 0


async def test_documento_solo_espacios_es_422(http, db_auth, settings_auth):
    _, cab = await personal(db_auth, settings_auth)
    assert (await http.post("/clientes", json={**CUERPO, "documento": "   "}, headers=cab)).status_code == 422


async def test_documento_se_guarda_recortado(http, db_auth, settings_auth):
    _, cab = await personal(db_auth, settings_auth)
    r = await http.post("/clientes", json={**CUERPO, "documento": "  30111222 "}, headers=cab)
    assert r.status_code == 201 and r.json()["documento"] == "30111222"


async def test_documento_de_cliente_auto_registrado_es_409_sin_texto_de_la_base(
    http, db_auth, settings_auth
):
    uid = await db_auth.crear_usuario("web@example.com", "x" * 10, roles=("CLIENTE",))
    await sembrar_cliente(db_auth, "30111222", uid)
    _, cab = await personal(db_auth, settings_auth)
    r = await http.post("/clientes", json=CUERPO, headers=cab)
    assert r.status_code == 409
    assert r.json() == {"detail": "El documento ya pertenece a un cliente del taller"}
    assert await db_auth.contar("cliente") == 1


async def test_documento_repetido_entre_altas_del_personal(http, db_auth, settings_auth):
    _, cab = await personal(db_auth, settings_auth)
    assert (await http.post("/clientes", json=CUERPO, headers=cab)).status_code == 201
    r = await http.post("/clientes", json={**CUERPO, "nombre": "Otro"}, headers=cab)
    assert r.status_code == 409
    cuerpo = r.text.lower()
    for ajeno in ("uq_", "cliente_", "constraint", "duplicate", "violates"):
        assert ajeno not in cuerpo
    assert await db_auth.contar("cliente") == 1
    assert (await db_auth.filas("SELECT nombre FROM cliente"))[0]["nombre"] == "Ana Perez"


async def test_registro_web_con_documento_de_ficha_del_personal_es_409_y_no_la_apropia(
    http, db_auth, settings_auth
):
    _, cab = await personal(db_auth, settings_auth)
    cid = (await http.post("/clientes", json=CUERPO, headers=cab)).json()["id"]
    r = await http.post(
        "/auth/registro",
        json={
            "email": "intruso@example.com",
            "password": "pw-" + "z" * 12,
            "nombre": "Otra Persona",
            "documento": "30111222",
            "telefono": "1",
        },
    )
    assert r.status_code == 409
    filas = await db_auth.filas("SELECT usuario_id FROM cliente WHERE id = :i", i=cid)
    assert filas == [{"usuario_id": None}]
    assert await db_auth.contar("usuario") == 1  # solo el de personal


# --- Consulta (5.4) ------------------------------------------------------------------------


async def test_detalle_devuelve_solo_vigentes_ordenados_por_id(http, db_auth, settings_auth):
    _, cab = await personal(db_auth, settings_auth, "ADMIN")
    cid = await sembrar_cliente(db_auth, "1", nombre="Beto")
    a = await sembrar_vehiculo(db_auth, cid, "AAA111")
    await sembrar_vehiculo(db_auth, cid, "BBB222", baja=True)
    b = await sembrar_vehiculo(db_auth, cid, "CCC333")
    r = await http.get(f"/clientes/{cid}", headers=cab)
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["id"] == cid and cuerpo["usuario_id"] is None and cuerpo["nombre"] == "Beto"
    assert [v["id"] for v in cuerpo["vehiculos"]] == [a, b]
    assert set(cuerpo["vehiculos"][0]) == {"id", "patente", "marca", "modelo", "anio"}
    assert "borrado_en" not in r.text


async def test_detalle_sin_vehiculos_devuelve_lista_vacia(http, db_auth, settings_auth):
    _, cab = await personal(db_auth, settings_auth)
    cid = await sembrar_cliente(db_auth, "1")
    assert (await http.get(f"/clientes/{cid}", headers=cab)).json()["vehiculos"] == []


async def test_detalle_de_inexistente_es_404_con_mensaje_propio(http, db_auth, settings_auth):
    _, cab = await personal(db_auth, settings_auth, "ADMIN")
    r = await http.get("/clientes/999999", headers=cab)
    assert r.status_code == 404 and r.json() == {"detail": "Cliente no encontrado"}


async def test_detalle_con_id_no_entero_es_422(http, db_auth, settings_auth):
    _, cab = await personal(db_auth, settings_auth, "ADMIN")
    assert (await http.get("/clientes/abc", headers=cab)).status_code == 422


async def test_detalle_sin_cookie_es_401(http):
    assert (await http.get("/clientes/1")).status_code == 401


# --- Sin N+1 (5.5) ----------------------------------------------------------------------------


async def _sentencias_del_detalle(http, motor, cab, cid) -> list[str]:
    sentencias: list[str] = []

    def capturar(conn, cursor, statement, parameters, context, executemany):
        sentencias.append(statement)

    event.listen(motor.sync_engine, "before_cursor_execute", capturar)
    try:
        r = await http.get(f"/clientes/{cid}", headers=cab)
    finally:
        event.remove(motor.sync_engine, "before_cursor_execute", capturar)
    assert r.status_code == 200
    return [s for s in sentencias if re.search(r"FROM (cliente|vehiculo)\b", s)]


async def test_detalle_ejecuta_el_mismo_numero_de_sentencias_con_1_y_con_4_vehiculos(
    http, db_auth, settings_auth, motor_auth
):
    _, cab = await personal(db_auth, settings_auth, "ADMIN")
    uno = await sembrar_cliente(db_auth, "1")
    await sembrar_vehiculo(db_auth, uno, "AAA001")
    cuatro = await sembrar_cliente(db_auth, "2")
    for i in range(4):
        await sembrar_vehiculo(db_auth, cuatro, f"BBB00{i}")
    s1 = await _sentencias_del_detalle(http, motor_auth, cab, uno)
    s4 = await _sentencias_del_detalle(http, motor_auth, cab, cuatro)
    assert len(s1) == len(s4) == 2
    assert sum("FROM vehiculo" in s for s in s4) == 1
