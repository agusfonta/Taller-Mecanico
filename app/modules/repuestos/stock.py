"""Punto unico de escritura de stock (C-08, D4/D5, RN-14).

``mover_stock`` es la UNICA forma de cambiar ``repuesto.stock``: aplica la variacion en la base
(incremento relativo y atomico) y registra el ``movimiento_stock`` en la misma transaccion.
Lo usan el alta (stock inicial), la reposicion y, desde C-10, la terminacion de ordenes.

Contrato para C-10 (y cualquier otro llamador):

* Llamar DENTRO de un UoW ya abierto (``async with uow``): ``mover_stock`` nunca abre ni
  confirma una transaccion. Si algo falla, la excepcion debe atravesar el bloque para que el UoW
  revierta TODO (stock y movimientos ya aplicados en esa operacion).
* Tras ``StockInsuficienteError`` la transaccion de PostgreSQL queda abortada: NO capturar la
  excepcion dentro del bloque para seguir usando la sesion; dejarla propagar.
* Con varios repuestos en una misma operacion, iterar ordenado por ``repuesto_id`` ascendente:
  dos transacciones concurrentes toman asi los bloqueos de fila en el mismo orden (sin
  interbloqueos).
* No filtra repuestos dados de baja (SU-C08-9): decidir si corresponde es del llamador.
* ``cantidad`` > 0 es una entrada y < 0 una salida; 0 y un ``motivo`` vacio son errores de
  programacion (``ValueError``).
"""
from typing import Protocol

from sqlalchemy.exc import IntegrityError

from app.core.errores import restriccion_violada
from app.modules.repuestos.models import MovimientoStock
from app.modules.repuestos.repository import (
    STOCK_MAXIMO,
    MovimientoStockRepository,
    RepuestoRepository,
)

__all__ = [
    "ConStock",
    "MOTIVO_ORDEN_TERMINADA",
    "MOTIVO_REPOSICION",
    "MOTIVO_STOCK_INICIAL",
    "RepuestoNoEncontradoError",
    "STOCK_MAXIMO",
    "StockFueraDeRangoError",
    "StockInsuficienteError",
    "mover_stock",
]

MOTIVO_STOCK_INICIAL = "Stock inicial"
MOTIVO_REPOSICION = "Reposición"
MOTIVO_ORDEN_TERMINADA = "Terminación de orden"  # el orden_id del movimiento identifica la orden

_CK_STOCK_NO_NEGATIVO = "ck_repuesto_stock_no_negativo"


class ConStock(Protocol):
    """Lo que ``mover_stock`` necesita de un UoW (``RepuestosUoW`` lo cumple por estructura)."""

    repuestos: RepuestoRepository
    movimientos: MovimientoStockRepository


class _ErrorDeStock(Exception):
    def __init__(self, repuesto_id: int) -> None:
        super().__init__(repuesto_id)
        self.repuesto_id = repuesto_id


class StockInsuficienteError(_ErrorDeStock):
    """Una salida dejaria el stock por debajo de 0."""


class StockFueraDeRangoError(_ErrorDeStock):
    """El stock resultante superaria el maximo representable (INTEGER)."""


class RepuestoNoEncontradoError(_ErrorDeStock):
    """El repuesto no existe."""


async def mover_stock(
    uow: ConStock,
    *,
    repuesto_id: int,
    cantidad: int,
    motivo: str,
    usuario_id: int,
    orden_id: int | None = None,
) -> int:
    """Aplica ``cantidad`` al stock y registra el movimiento; devuelve el stock resultante."""
    if cantidad == 0:
        raise ValueError("La variación de stock no puede ser 0")
    if not motivo or not motivo.strip():
        raise ValueError("El motivo del movimiento no puede estar vacío")

    try:
        nuevo = await uow.repuestos.sumar_stock(repuesto_id, cantidad)
    except IntegrityError as exc:
        if restriccion_violada(exc) == _CK_STOCK_NO_NEGATIVO:
            raise StockInsuficienteError(repuesto_id) from None
        raise
    if nuevo is None:
        existente = await uow.repuestos.get_by_id_including_deleted(repuesto_id)
        if existente is None:
            raise RepuestoNoEncontradoError(repuesto_id)
        raise StockFueraDeRangoError(repuesto_id)

    await uow.movimientos.add(
        MovimientoStock(
            repuesto_id=repuesto_id,
            orden_id=orden_id,
            usuario_id=usuario_id,
            cantidad=cantidad,
            motivo=motivo,
        )
    )
    return nuevo
