"""Usuario actual y autorización contra PostgreSQL real (C-05, tarea 6.4)."""
import re
import time
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event

from app.core.security import emitir_token

pytestmark = pytest.mark.integration

SIN_SESION = {"detail": "Se requiere iniciar sesión"}


def con_token(token: str) -> dict[str, str]:
    return {"Cookie": f"access_token={token}"}


async def test_token_valido_de_usuario_existente_pasa(http, db_auth, settings_auth):
    uid = await db_auth.crear_usuario("ana@example.com", "clave-de-prueba-1")
    r = await http.get("/prueba/autenticada", headers=con_token(emitir_token(uid, ["CLIENTE"], settings_auth)))
    assert r.status_code == 200
    assert r.json() == {"id": uid}


async def test_sub_inexistente_401(http, settings_auth):
    r = await http.get("/prueba/autenticada", headers=con_token(emitir_token(999, ["ADMIN"], settings_auth)))
    assert (r.status_code, r.json()) == (401, SIN_SESION)


async def test_usuario_inactivo_401(http, db_auth, settings_auth):
    uid = await db_auth.crear_usuario("off@example.com", "clave-de-prueba-1", activo=False)
    r = await http.get("/prueba/autenticada", headers=con_token(emitir_token(uid, [], settings_auth)))
    assert (r.status_code, r.json()) == (401, SIN_SESION)


async def test_usuario_desactivado_con_sesion_abierta_pasa_a_401(http, db_auth, settings_auth):
    uid = await db_auth.crear_usuario("ana@example.com", "clave-de-prueba-1")
    cab = con_token(emitir_token(uid, [], settings_auth))
    assert (await http.get("/prueba/autenticada", headers=cab)).status_code == 200
    await db_auth.ejecutar("UPDATE usuario SET activo = false WHERE id = :i", i=uid)
    assert (await http.get("/prueba/autenticada", headers=cab)).status_code == 401


async def test_password_cambiada_un_milisegundo_despues_del_iat_es_401(http, db_auth, settings_auth):
    uid = await db_auth.crear_usuario("ana@example.com", "clave-de-prueba-1")
    iat = time.time()
    cambio = datetime.fromtimestamp(iat, UTC) + timedelta(milliseconds=1)  # mismo segundo
    await db_auth.ejecutar("UPDATE usuario SET password_cambiada_en = :c WHERE id = :i", c=cambio, i=uid)
    r = await http.get("/prueba/autenticada", headers=con_token(emitir_token(uid, [], settings_auth, ahora=iat)))
    assert (r.status_code, r.json()) == (401, SIN_SESION)


@pytest.mark.parametrize("desfase_ms", [0, -1, -5000])
async def test_password_cambiada_igual_o_antes_del_iat_pasa(http, db_auth, settings_auth, desfase_ms):
    uid = await db_auth.crear_usuario("ana@example.com", "clave-de-prueba-1")
    iat = time.time()
    cambio = datetime.fromtimestamp(iat, UTC) + timedelta(milliseconds=desfase_ms)
    await db_auth.ejecutar("UPDATE usuario SET password_cambiada_en = :c WHERE id = :i", c=cambio, i=uid)
    r = await http.get("/prueba/autenticada", headers=con_token(emitir_token(uid, [], settings_auth, ahora=iat)))
    assert r.status_code == 200


async def test_rol_admin_vigente_ejecuta_la_ruta_con_rol(http, db_auth, settings_auth, ejecuciones_prueba):
    uid = await db_auth.crear_usuario("adm@example.com", "clave-de-prueba-1", roles=["ADMIN"])
    r = await http.get("/prueba/admin", headers=con_token(emitir_token(uid, ["ADMIN"], settings_auth)))
    assert r.status_code == 200
    assert ejecuciones_prueba["admin"] == 1


async def test_rol_revocado_en_la_base_con_token_que_dice_admin_es_403(
    http, db_auth, settings_auth, ejecuciones_prueba
):
    uid = await db_auth.crear_usuario("adm@example.com", "clave-de-prueba-1", roles=["ADMIN"])
    cab = con_token(emitir_token(uid, ["ADMIN"], settings_auth))
    assert (await http.get("/prueba/admin", headers=cab)).status_code == 200
    await db_auth.ejecutar("UPDATE asignacion_rol SET revocada_en = now() WHERE usuario_id = :i", i=uid)
    r = await http.get("/prueba/admin", headers=cab)
    assert r.status_code == 403
    assert r.json() == {"detail": "No tiene permiso para esta operación"}
    assert ejecuciones_prueba["admin"] == 1  # la segunda llamada no ejecuto la ruta


async def test_rol_vencido_en_la_base_es_403(http, db_auth, settings_auth):
    uid = await db_auth.crear_usuario("adm@example.com", "clave-de-prueba-1", roles=[])
    await db_auth.asignar_rol(uid, "ADMIN", vence_en=datetime.now(UTC) - timedelta(seconds=1))
    r = await http.get("/prueba/admin", headers=con_token(emitir_token(uid, ["ADMIN"], settings_auth)))
    assert r.status_code == 403


async def test_solo_cliente_en_ruta_de_admin_403_y_sin_cookie_401(http, db_auth, settings_auth):
    uid = await db_auth.crear_usuario("cli@example.com", "clave-de-prueba-1", roles=["CLIENTE"])
    r = await http.get("/prueba/admin", headers=con_token(emitir_token(uid, ["CLIENTE"], settings_auth)))
    assert r.status_code == 403
    assert (await http.get("/prueba/admin")).status_code == 401


async def test_ruta_con_rol_consulta_usuario_una_sola_vez_por_peticion(
    http, db_auth, settings_auth, motor_auth
):
    uid = await db_auth.crear_usuario("adm@example.com", "clave-de-prueba-1", roles=["ADMIN"])
    sentencias: list[str] = []

    def contar(conn, cursor, statement, parameters, context, executemany):
        sentencias.append(statement)

    event.listen(motor_auth.sync_engine, "before_cursor_execute", contar)
    try:
        r = await http.get("/prueba/admin", headers=con_token(emitir_token(uid, ["ADMIN"], settings_auth)))
    finally:
        event.remove(motor_auth.sync_engine, "before_cursor_execute", contar)
    assert r.status_code == 200
    a_usuario = [s for s in sentencias if re.search(r"FROM usuario\b", s)]
    assert len(a_usuario) == 1
    assert len([s for s in sentencias if "FROM asignacion_rol" in s]) == 1


async def test_cambio_pendiente_bloquea_el_grupo_protegido_pero_no_la_ruta_abierta(
    http, db_auth, settings_auth
):
    uid = await db_auth.crear_usuario(
        "nuevo@example.com", "clave-de-prueba-1", roles=["ADMIN"], debe_cambiar_password=True
    )
    cab = con_token(emitir_token(uid, ["ADMIN"], settings_auth))
    r = await http.get("/prueba/admin", headers=cab)
    assert (r.status_code, r.json()) == (403, {"detail": "Debe cambiar la contraseña antes de continuar"})
    assert (await http.get("/prueba/autenticada", headers=cab)).status_code == 200
    assert (await http.get("/health/live")).status_code == 200
