"""Usuario actual, control del grupo protegido y ``requiere_rol`` (C-05, D5/D6).

Sin base de datos: la app se arma SIN lifespan (no existe ``app.state.session_factory``), asi que
cualquier intento de abrir una sesion explota. Eso prueba el orden de D5 (token antes que base).
Los casos con usuario usan un UoW falso solo en este archivo unitario; la integracion real
contra PostgreSQL esta en ``test/integration/test_auth_sesion.py``.
"""
import importlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit

SIN_SESION = {"detail": "Se requiere iniciar sesión"}


@pytest.fixture
def main_mod(secretos_validos):
    import main

    return importlib.reload(main)


@pytest.fixture
def seg(main_mod):
    from app.core import security

    return security


@pytest.fixture
def ajustes(main_mod):
    from app.core.config import get_settings

    return get_settings()


@pytest.fixture
def ejecuciones():
    return {"protegida": 0, "admin": 0}


@pytest.fixture
def app_prueba(main_mod, ejecuciones):
    from app.core.dependencies import requiere_rol
    from app.modules.usuarios.models import Rol

    protegido = APIRouter()

    @protegido.get("/protegida")
    async def protegida():
        ejecuciones["protegida"] += 1
        return {"ok": True}

    @protegido.get("/admin", dependencies=[Depends(requiere_rol(Rol.ADMIN))])
    async def admin():
        ejecuciones["admin"] += 1
        return {"ok": True}

    return main_mod.crear_app(protegidos=[protegido])


# --- 6.1 sin cookie / token inválido: 401 sin tocar la base ---------------------------


def test_sin_cookie_401_y_la_ruta_no_corre_sin_tocar_app_state(app_prueba, ejecuciones):
    r = TestClient(app_prueba).get("/protegida")
    assert r.status_code == 401
    assert r.json() == SIN_SESION
    assert ejecuciones["protegida"] == 0


def test_sin_cookie_en_ruta_con_rol_es_401_no_403(app_prueba, ejecuciones):
    r = TestClient(app_prueba).get("/admin")
    assert r.status_code == 401
    assert r.json() == SIN_SESION
    assert ejecuciones["admin"] == 0


@pytest.mark.parametrize("basura", ["no-es-un-jwt", "a.b.c", "x" * 300])
def test_cookie_con_token_invalido_401_sin_tocar_la_base(app_prueba, ejecuciones, basura):
    cliente = TestClient(app_prueba, cookies={"access_token": basura})
    r = cliente.get("/protegida")
    assert r.status_code == 401
    assert r.json() == SIN_SESION
    assert "Traceback" not in r.text
    assert ejecuciones["protegida"] == 0


def test_token_vencido_en_cookie_401_sin_tocar_la_base(app_prueba, seg, ajustes):
    import time

    viejo = seg.emitir_token(7, ["ADMIN"], ajustes, ahora=time.time() - 7200)
    r = TestClient(app_prueba, cookies={"access_token": viejo}).get("/protegida")
    assert r.status_code == 401
    assert r.json() == SIN_SESION


