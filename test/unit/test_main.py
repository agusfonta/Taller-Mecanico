"""`main.py` falla rapido sin secretos y carga sin contactar la base (D6)."""
import os
import secrets
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.unit


def _importar_main(tmp_path, extra_env: dict[str, str], codigo="import main"):
    # Entorno minimo: sin variables reconocidas heredadas ni .env (cwd temporal).
    entorno = {
        clave: valor
        for clave, valor in os.environ.items()
        if clave in ("SYSTEMROOT", "PATH", "TEMP", "TMP", "HOME", "USERPROFILE")
    }
    entorno["PYTHONPATH"] = str(RAIZ)
    entorno.update(extra_env)
    return subprocess.run(
        [sys.executable, "-c", codigo],
        cwd=tmp_path,
        env=entorno,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_import_main_sin_jwt_secret_key_falla(tmp_path):
    password = "pw-" + secrets.token_hex(8)
    resultado = _importar_main(tmp_path, {"POSTGRES_PASSWORD": password})
    assert resultado.returncode != 0
    assert "JWT_SECRET_KEY" in resultado.stderr.upper()
    assert password not in resultado.stderr


def test_import_main_sin_postgres_password_falla(tmp_path):
    clave = secrets.token_urlsafe(48)
    resultado = _importar_main(tmp_path, {"JWT_SECRET_KEY": clave})
    assert resultado.returncode != 0
    assert "POSTGRES_PASSWORD" in resultado.stderr.upper()
    assert clave not in resultado.stderr


def test_import_main_con_secretos_y_host_inexistente_carga_sin_contactar_la_base(tmp_path):
    resultado = _importar_main(
        tmp_path,
        {
            "JWT_SECRET_KEY": secrets.token_urlsafe(48),
            "POSTGRES_PASSWORD": "pw-" + secrets.token_hex(8),
            "POSTGRES_HOST": "host-que-no-existe.invalid",
        },
        codigo="import main; from fastapi import FastAPI; assert isinstance(main.app, FastAPI)",
    )
    assert resultado.returncode == 0, resultado.stderr


# --- C-08: rutas de repuestos en el grupo protegido (8.1) ----------------------------------

RUTAS_REPUESTOS = {
    ("post", "/repuestos"),
    ("get", "/repuestos"),
    ("get", "/repuestos/{repuesto_id}"),
    ("patch", "/repuestos/{repuesto_id}"),
    ("delete", "/repuestos/{repuesto_id}"),
    ("post", "/repuestos/{repuesto_id}/reponer"),
    ("get", "/repuestos/{repuesto_id}/movimientos"),
    ("get", "/repuestos/{repuesto_id}/precios"),
}


@pytest.fixture
def main_recargado(secretos_validos):
    import importlib

    import main

    return importlib.reload(main)


def test_main_expone_las_ocho_rutas_de_repuestos(main_recargado):
    esquema = main_recargado.app.openapi()["paths"]
    operaciones = {
        (metodo, ruta)
        for ruta, definicion in esquema.items()
        if ruta.startswith("/repuestos")
        for metodo in definicion
    }
    assert operaciones == RUTAS_REPUESTOS


@pytest.mark.parametrize(("metodo", "ruta"), sorted(RUTAS_REPUESTOS))
def test_las_rutas_de_repuestos_exigen_sesion_sin_lifespan(main_recargado, metodo, ruta):
    from fastapi.testclient import TestClient

    cliente = TestClient(main_recargado.app)  # sin ``with``: no corre el lifespan ni toca la base
    r = cliente.request(metodo.upper(), ruta.format(repuesto_id=1), json={} if metodo in ("post", "patch") else None)
    assert r.status_code == 401


# --- C-09: rutas de ordenes en el grupo protegido (6.6) ------------------------------------

RUTAS_ORDENES = {
    ("post", "/ordenes"),
    ("get", "/ordenes"),
    ("get", "/ordenes/{orden_id}"),
    ("get", "/mis-ordenes"),
    ("get", "/estados-orden"),
    ("post", "/ordenes/{orden_id}/iniciar"),
    ("post", "/ordenes/{orden_id}/terminar"),
    ("post", "/ordenes/{orden_id}/cancelar"),
}


def test_main_expone_las_ocho_rutas_de_ordenes(main_recargado):
    esquema = main_recargado.app.openapi()["paths"]
    operaciones = {
        (metodo, ruta)
        for ruta, definicion in esquema.items()
        if ruta.startswith(("/ordenes", "/mis-ordenes", "/estados-orden"))
        for metodo in definicion
    }
    assert operaciones == RUTAS_ORDENES


@pytest.mark.parametrize(("metodo", "ruta"), sorted(RUTAS_ORDENES))
def test_las_rutas_de_ordenes_pasan_por_el_control_del_grupo_protegido(main_recargado, metodo, ruta):
    from fastapi import HTTPException
    from fastapi.testclient import TestClient

    from app.core.dependencies import exigir_acceso

    async def control_falso():
        raise HTTPException(status_code=418, detail="control del grupo protegido")

    cliente = TestClient(main_recargado.app)  # sin ``with``: no corre el lifespan ni toca la base
    cuerpo = {"json": {}} if metodo == "post" else {}
    url = ruta.format(orden_id=1)
    assert cliente.request(metodo.upper(), url, **cuerpo).status_code == 401  # sin sesion
    cliente.cookies.set("access_token", "x")
    main_recargado.app.dependency_overrides[exigir_acceso] = control_falso
    try:
        # el control del grupo corre ANTES que la autenticacion de la ruta: responde su 418
        r = cliente.request(metodo.upper(), url, **cuerpo)
    finally:
        main_recargado.app.dependency_overrides.clear()
    assert r.status_code == 418



def _rutas_con_dependencias(rutas, heredadas=frozenset()):
    """Recorre ``app.routes`` con routers incluidos anidados (FastAPI 0.162 no los aplana).

    Devuelve ``(ruta, dependencias)``: las del propio route mas las de cada router que lo contiene.
    """
    for ruta in rutas:
        if hasattr(ruta, "original_router"):
            propias = {d.dependency for d in ruta.original_router.dependencies}
            yield from _rutas_con_dependencias(ruta.original_router.routes, heredadas | propias)
        else:
            yield ruta, heredadas | {d.dependency for d in getattr(ruta, "dependencies", ())}


@pytest.mark.parametrize(("metodo", "ruta"), [("POST", "/ordenes"), ("GET", "/ordenes")])
def test_post_y_get_ordenes_declaran_exigir_acceso_en_el_grupo_protegido(main_recargado, metodo, ruta):
    # ``requiere_rol`` tambien depende de ``exigir_acceso``: el override 418 no distingue si lo
    # monta el grupo protegido o solo la ruta; por eso se inspeccionan las dependencias de los
    # routers contenedores (el route de ordenes no declara ``exigir_acceso`` por si mismo).
    from app.core.dependencies import exigir_acceso

    candidatas = [
        (r, deps)
        for r, deps in _rutas_con_dependencias(main_recargado.app.routes)
        if getattr(r, "path", None) == ruta and metodo in getattr(r, "methods", ())
    ]
    assert len(candidatas) == 1
    ruta_encontrada, dependencias = candidatas[0]
    assert exigir_acceso not in {d.dependency for d in ruta_encontrada.dependencies}
    assert exigir_acceso in dependencias


# --- C-10: rutas de transicion en el grupo protegido (8.7) --------------------------------------

RUTAS_TRANSICION = [
    ("POST", "/ordenes/{orden_id}/iniciar", {"MECANICO"}),
    ("POST", "/ordenes/{orden_id}/terminar", {"MECANICO", "ADMIN"}),
    ("POST", "/ordenes/{orden_id}/cancelar", set()),
]


def _roles_de_requiere_rol(ruta):
    """Roles de las dependencias ``requiere_rol`` de la ruta (vacio si no declara ninguna)."""
    roles: set[str] = set()

    def recorrer(dependant):
        for sub in dependant.dependencies:
            llamada = sub.call
            if getattr(llamada, "__qualname__", "").startswith("requiere_rol.<locals>"):
                for celda in llamada.__closure__ or ():
                    if isinstance(celda.cell_contents, frozenset):
                        roles.update(r.value for r in celda.cell_contents)
            recorrer(sub)

    recorrer(ruta.dependant)
    return roles


def _candidatas(main_recargado, metodo, ruta):
    return [
        (r, deps)
        for r, deps in _rutas_con_dependencias(main_recargado.app.routes)
        if getattr(r, "path", None) == ruta and metodo in getattr(r, "methods", ())
    ]


@pytest.mark.parametrize(("metodo", "ruta", "roles"), RUTAS_TRANSICION)
def test_las_rutas_de_transicion_estan_en_el_grupo_protegido_y_declaran_sus_roles(
    main_recargado, metodo, ruta, roles
):
    from app.core.dependencies import exigir_acceso

    candidatas = _candidatas(main_recargado, metodo, ruta)
    assert len(candidatas) == 1  # una sola vez en toda la app
    ruta_encontrada, dependencias = candidatas[0]
    assert exigir_acceso in dependencias  # lo aporta el router contenedor (grupo protegido)
    assert exigir_acceso not in {d.dependency for d in ruta_encontrada.dependencies}
    assert _roles_de_requiere_rol(ruta_encontrada) == roles


@pytest.mark.parametrize(("metodo", "ruta", "roles"), RUTAS_TRANSICION)
def test_las_rutas_de_transicion_no_estan_en_ningun_grupo_abierto(main_recargado, metodo, ruta, roles):
    from app.core.dependencies import exigir_acceso

    sin_control = [
        r
        for r, deps in _rutas_con_dependencias(main_recargado.app.routes)
        if getattr(r, "path", None) == ruta and metodo in getattr(r, "methods", ()) and exigir_acceso not in deps
    ]
    assert sin_control == []


@pytest.mark.parametrize(("metodo", "ruta", "roles"), RUTAS_TRANSICION)
def test_las_rutas_de_transicion_exigen_sesion_sin_lifespan(main_recargado, metodo, ruta, roles):
    from fastapi.testclient import TestClient

    cliente = TestClient(main_recargado.app)
    assert cliente.request(metodo, ruta.format(orden_id=1)).status_code == 401
