"""GET /auth/yo y POST /auth/cambiar-password contra PostgreSQL real (C-05, tareas 9.1 a 9.7)."""
import secrets
from datetime import UTC, datetime, timedelta

import pytest

pytestmark = pytest.mark.integration

EMAIL = "ana@example.com"
SIN_SESION = {"detail": "Se requiere iniciar sesión"}


@pytest.fixture
def clave() -> str:
    return "pw-" + secrets.token_urlsafe(12)


@pytest.fixture
def clave_nueva() -> str:
    return "nueva-" + secrets.token_urlsafe(12)


def login(email, password):
    return {"email": email, "password": password}


async def entrar(http, email, password):
    r = await http.post("/auth/login", json=login(email, password))
    assert r.status_code == 200, r.text
    return r


def cabecera_cookie(http) -> dict[str, str]:
    return {"Cookie": f"access_token={http.cookies['access_token']}"}


# --- 9.1 GET /auth/yo ---------------------------------------------------------------------------


async def test_yo_devuelve_usuario_roles_vigentes_y_roles_del_token_sin_hash(http, db_auth, clave):
    uid = await db_auth.crear_usuario(EMAIL, clave, roles=["ADMIN", "CLIENTE"], nombre="Ana Pérez")
    await entrar(http, EMAIL, clave)
    r = await http.get("/auth/yo")
    assert r.status_code == 200
    assert r.json() == {
        "id": uid,
        "email": EMAIL,
        "nombre": "Ana Pérez",
        "debe_cambiar_password": False,
        "roles_vigentes": ["ADMIN", "CLIENTE"],
        "roles_token": ["ADMIN", "CLIENTE"],
    }
    assert "password_hash" not in r.text and "$2b$" not in r.text and clave not in r.text


async def test_yo_tras_revocar_un_rol_en_la_base_los_vigentes_cambian_y_los_del_token_no(http, db_auth, clave):
    uid = await db_auth.crear_usuario(EMAIL, clave, roles=["ADMIN", "CLIENTE"])
    await entrar(http, EMAIL, clave)
    await db_auth.ejecutar(
        "UPDATE asignacion_rol SET revocada_en = now() WHERE usuario_id = :i AND rol = 'ADMIN'", i=uid
    )
    cuerpo = (await http.get("/auth/yo")).json()
    assert cuerpo["roles_vigentes"] == ["CLIENTE"]
    assert cuerpo["roles_token"] == ["ADMIN", "CLIENTE"]


async def test_yo_un_rol_vencido_no_figura_entre_los_vigentes(http, db_auth, clave):
    uid = await db_auth.crear_usuario(EMAIL, clave, roles=["CLIENTE"])
    await db_auth.asignar_rol(uid, "MECANICO", vence_en=datetime.now(UTC) - timedelta(minutes=1))
    await entrar(http, EMAIL, clave)
    assert (await http.get("/auth/yo")).json()["roles_vigentes"] == ["CLIENTE"]


async def test_yo_con_cambio_pendiente_200_y_lo_informa(http, db_auth, clave):
    await db_auth.crear_usuario(EMAIL, clave, debe_cambiar_password=True)
    await entrar(http, EMAIL, clave)
    r = await http.get("/auth/yo")
    assert r.status_code == 200
    assert r.json()["debe_cambiar_password"] is True


async def test_yo_sin_cookie_401_con_mensaje_propio(http):
    r = await http.get("/auth/yo")
    assert (r.status_code, r.json()) == (401, SIN_SESION)


async def test_yo_con_usuario_desactivado_y_misma_cookie_pasa_a_401(http, db_auth, clave):
    uid = await db_auth.crear_usuario(EMAIL, clave)
    await entrar(http, EMAIL, clave)
    await db_auth.ejecutar("UPDATE usuario SET activo = false WHERE id = :i", i=uid)
    assert (await http.get("/auth/yo")).status_code == 401


