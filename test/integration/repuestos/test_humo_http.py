"""Humo de la infraestructura HTTP de repuestos (C-08, 5.1)."""
import pytest

pytestmark = pytest.mark.integration


async def test_sin_cookie_la_ruta_de_repuestos_responde_401(http):
    r = await http.get("/repuestos")
    assert r.status_code == 401


async def test_el_override_monta_solo_lo_declarado(app_auth):
    rutas = set(app_auth.openapi()["paths"])
    assert "/repuestos" in rutas and "/health/live" in rutas
    assert not any(p.startswith("/clientes") for p in rutas)
