"""Contratos de ordenes de trabajo (C-09, D4/D10), separados de los modelos de tabla.

Entradas con ``extra="forbid"``: ``precio_unitario``, ``total``, ``estado``, ``mecanico_id``, etc.
los decide el servidor, nunca el cliente. Dinero: ``Decimal`` en todas las capas y CADENA con 2
decimales en la salida JSON (``Dinero``).
"""
from datetime import datetime
from typing import Annotated, Self

from pydantic import (
    AliasPath,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StringConstraints,
    computed_field,
    model_validator,
)

from app.modules.repuestos.schemas import Dinero

__all__ = [
    "EstadoOrdenRespuesta",
    "HistorialRespuesta",
    "ItemAlta",
    "ItemRespuesta",
    "MAX_ITEMS",
    "OrdenAlta",
    "OrdenDetalle",
    "OrdenResumen",
]

MAX_ITEMS = 50
_MAX_BIGINT = 2**63 - 1

_IdBigint = Annotated[StrictInt, Field(ge=1, le=_MAX_BIGINT)]
_Falla = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class _Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ItemAlta(_Entrada):
    repuesto_id: _IdBigint
    cantidad: Annotated[StrictInt, Field(ge=1, le=1000)]


class OrdenAlta(_Entrada):
    vehiculo_id: _IdBigint
    falla: _Falla
    items: Annotated[list[ItemAlta], Field(min_length=1, max_length=MAX_ITEMS)]

    @model_validator(mode="after")
    def _sin_repuestos_repetidos(self) -> Self:
        ids = [i.repuesto_id for i in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Hay repuestos repetidos en los ítems")
        return self


class _Salida(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ItemRespuesta(_Salida):
    id: int
    repuesto_id: int
    codigo: str = Field(validation_alias=AliasPath("repuesto", "codigo"))
    descripcion: str = Field(validation_alias=AliasPath("repuesto", "descripcion"))
    cantidad: int
    precio_unitario: Dinero

    @computed_field  # type: ignore[prop-decorator]
    @property
    def subtotal(self) -> Dinero:
        return self.cantidad * self.precio_unitario


class HistorialRespuesta(_Salida):
    id: int
    desde_estado: str | None
    hasta_estado: str
    usuario_id: int
    cuando: datetime


class OrdenResumen(_Salida):
    id: int
    vehiculo_id: int
    mecanico_id: int | None
    estado: str
    falla: str
    creada_en: datetime
    total: Dinero


class OrdenDetalle(OrdenResumen):
    items: list[ItemRespuesta]
    historial: list[HistorialRespuesta]


class EstadoOrdenRespuesta(_Salida):
    codigo: str
    descripcion: str
    posicion: int
    es_final: bool