async def test_yo_ignora_authorization_bearer_sin_cookie(http, db_auth, clave, fabrica_http):
    await db_auth.crear_usuario(EMAIL, clave)
    await entrar(http, EMAIL, clave)
    token = http.cookies["access_token"]
    otro = fabrica_http("198.51.100.8")
    r = await otro.get("/auth/yo", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


async def test_registro_y_luego_login_muestran_el_rol_cliente_y_nunca_el_hash(http, db_auth, clave):
    cuerpo = {"email": EMAIL, "password": clave, "nombre": "Ana", "documento": "30111222", "telefono": "381"}
    registro = await http.post("/auth/registro", json=cuerpo)
    await entrar(http, EMAIL, clave)
    yo = await http.get("/auth/yo")
    assert yo.json()["roles_vigentes"] == ["CLIENTE"]
    for r in (registro, yo):
        assert "password_hash" not in r.text and clave not in r.text and "$2b$" not in r.text


async def test_yo_y_logout_encadenados_cierran_la_sesion(http, db_auth, clave):
    await db_auth.crear_usuario(EMAIL, clave)
    await entrar(http, EMAIL, clave)
    assert (await http.get("/auth/yo")).status_code == 200
    assert (await http.post("/auth/logout")).status_code == 200
    r = await http.get("/auth/yo")
    assert (r.status_code, r.json()) == (401, SIN_SESION)


# --- 9.3 cambio exitoso --------------------------------------------------------------------------


async def test_cambio_exitoso_200_cookie_nueva_y_efectos_en_la_base(http, db_auth, clave, clave_nueva):
    await db_auth.crear_usuario(EMAIL, clave, debe_cambiar_password=True)
    await entrar(http, EMAIL, clave)
    antes = (await db_auth.filas("SELECT password_hash FROM usuario"))[0]["password_hash"]
    r = await http.post(
        "/auth/cambiar-password", json={"password_actual": clave, "password_nueva": clave_nueva}
    )
    assert r.status_code == 200
    assert r.json() == {"mensaje": "Contraseña actualizada"}
    assert r.headers["set-cookie"].startswith("access_token=")
    assert "HttpOnly" in r.headers["set-cookie"]

    (usuario,) = await db_auth.filas("SELECT * FROM usuario")
    assert usuario["password_hash"] != antes and usuario["password_hash"].startswith("$2b$04$")
    assert usuario["password_cambiada_en"] is not None
    assert usuario["debe_cambiar_password"] is False
    (evento,) = await db_auth.filas("SELECT actor, accion FROM evento_seguridad")
    assert evento == {"actor": EMAIL, "accion": "Cambio de contraseña"}


async def test_tras_el_cambio_la_vieja_da_401_y_la_nueva_200(http, fabrica_http, db_auth, clave, clave_nueva):
    await db_auth.crear_usuario(EMAIL, clave)
    await entrar(http, EMAIL, clave)
    await http.post("/auth/cambiar-password", json={"password_actual": clave, "password_nueva": clave_nueva})
    otro = fabrica_http("198.51.100.20")
    assert (await otro.post("/auth/login", json=login(EMAIL, clave))).status_code == 401
    assert (await otro.post("/auth/login", json=login(EMAIL, clave_nueva))).status_code == 200


async def test_cambio_con_nueva_igual_a_la_actual_se_acepta(http, db_auth, clave):
    # SU-C05-8: no se exige que la nueva difiera de la actual.
    await db_auth.crear_usuario(EMAIL, clave)
    await entrar(http, EMAIL, clave)
    r = await http.post("/auth/cambiar-password", json={"password_actual": clave, "password_nueva": clave})
    assert r.status_code == 200


# --- 9.5 RN-07 (C-09) ------------------------------------------------------------------------------


async def test_login_y_cambio_inmediatos_invalidan_la_cookie_vieja_y_la_nueva_vale(
    http, db_auth, clave, clave_nueva
):
    await db_auth.crear_usuario(EMAIL, clave)
    await entrar(http, EMAIL, clave)
    vieja = cabecera_cookie(http)
    r = await http.post("/auth/cambiar-password", json={"password_actual": clave, "password_nueva": clave_nueva})
    nueva = cabecera_cookie(http)
    assert r.status_code == 200 and vieja != nueva
    assert (await http.get("/auth/yo", headers=vieja)).status_code == 401
    assert (await http.get("/auth/yo", headers=nueva)).status_code == 200


async def test_dos_sesiones_abiertas_el_cambio_desde_una_invalida_la_otra(
    http, fabrica_http, db_auth, clave, clave_nueva
):
    await db_auth.crear_usuario(EMAIL, clave)
    segunda = fabrica_http("198.51.100.30")
    await entrar(http, EMAIL, clave)
    await entrar(segunda, EMAIL, clave)
    await http.post("/auth/cambiar-password", json={"password_actual": clave, "password_nueva": clave_nueva})
    assert (await segunda.get("/auth/yo")).status_code == 401
    assert (await http.get("/auth/yo")).status_code == 200


async def test_password_actual_incorrecta_401_sin_cambios(http, db_auth, clave, clave_nueva):
    await db_auth.crear_usuario(EMAIL, clave)
    await entrar(http, EMAIL, clave)
    antes = await db_auth.filas("SELECT password_hash, password_cambiada_en FROM usuario")
    r = await http.post(
        "/auth/cambiar-password", json={"password_actual": "no-es-la-actual", "password_nueva": clave_nueva}
    )
    assert (r.status_code, r.json()) == (401, {"detail": "La contraseña actual no es correcta"})
    assert "set-cookie" not in r.headers
    assert await db_auth.filas("SELECT password_hash, password_cambiada_en FROM usuario") == antes
    assert await db_auth.contar("evento_seguridad") == 0
    assert (await http.get("/auth/yo")).status_code == 200  # la sesion sigue valida


async def test_cambiar_password_sin_cookie_401(http, clave_nueva):
    r = await http.post("/auth/cambiar-password", json={"password_actual": "x", "password_nueva": clave_nueva})
    assert (r.status_code, r.json()) == (401, SIN_SESION)


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"password_actual": "x", "password_nueva": "a" * 7},
        {"password_actual": "x", "password_nueva": "ñ" * 37},
        {"password_actual": "ñ" * 37, "password_nueva": "valida-12345"},
        {"password_actual": "", "password_nueva": "valida-12345"},
        {"password_actual": "x", "password_nueva": "valida-12345", "extra": 1},
        {"password_actual": "x"},
    ],
)
async def test_cambio_con_contrato_invalido_422_sin_tocar_nada(http, db_auth, clave, cuerpo):
    await db_auth.crear_usuario(EMAIL, clave)
    await entrar(http, EMAIL, clave)
    antes = await db_auth.filas("SELECT password_hash FROM usuario")
    r = await http.post("/auth/cambiar-password", json=cuerpo)
    assert r.status_code == 422
    assert await db_auth.filas("SELECT password_hash FROM usuario") == antes


