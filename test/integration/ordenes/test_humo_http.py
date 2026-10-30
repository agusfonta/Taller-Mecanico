"""Humo de la infraestructura HTTP de ordenes (C-09, tarea 6.1)."""
import pytest

pytestmark = pytest.mark.integration


async def test_estados_orden_sin_cookie_es_401(http):
    assert (await http.get("/estados-orden")).status_code == 401


async def test_el_override_monta_ordenes_y_repuestos_en_el_grupo_protegido(http):
    for ruta in ("/ordenes", "/ordenes/1", "/mis-ordenes", "/repuestos"):
        assert (await http.get(ruta)).status_code == 401
