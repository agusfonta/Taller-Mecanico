"""Guarda estatica del modulo clientes (C-07, 3.6): ni UoW ni servicio confirman por su cuenta."""
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

RAIZ = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "ruta",
    ["app/modules/clientes/unit_of_work.py", "app/modules/clientes/service.py"],
)
def test_uow_y_servicio_de_clientes_no_confirman_revierten_ni_cierran(ruta):
    fuente = (RAIZ / ruta).read_text(encoding="utf-8")
    assert ".commit(" not in fuente
    assert ".rollback(" not in fuente
    assert ".close(" not in fuente
