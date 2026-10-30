"""Permisos de las rutas de C-06: solo ADMIN, en el orden 401 -> 403 -> 422 (tareas 4.1 y 4.2)."""
import pytest

from test.integration.sesiones import admin_con_sesion, usuario_con_sesion

pytestmark = pytest.mark.integration

SIN_PERMISO = {"detail": "No tiene permiso para esta operación"}
SIN_SESION = {"detail": "Se requiere iniciar sesión"}
CAMBIO_PENDIENTE = {"detail": "Debe cambiar la contraseña antes de continuar"}

RUTAS = [
    ("POST", "/usuarios"),
    ("GET", "/usuarios/1/roles"),
    ("POST", "/usuarios/1/roles"),
    ("DELETE", "/usuarios/1/roles/MECANICO"),
    ("GET", "/eventos"),
]


async def test_ayudante_admin_con_sesion_devuelve_cliente_con_admin_vigente(db_auth, fabrica_http):
    uid, http = await admin_con_sesion(db_auth, fabrica_http, "admin@taller.com")
    r = await http.get("/auth/yo")
    assert r.status_code == 200
    assert r.json()["id"] == uid and r.json()["roles_vigentes"] == ["ADMIN"]


@pytest.mark.parametrize(("metodo", "ruta"), RUTAS)
async def test_sin_cookie_todas_las_rutas_dan_401(http, metodo, ruta):
    r = await http.request(metodo, ruta)
    assert r.status_code == 401
    assert r.json() == SIN_SESION


@pytest.mark.parametrize("rol", ["CLIENTE", "RECEPCION", "MECANICO"])
@pytest.mark.parametrize(("metodo", "ruta"), RUTAS)
async def test_sin_rol_admin_todas_las_rutas_dan_403(db_auth, fabrica_http, rol, metodo, ruta):
    _, http, _ = await usuario_con_sesion(db_auth, fabrica_http, f"{rol.lower()}@taller.com", roles=(rol,))
    r = await http.request(metodo, ruta)
    assert r.status_code == 403
    assert r.json() == SIN_PERMISO


@pytest.mark.parametrize(("metodo", "ruta"), RUTAS)
async def test_admin_con_cambio_pendiente_recibe_403_de_cambio_pendiente(db_auth, fabrica_http, metodo, ruta):
    _, http, _ = await usuario_con_sesion(
        db_auth, fabrica_http, "admin@taller.com", roles=("ADMIN",), debe_cambiar_password=True
    )
    r = await http.request(metodo, ruta)
    assert r.status_code == 403
    assert r.json() == CAMBIO_PENDIENTE


async def test_no_admin_con_cuerpo_invalido_recibe_403_no_422_y_no_se_calcula_ningun_hash(
    db_auth, fabrica_http, app_auth, monkeypatch
):
    _, http, _ = await usuario_con_sesion(db_auth, fabrica_http, "rec@taller.com", roles=("RECEPCION",))
    llamadas = []
    original = app_auth.state.contrasenas.hashear

    async def espia(password):
        llamadas.append(password)
        return await original(password)

    monkeypatch.setattr(app_auth.state.contrasenas, "hashear", espia)
    invalidos = [
        ("POST", "/usuarios", {"email": "no-es-correo", "password": "1", "rol": "CLIENTE", "x": 1}),
        ("POST", "/usuarios/1/roles", {"rol": "JEFE", "vence_en": "2020-01-01T00:00:00"}),
        ("POST", "/usuarios/abc/roles", {}),
        ("DELETE", "/usuarios/abc/roles/JEFE", None),
    ]
    for metodo, ruta, cuerpo in invalidos:
        r = await http.request(metodo, ruta, json=cuerpo)
        assert r.status_code == 403, (ruta, r.text)
        assert r.json() == SIN_PERMISO
    r = await http.get("/eventos", params={"size": 500, "page": 0})
    assert r.status_code == 403
    assert llamadas == []


async def test_openapi_publica_las_cinco_rutas_bajo_usuarios_y_eventos(http):
    paths = (await http.get("/openapi.json")).json()["paths"]
    publicadas = {(m.upper(), p, tuple(op.get("tags", []))) for p, ops in paths.items() for m, op in ops.items()}
    esperadas = {
        ("POST", "/usuarios", ("usuarios",)),
        ("GET", "/usuarios/{usuario_id}/roles", ("usuarios",)),
        ("POST", "/usuarios/{usuario_id}/roles", ("usuarios",)),
        ("DELETE", "/usuarios/{usuario_id}/roles/{rol}", ("usuarios",)),
        ("GET", "/eventos", ("eventos",)),
    }
    assert esperadas <= publicadas
