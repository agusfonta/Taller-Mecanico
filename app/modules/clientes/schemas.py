"""Contratos de clientes y vehiculos (C-07, D3/D5): separados de los modelos de tabla.

Por que la patente se normaliza en el contrato: ``uq_vehiculo_patente_vigente`` compara el
texto EXACTO, asi que ``AB123CD`` y ``ab 123 cd`` serian dos vehiculos vigentes con "la misma"
patente. Normalizar aqui (sin espacios ni guiones, en mayusculas) hace que el 422 de una patente
invalida sea parte del contrato y que la unicidad de la base sea la unica fuente de verdad.

Por que ``strict`` en ``anio``: en modo laxo ``"2020"`` se aceptaria como entero; el contrato
pide un numero entero JSON. El CHECK ``ck_vehiculo_anio_rango`` queda como segunda barrera.
"""
import re
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints

__all__ = [
    "ClienteDetalleRespuesta",
    "ClienteEntrada",
    "ClienteRespuesta",
    "Patente",
    "VehiculoEntrada",
    "VehiculoRespuesta",
    "VehiculoResumen",
    "normalizar_patente",
]

_SEPARADORES = re.compile(r"[\s-]")


def _texto(maximo: int):
    return Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=maximo)]


Texto120 = _texto(120)
Texto60 = _texto(60)
Texto30 = _texto(30)
Texto20 = _texto(20)


def normalizar_patente(valor: object) -> object:
    """Quita espacios y guiones y pasa a mayusculas; lo que no es ``str`` pasa para fallar por tipo."""
    if isinstance(valor, str):
        return _SEPARADORES.sub("", valor).upper()
    return valor


Patente = Annotated[
    str,
    BeforeValidator(normalizar_patente),
    StringConstraints(pattern=r"^[A-Z0-9]{1,10}$"),
]


class _Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClienteEntrada(_Entrada):
    nombre: Texto120
    documento: Texto20
    telefono: Texto30


class VehiculoEntrada(_Entrada):
    patente: Patente
    marca: Texto60
    modelo: Texto60
    anio: Annotated[int, Field(strict=True, ge=1950, le=2100)]


class ClienteRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    documento: str
    telefono: str
    usuario_id: int | None


class VehiculoResumen(BaseModel):
    """Vehiculo dentro del detalle de un cliente (sin ``cliente_id``: ya es el del padre)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    patente: str
    marca: str
    modelo: str
    anio: int


class VehiculoRespuesta(VehiculoResumen):
    cliente_id: int


class ClienteDetalleRespuesta(ClienteRespuesta):
    vehiculos: list[VehiculoResumen]
