"""GET /eventos (historial de seguridad) contra PostgreSQL real (C-06, tareas 8.1 a 8.4)."""
from datetime import UTC, datetime, timedelta

import pytest

from test.integration.sesiones import admin_con_sesion, clave, entrar, usuario_con_sesion

pytestmark = pytest.mark.integration

ADMIN = "admin@taller.com"
CAMPOS = {"id", "cuando", "actor", "accion"}


async def _tres_eventos(db_auth, fabrica_http):
    """Registro de cliente -> cambio de contrasena -> asignacion de MECANICO por un ADMIN."""
    admin_id, admin = await admin_con_sesion(db_auth, fabrica_http, ADMIN)
    pw = clave()
    cliente = fabrica_http("203.0.113.9")
    r = await cliente.post(
        "/auth/registro",
        json={"email": "cli@taller.com", "password": pw, "nombre": "Cli", "documento": "123", "telefono": "555"},
    )
    assert r.status_code == 201, r.text
    await entrar(cliente, "cli@taller.com", pw)
    r = await cliente.post(
        "/auth/cambiar-password", json={"password_actual": pw, "password_nueva": clave()}
    )
    assert r.status_code == 200, r.text
    cliente_id = await _id(db_auth, "cli@taller.com")
    r = await admin.post(f"/usuarios/{cliente_id}/roles", json={"rol": "MECANICO"})
    assert r.status_code == 201, r.text
    return admin


async def _id(db_auth, email):
    return (await db_auth.filas("SELECT id FROM usuario WHERE email = :e", e=email))[0]["id"]


async def test_eventos_lista_mas_reciente_primero_con_los_campos_del_contrato(db_auth, fabrica_http):
    admin = await _tres_eventos(db_auth, fabrica_http)
    r = await admin.get("/eventos")
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert set(cuerpo) == {"items", "total", "page", "size", "pages"}
    assert cuerpo["total"] == 3 and cuerpo["page"] == 1 and cuerpo["size"] == 20 and cuerpo["pages"] == 1
    assert all(set(e) == CAMPOS for e in cuerpo["items"])
    assert [(e["actor"], e["accion"]) for e in cuerpo["items"]] == [
        (ADMIN, "Asignación de rol MECANICO a cli@taller.com"),
        ("cli@taller.com", "Cambio de contraseña"),
        ("cli@taller.com", "Registro de cliente"),
    ]
    cuandos = [datetime.fromisoformat(e["cuando"]) for e in cuerpo["items"]]
    assert cuandos == sorted(cuandos, reverse=True)


async def test_eventos_paginacion_page_2_size_2_trae_el_mas_viejo(db_auth, fabrica_http):
    admin = await _tres_eventos(db_auth, fabrica_http)
    r = await admin.get("/eventos", params={"page": 2, "size": 2})
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["total"] == 3 and cuerpo["pages"] == 2 and cuerpo["page"] == 2 and cuerpo["size"] == 2
    assert [e["accion"] for e in cuerpo["items"]] == ["Registro de cliente"]


# --- 8.3 triangular --------------------------------------------------------------------------


@pytest.mark.parametrize("params", [{"size": 500}, {"size": 0}, {"page": 0}])
async def test_eventos_parametros_fuera_de_rango_dan_422(db_auth, fabrica_http, params):
    _, admin = await admin_con_sesion(db_auth, fabrica_http, ADMIN)
    assert (await admin.get("/eventos", params=params)).status_code == 422


async def test_eventos_pagina_mas_alla_de_la_ultima_da_422_con_mensaje_propio(db_auth, fabrica_http):
    admin = await _tres_eventos(db_auth, fabrica_http)
    r = await admin.get("/eventos", params={"page": 3, "size": 2})
    assert r.status_code == 422 and r.json() == {"detail": "La página solicitada no existe"}


async def test_eventos_sin_eventos_da_200_con_items_vacios_y_una_pagina(db_auth, fabrica_http):
    _, admin = await admin_con_sesion(db_auth, fabrica_http, ADMIN)
    r = await admin.get("/eventos")
    assert r.status_code == 200
    assert r.json() == {"items": [], "total": 0, "page": 1, "size": 20, "pages": 1}


async def test_eventos_incluye_uno_insertado_por_sql_con_actor_sistema(db_auth, fabrica_http):
    _, admin = await admin_con_sesion(db_auth, fabrica_http, ADMIN)
    await db_auth.ejecutar(
        "INSERT INTO evento_seguridad (cuando, actor, accion) VALUES (:w, 'SISTEMA', 'Carga de los datos iniciales')",
        w=datetime.now(UTC) + timedelta(minutes=1),
    )
    items = (await admin.get("/eventos")).json()["items"]
    assert items[0]["actor"] == "SISTEMA" and items[0]["accion"] == "Carga de los datos iniciales"


async def test_eventos_un_cliente_recibe_403(db_auth, fabrica_http):
    _, http, _ = await usuario_con_sesion(db_auth, fabrica_http, "c@taller.com", roles=("CLIENTE",))
    r = await http.get("/eventos")
    assert r.status_code == 403 and r.json() == {"detail": "No tiene permiso para esta operación"}


async def test_las_peticiones_rechazadas_no_agregan_eventos(db_auth, fabrica_http):
    _, admin = await admin_con_sesion(db_auth, fabrica_http, ADMIN)
    existente = await db_auth.crear_usuario("ya@taller.com", clave(), roles=("MECANICO",))
    antes = (await admin.get("/eventos")).json()["total"]
    rechazadas = [
        ("POST", "/usuarios", {"email": "YA@taller.com", "nombre": "x", "password": clave(), "rol": "ADMIN"}, 409),
        ("POST", "/usuarios", {"email": "n@taller.com", "nombre": "x", "password": clave(), "rol": "CLIENTE"}, 422),
        ("POST", f"/usuarios/{existente}/roles", {"rol": "MECANICO"}, 409),
        ("POST", "/usuarios/999999/roles", {"rol": "MECANICO"}, 404),
        ("POST", f"/usuarios/{existente}/roles", {"rol": "MECANICO", "vence_en": "2099-01-01T00:00:00"}, 422),
        ("DELETE", f"/usuarios/{existente}/roles/RECEPCION", None, 404),
        ("DELETE", "/usuarios/999999/roles/MECANICO", None, 404),
        ("DELETE", f"/usuarios/{existente}/roles/JEFE", None, 422),
    ]
    for metodo, ruta, cuerpo, esperado in rechazadas:
        r = await admin.request(metodo, ruta, json=cuerpo)
        assert r.status_code == esperado, (metodo, ruta, r.status_code, r.text)
    assert (await admin.get("/eventos")).json()["total"] == antes
