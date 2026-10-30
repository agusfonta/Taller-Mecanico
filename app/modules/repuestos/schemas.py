"""Contratos de repuestos (C-08, D2/D3), separados de los modelos de tabla.

Dinero: ``Decimal`` en todas las capas. En la entrada se acepta un numero JSON o una cadena
numerica (``> 0``, a lo sumo 2 decimales, a lo sumo 99999999.99: replica ``NUMERIC(10,2)`` para
que nada llegue a la base como ``DataError``). En la salida se emite SIEMPRE una CADENA con
2 decimales (``"8500.00"``) y nunca un numero: un cliente JavaScript parsearia el numero a
punto flotante y perderia exactitud, y Pydantic tendria que convertirlo a punto flotante para emitirlo.
"""
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    StrictInt,
    StringConstraints,
    model_validator,
)

__all__ = [
    "Codigo",
    "Descripcion",
    "Dinero",
    "MovimientoRespuesta",
    "Precio",
    "PrecioHistorialRespuesta",
    "Reposicion",
    "RepuestoAlta",
    "RepuestoEdicion",
    "RepuestoRespuesta",
]

_DOS_DECIMALES = Decimal("0.01")


def _rechazar_booleanos(valor: object) -> object:
    """``Decimal`` laxo aceptaria ``True`` como 1: un booleano nunca es un precio."""
    if isinstance(valor, bool):
        raise ValueError("El precio debe ser un número")
    return valor


Precio = Annotated[
    Decimal,
    BeforeValidator(_rechazar_booleanos),
    Field(gt=0, max_digits=10, decimal_places=2, allow_inf_nan=False),
    AfterValidator(lambda d: d.quantize(_DOS_DECIMALES)),
]

Dinero = Annotated[
    Decimal,
    PlainSerializer(lambda d: f"{d:.2f}", return_type=str, when_used="json"),
]

Codigo = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=50),
    AfterValidator(str.upper),
]
Descripcion = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]

_Cantidad = Annotated[StrictInt, Field(ge=1, le=1_000_000)]


class _Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RepuestoAlta(_Entrada):
    codigo: Codigo
    descripcion: Descripcion
    precio: Precio
    stock_inicial: Annotated[StrictInt, Field(ge=0, le=1_000_000)] = 0


class RepuestoEdicion(_Entrada):
    """Solo ``descripcion`` y ``precio``; el servicio usa ``model_dump(exclude_unset=True)``."""

    descripcion: Descripcion | None = None
    precio: Precio | None = None

    @model_validator(mode="after")
    def _sin_nulos_explicitos(self) -> Self:
        for campo in self.model_fields_set:
            if getattr(self, campo) is None:
                raise ValueError(f"{campo} no admite null")
        return self


class Reposicion(_Entrada):
    cantidad: _Cantidad


class _Salida(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RepuestoRespuesta(_Salida):
    id: int
    codigo: str
    descripcion: str
    precio: Dinero
    stock: int


class MovimientoRespuesta(_Salida):
    id: int
    repuesto_id: int
    orden_id: int | None
    usuario_id: int
    cantidad: int
    motivo: str
    cuando: datetime


class PrecioHistorialRespuesta(_Salida):
    id: int
    repuesto_id: int
    usuario_id: int
    precio_anterior: Dinero
    precio_nuevo: Dinero
    cuando: datetime