async def test_el_hash_del_cambio_se_calcula_fuera_de_transaccion(http, app_auth, db_auth, clave, clave_nueva, monkeypatch):
    # Entre la lectura y la escritura no puede haber una transaccion abierta durante bcrypt:
    # el ultimo evento antes de cada bcrypt debe ser un COMMIT/ROLLBACK de la conexion.
    from sqlalchemy import event

    await db_auth.crear_usuario(EMAIL, clave)
    await entrar(http, EMAIL, clave)
    motor = app_auth.state.engine.sync_engine
    eventos: list[str] = []
    event.listen(motor, "commit", lambda c: eventos.append("commit"))
    event.listen(motor, "rollback", lambda c: eventos.append("rollback"))
    servicio = app_auth.state.contrasenas
    real_v, real_h = servicio.verificar, servicio.hashear

    async def verificar(p, h):
        eventos.append("bcrypt")
        return await real_v(p, h)

    async def hashear(p):
        eventos.append("bcrypt")
        return await real_h(p)

    monkeypatch.setattr(servicio, "verificar", verificar)
    monkeypatch.setattr(servicio, "hashear", hashear)
    r = await http.post("/auth/cambiar-password", json={"password_actual": clave, "password_nueva": clave_nueva})
    assert r.status_code == 200
    for i, e in enumerate(eventos):
        if e == "bcrypt":
            previos = [x for x in eventos[:i] if x != "bcrypt"]
            assert previos and previos[-1] in ("commit", "rollback"), eventos


# --- 9.6 bloqueo / desbloqueo (C-09) --------------------------------------------------------------


async def test_cambio_pendiente_bloquea_la_ruta_protegida_pero_no_auth_ni_salud(http, db_auth, clave):
    await db_auth.crear_usuario(EMAIL, clave, roles=["ADMIN"], debe_cambiar_password=True)
    await entrar(http, EMAIL, clave)
    r = await http.get("/prueba/admin")
    assert (r.status_code, r.json()) == (403, {"detail": "Debe cambiar la contraseña antes de continuar"})
    assert (await http.get("/prueba/protegida")).status_code == 403
    assert (await http.get("/auth/yo")).status_code == 200
    assert (await http.get("/health/live")).status_code == 200
    r = await http.post("/auth/cambiar-password", json={"password_actual": "mala", "password_nueva": "valida-12345"})
    assert r.status_code == 401  # llego al servicio: no es 403


async def test_tras_el_cambio_con_la_cookie_nueva_la_ruta_protegida_corre(
    http, db_auth, clave, clave_nueva, ejecuciones_prueba
):
    await db_auth.crear_usuario(EMAIL, clave, roles=["ADMIN"], debe_cambiar_password=True)
    await entrar(http, EMAIL, clave)
    assert (await http.get("/prueba/admin")).status_code == 403
    r = await http.post("/auth/cambiar-password", json={"password_actual": clave, "password_nueva": clave_nueva})
    assert r.status_code == 200
    assert (await http.get("/prueba/admin")).status_code == 200
    assert ejecuciones_prueba["admin"] == 1
