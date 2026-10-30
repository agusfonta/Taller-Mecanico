"""Aviso al cliente en segundo plano (C-10, D7, spec aviso-cliente)."""
import inspect
import logging
from unittest.mock import AsyncMock

import pytest

from app.modules.ordenes import avisos
from app.modules.ordenes.avisos import DEMORA_AVISO, avisar_cliente

pytestmark = pytest.mark.unit

LOGGER = "app.modules.ordenes.avisos"


@pytest.fixture
def dormir(monkeypatch):
    espia = AsyncMock()
    monkeypatch.setattr(avisos.asyncio, "sleep", espia)
    return espia


def test_la_demora_es_medio_segundo():
    assert DEMORA_AVISO == 0.5


def test_avisar_cliente_es_una_corrutina_y_no_bloquea():
    assert inspect.iscoroutinefunction(avisar_cliente)
    assert "time.sleep" not in inspect.getsource(avisos)


@pytest.mark.parametrize(("cliente", "orden"), [(5, 2), (11, 40)])
async def test_espera_la_demora_y_registra_un_unico_info_exacto(dormir, caplog, cliente, orden):
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    assert await avisar_cliente(cliente, orden) is None
    dormir.assert_awaited_once_with(0.5)
    registros = [r for r in caplog.records if r.name == LOGGER]
    assert len(registros) == 1
    assert registros[0].levelno == logging.INFO
    assert registros[0].getMessage() == f"Aviso a cliente {cliente}: orden {orden} terminada"


async def test_el_aviso_se_registra_despues_de_la_espera(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    vistos_al_dormir: list[int] = []

    async def dormir_y_mirar(segundos):
        vistos_al_dormir.append(len([r for r in caplog.records if r.name == LOGGER]))

    monkeypatch.setattr(avisos.asyncio, "sleep", dormir_y_mirar)
    await avisar_cliente(1, 1)
    assert vistos_al_dormir == [0]  # al dormir todavia no habia aviso
    assert len([r for r in caplog.records if r.name == LOGGER]) == 1


@pytest.mark.parametrize("error", [RuntimeError("falla"), OSError("disco")])
async def test_una_excepcion_interna_se_registra_con_traza_y_no_se_propaga(monkeypatch, caplog, error):
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    monkeypatch.setattr(avisos.asyncio, "sleep", AsyncMock(side_effect=error))
    assert await avisar_cliente(5, 2) is None
    registros = [r for r in caplog.records if r.name == LOGGER]
    assert len(registros) == 1 and registros[0].levelno == logging.ERROR
    assert registros[0].exc_info is not None and registros[0].exc_info[1] is error
    assert "terminada" not in registros[0].getMessage()
