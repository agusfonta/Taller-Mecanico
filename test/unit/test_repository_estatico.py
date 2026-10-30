"""Guardas del repositorio que no necesitan base (D4)."""
from pathlib import Path

import pytest

from app.core.repository import BaseRepository
from test.integration.modelos_prueba import ItemPkCompuesta, ItemPrueba

pytestmark = pytest.mark.unit

RAIZ = Path(__file__).resolve().parents[2]


def test_pk_compuesta_lanza_typeerror():
    with pytest.raises(TypeError):
        BaseRepository(object(), ItemPkCompuesta)


def test_pk_simple_se_acepta():
    assert BaseRepository(object(), ItemPrueba).model is ItemPrueba


def test_fuente_de_repository_no_confirma_ni_cierra():
    fuente = (RAIZ / "app" / "core" / "repository.py").read_text(encoding="utf-8")
    assert ".commit(" not in fuente
    assert ".close(" not in fuente


@pytest.mark.parametrize(
    "ruta",
    [
        "app/modules/usuarios/repository.py",
        "app/modules/clientes/repository.py",
    ],
)
def test_repositorios_de_modulo_no_confirman_ni_cierran(ruta):
    fuente = (RAIZ / ruta).read_text(encoding="utf-8")
    assert ".commit(" not in fuente
    assert ".rollback(" not in fuente
    assert ".close(" not in fuente


def test_uow_de_usuarios_no_cierra_la_sesion_ni_la_confirma_por_su_cuenta():
    fuente = (RAIZ / "app/modules/usuarios/unit_of_work.py").read_text(encoding="utf-8")
    assert ".commit(" not in fuente
    assert ".close(" not in fuente
