"""Modelos SOLO de prueba para los tests de integracion de C-02 (D7).

Viven en un ``registry()`` propio: NO entran en ``SQLModel.metadata`` y el
``--autogenerate`` de C-03 nunca los ve.
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Column, DateTime, Numeric, String, UniqueConstraint
from sqlalchemy.orm import registry
from sqlmodel import Field, SQLModel

__all__ = ["BasePrueba", "ItemPrueba", "ItemBorrable", "ItemPkCompuesta"]


class BasePrueba(SQLModel, registry=registry()):
    """Base declarativa con metadata propia (aislada de la de la app)."""


class ItemPrueba(BasePrueba, table=True):
    __tablename__ = "c02_item_prueba"
    # UNIQUE DEFERRABLE INITIALLY DEFERRED: la violacion ocurre en el COMMIT, no en el flush.
    __table_args__ = (
        UniqueConstraint("nombre", name="uq_c02_item_prueba_nombre", deferrable=True, initially="DEFERRED"),
    )

    id: int | None = Field(default=None, primary_key=True)
    nombre: str = Field(sa_column=Column(String, nullable=False))
    precio: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(10, 2), nullable=False))


class ItemBorrable(BasePrueba, table=True):
    __tablename__ = "c02_item_borrable"

    id: int | None = Field(default=None, primary_key=True)
    nombre: str = Field(sa_column=Column(String, nullable=False))
    borrado_en: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))


class ItemPkCompuesta(BasePrueba, table=True):
    __tablename__ = "c02_item_pk_compuesta"

    a: int = Field(primary_key=True)
    b: int = Field(primary_key=True)
