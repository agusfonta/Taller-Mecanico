"""Tabla pura de transiciones de estado de las ordenes (C-10, D1, DD-02).

Sin entrada/salida: ``destino`` decide con una tabla en codigo. El catalogo ``estado_orden`` solo
dice cuales estados son finales (``es_final``), no las aristas; un test verifica que ambos
coincidan (D1-a), pero en ejecucion no se consulta ``es_final`` para transicionar.
"""
from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType

from app.modules.ordenes.models import EstadoOrdenCodigo

__all__ = ["Accion", "TRANSICIONES", "destino"]


class Accion(StrEnum):
    INICIAR = "iniciar"
    TERMINAR = "terminar"
    CANCELAR = "cancelar"


TRANSICIONES: Mapping[tuple[Accion, EstadoOrdenCodigo], EstadoOrdenCodigo] = MappingProxyType(
    {
        (Accion.INICIAR, EstadoOrdenCodigo.PENDIENTE): EstadoOrdenCodigo.EN_REPARACION,
        (Accion.TERMINAR, EstadoOrdenCodigo.EN_REPARACION): EstadoOrdenCodigo.TERMINADA,
        (Accion.CANCELAR, EstadoOrdenCodigo.PENDIENTE): EstadoOrdenCodigo.CANCELADA,
    }
)


def destino(accion: Accion, actual: str) -> EstadoOrdenCodigo:
    """Estado al que lleva ``accion`` desde ``actual``; ``TransicionInvalidaError`` si no existe."""
    try:
        return TRANSICIONES[(accion, EstadoOrdenCodigo(actual))]
    except (KeyError, ValueError):
        # Import local: ``service`` importa este modulo (ciclo si fuera a nivel de modulo).
        from app.modules.ordenes.service import TransicionInvalidaError

        raise TransicionInvalidaError(str(actual), accion.value) from None