def test_authorization_bearer_valido_sin_cookie_es_401(app_prueba, seg, ajustes):
    token = seg.emitir_token(7, ["ADMIN"], ajustes)
    r = TestClient(app_prueba).get("/protegida", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
    assert r.json() == SIN_SESION


# --- 6.2 / 6.3 con usuario (UoW falso) ---------------------------------------------------


class _Repos:
    def __init__(self, usuario, roles, llamadas):
        self._usuario = usuario
        self._roles = roles
        self._llamadas = llamadas

    async def get_by_id(self, id_):
        self._llamadas["usuario"] += 1
        return self._usuario if self._usuario is not None and self._usuario.id == id_ else None

    async def roles_vigentes(self, usuario_id, ahora):
        self._llamadas["roles"] += 1
        return list(self._roles)


class UoWFalso:
    def __init__(self, usuario, roles):
        self.llamadas = {"usuario": 0, "roles": 0, "entradas": 0}
        repos = _Repos(usuario, roles, self.llamadas)
        self.usuarios = repos
        self.asignaciones = repos

    async def __aenter__(self):
        self.llamadas["entradas"] += 1
        return self

    async def __aexit__(self, *exc):
        return False


def _usuario(**extra):
    base = dict(
        id=7,
        email="ana@example.com",
        nombre="Ana",
        activo=True,
        debe_cambiar_password=False,
        password_cambiada_en=None,
        password_hash="no-se-expone",
    )
    base.update(extra)
    return SimpleNamespace(**base)


@pytest.fixture
def con_usuario(app_prueba, seg, ajustes):
    """Devuelve ``cliente(usuario, roles)``: TestClient con cookie valida del usuario 7 y UoW falso."""
    from app.modules.usuarios.unit_of_work import get_usuarios_uow

    def armar(usuario, roles=(), roles_token=("ADMIN",), iat=None):
        uow = UoWFalso(usuario, roles)
        app_prueba.dependency_overrides[get_usuarios_uow] = lambda: uow
        token = seg.emitir_token(7, roles_token, ajustes, ahora=iat)
        return TestClient(app_prueba, cookies={"access_token": token}), uow

    return armar


def test_usuario_valido_sin_cambio_pendiente_la_ruta_corre_una_vez(con_usuario, ejecuciones):
    from app.modules.usuarios.models import Rol

    cliente, uow = con_usuario(_usuario(), roles=[Rol.CLIENTE])
    assert cliente.get("/protegida").status_code == 200
    assert ejecuciones["protegida"] == 1
    assert uow.llamadas["usuario"] == 1


def test_usuario_inexistente_401(con_usuario, ejecuciones):
    cliente, _ = con_usuario(None)
    r = cliente.get("/protegida")
    assert (r.status_code, r.json()) == (401, SIN_SESION)
    assert ejecuciones["protegida"] == 0


def test_usuario_inactivo_401(con_usuario, ejecuciones):
    cliente, _ = con_usuario(_usuario(activo=False))
    r = cliente.get("/protegida")
    assert (r.status_code, r.json()) == (401, SIN_SESION)
    assert ejecuciones["protegida"] == 0


def test_token_anterior_al_cambio_de_password_por_un_microsegundo_401(con_usuario):
    iat = 1_700_000_000.250000
    cambio = datetime.fromtimestamp(iat, UTC) + timedelta(microseconds=1)
    cliente, _ = con_usuario(_usuario(password_cambiada_en=cambio), iat=iat)
    assert cliente.get("/protegida").status_code == 401


def test_token_igual_o_posterior_al_cambio_de_password_pasa(con_usuario):
    import time

    ahora = time.time()
    cambio = datetime.fromtimestamp(ahora, UTC)
    cliente, _ = con_usuario(_usuario(password_cambiada_en=cambio), iat=ahora)
    assert cliente.get("/protegida").status_code == 200
    cliente, _ = con_usuario(_usuario(password_cambiada_en=cambio - timedelta(milliseconds=1)), iat=ahora)
    assert cliente.get("/protegida").status_code == 200


def test_cambio_pendiente_403_con_mensaje_propio_y_la_ruta_no_corre(con_usuario, ejecuciones):
    from app.modules.usuarios.models import Rol

    cliente, _ = con_usuario(_usuario(debe_cambiar_password=True), roles=[Rol.ADMIN])
    r = cliente.get("/protegida")
    assert r.status_code == 403
    assert r.json() == {"detail": "Debe cambiar la contraseña antes de continuar"}
    assert ejecuciones["protegida"] == 0


def test_cambio_pendiente_se_evalua_antes_que_el_rol(con_usuario, ejecuciones):
    from app.modules.usuarios.models import Rol

    # Con ADMIN y cambio pendiente: 403 por cambio pendiente (no pasa a la ruta).
    cliente, _ = con_usuario(_usuario(debe_cambiar_password=True), roles=[Rol.ADMIN])
    r = cliente.get("/admin")
    assert r.json() == {"detail": "Debe cambiar la contraseña antes de continuar"}
    # Sin ADMIN y con cambio pendiente: sigue siendo el de cambio pendiente, no el de rol.
    cliente, _ = con_usuario(_usuario(debe_cambiar_password=True), roles=[Rol.CLIENTE])
    r = cliente.get("/admin")
    assert r.json() == {"detail": "Debe cambiar la contraseña antes de continuar"}
    assert ejecuciones["admin"] == 0


def test_requiere_rol_con_admin_vigente_corre(con_usuario, ejecuciones):
    from app.modules.usuarios.models import Rol

    cliente, uow = con_usuario(_usuario(), roles=[Rol.ADMIN])
    assert cliente.get("/admin").status_code == 200
    assert ejecuciones["admin"] == 1
    assert uow.llamadas["usuario"] == 1  # el usuario se resuelve una sola vez por peticion


def test_requiere_rol_solo_cliente_403_con_mensaje_propio(con_usuario, ejecuciones):
    from app.modules.usuarios.models import Rol

    cliente, _ = con_usuario(_usuario(), roles=[Rol.CLIENTE])
    r = cliente.get("/admin")
    assert r.status_code == 403
    assert r.json() == {"detail": "No tiene permiso para esta operación"}
    assert ejecuciones["admin"] == 0


def test_los_roles_del_token_no_otorgan_permisos(con_usuario, ejecuciones):
    from app.modules.usuarios.models import Rol

    # El token dice ADMIN, la base solo CLIENTE: manda la base (DD-01).
    cliente, _ = con_usuario(_usuario(), roles=[Rol.CLIENTE], roles_token=("ADMIN",))
    assert cliente.get("/admin").status_code == 403


def test_los_roles_del_token_no_quitan_permisos(con_usuario, ejecuciones):
    from app.modules.usuarios.models import Rol

    cliente, _ = con_usuario(_usuario(), roles=[Rol.ADMIN], roles_token=())
    assert cliente.get("/admin").status_code == 200


def test_requiere_rol_acepta_cualquiera_de_varios(main_mod, con_usuario):
    from app.core.dependencies import requiere_rol
    from app.modules.usuarios.models import Rol

    router = APIRouter()

    @router.get("/varios", dependencies=[Depends(requiere_rol(Rol.ADMIN, Rol.RECEPCION))])
    async def varios():
        return {"ok": True}

    app = main_mod.crear_app(protegidos=[router])
    from app.modules.usuarios.unit_of_work import get_usuarios_uow

    uow = UoWFalso(_usuario(), [Rol.RECEPCION])
    app.dependency_overrides[get_usuarios_uow] = lambda: uow
    from app.core.config import get_settings
    from app.core.security import emitir_token

    token = emitir_token(7, [], get_settings())
    assert TestClient(app, cookies={"access_token": token}).get("/varios").status_code == 200


def test_requiere_rol_sin_roles_falla_al_declararse():
    from app.core.dependencies import requiere_rol

    with pytest.raises(ValueError):
        requiere_rol()


def test_requiere_rol_con_texto_que_no_es_rol_falla_al_declararse():
    from app.core.dependencies import requiere_rol

    with pytest.raises(TypeError):
        requiere_rol("ADMIN")


def test_usuario_actual_es_inmutable_y_no_tiene_hash(main_mod):
    import dataclasses

    from app.core.dependencies import UsuarioActual

    assert "password_hash" not in {f.name for f in dataclasses.fields(UsuarioActual)}
    u = UsuarioActual(
        id=1, email="a@b.c", nombre="n", debe_cambiar_password=False,
        roles_vigentes=frozenset(), roles_token=(),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        u.id = 2  # type: ignore[misc]
