"""Dependencia HTTP de paginacion y traduccion de pagina fuera de rango (D6)."""
import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.core.paginacion import PaginacionDep, PaginaFueraDeRangoError

pytestmark = pytest.mark.unit


@pytest.fixture
def cliente(secretos_validos):
    import main

    router = APIRouter()

    @router.get("/lista")
    async def lista(params: PaginacionDep):
        return {"page": params.page, "size": params.size, "offset": params.offset}

    @router.get("/fuera")
    async def fuera(params: PaginacionDep):
        raise PaginaFueraDeRangoError

    # El handler 422 lo registra la fabrica de la app.
    return TestClient(main.crear_app(abiertos=[router]), raise_server_exceptions=False)


def test_sin_parametros_usa_defecto(cliente):
    r = cliente.get("/lista")
    assert r.status_code == 200
    assert r.json() == {"page": 1, "size": 20, "offset": 0}


def test_valores_validos_se_respetan(cliente):
    r = cliente.get("/lista", params={"page": 3, "size": 100})
    assert r.json() == {"page": 3, "size": 100, "offset": 200}


@pytest.mark.parametrize(
    "params",
    [{"size": 0}, {"size": 101}, {"size": 500}, {"page": 0}, {"page": "abc"}, {"size": "x"}],
)
def test_parametros_invalidos_dan_422(cliente, params):
    assert cliente.get("/lista", params=params).status_code == 422


def test_pagina_fuera_de_rango_422_con_detail_propio_sin_traza(cliente):
    r = cliente.get("/fuera")
    assert r.status_code == 422
    assert r.json() == {"detail": "La página solicitada no existe"}
    assert "Traceback" not in r.text
