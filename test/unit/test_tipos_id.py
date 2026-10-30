"""Tipo compartido de id de ruta (C-12, D12): rango BIGINT para que PostgreSQL nunca reciba un id inexistente en su tipo."""
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.tipos import MAX_ID, MIN_ID, IdRuta

pytestmark = pytest.mark.unit

RAIZ = Path(__file__).resolve().parents[2]
ROUTERS = sorted((RAIZ / "app" / "modules").glob("*/router.py"))


@pytest.fixture
def cliente():
    app = FastAPI()

    @app.get("/cosas/{cosa_id}")
    def cosa(cosa_id: IdRuta) -> dict[str, int]:
        return {"id": cosa_id}

    return TestClient(app)


def test_los_limites_son_los_de_bigint():
    assert (MIN_ID, MAX_ID) == (-(2**63), 2**63 - 1)


@pytest.mark.parametrize("valor", [MAX_ID + 1, MIN_ID - 1, 10**25])
def test_fuera_de_rango_bigint_da_422(cliente, valor):
    assert cliente.get(f"/cosas/{valor}").status_code == 422


@pytest.mark.parametrize("valor", [MAX_ID, MIN_ID, 0, -1, 7])
def test_dentro_de_rango_llega_al_handler_sin_cambiar_el_valor(cliente, valor):
    respuesta = cliente.get(f"/cosas/{valor}")

    assert respuesta.status_code == 200
    assert respuesta.json() == {"id": valor}


def test_no_numerico_sigue_dando_422(cliente):
    assert cliente.get("/cosas/abc").status_code == 422


@pytest.mark.parametrize("router", ROUTERS, ids=lambda p: p.parent.name)
def test_ningun_router_declara_ids_de_ruta_como_int_sin_cota(router):
    texto = router.read_text(encoding="utf-8")
    assert re.findall(r"\b\w+_id: int\b", texto) == []
