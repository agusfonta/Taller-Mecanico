"""Los modelos de integracion no contaminan la metadata de la app (D7)."""
import pytest
from sqlmodel import SQLModel

from test.integration.modelos_prueba import BasePrueba, ItemBorrable, ItemPrueba

pytestmark = pytest.mark.unit

NOMBRES = {"c02_item_prueba", "c02_item_borrable", "c02_item_pk_compuesta"}


def test_sqlmodel_metadata_no_contiene_las_tablas_de_prueba():
    assert NOMBRES.isdisjoint(SQLModel.metadata.tables)


def test_base_prueba_metadata_contiene_solo_las_tablas_de_prueba():
    assert set(BasePrueba.metadata.tables) == NOMBRES
    assert BasePrueba.metadata is not SQLModel.metadata


def test_restriccion_unique_es_diferida():
    unique = next(
        c for c in ItemPrueba.__table__.constraints if c.name == "uq_c02_item_prueba_nombre"
    )
    assert unique.deferrable is True and unique.initially == "DEFERRED"


def test_borrado_en_es_timestamptz_nullable():
    col = ItemBorrable.__table__.c.borrado_en
    assert col.nullable is True and col.type.timezone is True
