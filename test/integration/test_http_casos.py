"""Los ``test/c*.http`` se ejecutan de verdad contra la app sobre el seed y cumplen su ``# Esperado`` (C-12, D3)."""
from pathlib import Path

import httpx
import pytest

from test.integration.app_completa import app_auth, contrasenas_seed, fabrica_seed, seed_cargado, sesion_de  # noqa: F401
from test.integration.http_casos import claves_de_prompts, ejecutar, parsear

pytestmark = pytest.mark.integration

ARCHIVOS = sorted((Path(__file__).resolve().parents[1]).glob("c*.http"))


@pytest.mark.parametrize("archivo", ARCHIVOS, ids=lambda p: p.stem)
async def test_cada_pedido_responde_lo_que_dice_su_esperado(archivo, seed_cargado, app_auth):
    doc = parsear(archivo.read_text(encoding="utf-8"))
    transporte = httpx.ASGITransport(app=app_auth, client=("203.0.113.5", 51000))

    async with httpx.AsyncClient(transport=transporte) as cliente:
        resultados = await ejecutar(doc, cliente, claves_de_prompts(doc))

    diferencias = [
        f"{r.pedido.titulo!r}: esperado {r.pedido.esperado}, recibido {r.codigo} -> {r.texto[:200]}"
        for r in resultados
        if r.codigo != r.pedido.esperado
    ]
    assert diferencias == []
