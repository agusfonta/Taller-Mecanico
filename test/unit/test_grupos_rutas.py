"""Dos grupos de rutas: abierto y protegido con control montado una vez (D2, D3)."""
import importlib

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit


@pytest.fixture
def main_mod(secretos_validos):
    import main

    return importlib.reload(main)


@pytest.fixture
def dependencies_mod(main_mod):
    from app.core import dependencies

    return dependencies


@pytest.fixture
def ejecuciones():
    return {"abierta": 0, "protegida": 0}


@pytest.fixture
def app_prueba(main_mod, ejecuciones):
    abierto = APIRouter()
    protegido = APIRouter()

    @abierto.get("/abierta")
    async def abierta():
        ejecuciones["abierta"] += 1
        return {"ok": True}

    @protegido.get("/protegida")
    async def protegida():
        ejecuciones["protegida"] += 1
        return {"ok": True}

    return main_mod.crear_app(abiertos=[abierto], protegidos=[protegido])


def test_ruta_abierta_responde_sin_control(app_prueba, ejecuciones):
    r = TestClient(app_prueba).get("/abierta")
    assert r.status_code == 200
    assert ejecuciones["abierta"] == 1


def test_ruta_protegida_falla_cerrada_con_401_y_no_ejecuta(app_prueba, ejecuciones):
    r = TestClient(app_prueba).get("/protegida")
    assert r.status_code == 401
    assert r.json() == {"detail": "Se requiere iniciar sesión"}
    assert "Traceback" not in r.text
    assert ejecuciones["protegida"] == 0


def test_control_del_grupo_protegido_corre_exactamente_una_vez(
    app_prueba, dependencies_mod, ejecuciones
):
    llamadas = []

    async def control_falso():
        llamadas.append(1)

    app_prueba.dependency_overrides[dependencies_mod.exigir_acceso] = control_falso
    cliente = TestClient(app_prueba)
    assert cliente.get("/protegida").status_code == 200
    assert len(llamadas) == 1
    assert ejecuciones["protegida"] == 1


def test_ruta_abierta_no_invoca_el_control(app_prueba, dependencies_mod):
    llamadas = []

    async def control_falso():
        llamadas.append(1)

    app_prueba.dependency_overrides[dependencies_mod.exigir_acceso] = control_falso
    assert TestClient(app_prueba).get("/abierta").status_code == 200
    assert llamadas == []


def test_crear_app_registra_handler_422_de_pagina_fuera_de_rango(main_mod):
    from app.core.paginacion import PaginaFueraDeRangoError

    router = APIRouter()

    @router.get("/fuera")
    async def fuera():
        raise PaginaFueraDeRangoError

    app = main_mod.crear_app(abiertos=[router])
    r = TestClient(app).get("/fuera")
    assert r.status_code == 422
    assert r.json() == {"detail": "La página solicitada no existe"}


def test_app_por_defecto_no_tiene_rutas_de_negocio(main_mod):
    rutas = {getattr(r, "path", "") for r in main_mod.app.routes}
    assert "/abierta" not in rutas and "/protegida" not in rutas
