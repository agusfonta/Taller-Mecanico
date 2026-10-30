"""Unit of Work del modulo ordenes (C-09, D1).

Expone, sobre la MISMA sesion, los repositorios de ordenes y los de clientes (vehiculos) y repuestos
(``repuestos`` + ``movimientos``): asi cumple ``ConStock`` y C-10 llama ``mover_stock(uow, ...)``
sin abrir otra transaccion (el alta y la terminacion son atomicas).
"""
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionDep
from app.core.unit_of_work import UnitOfWork
from app.modules.clientes.repository import VehiculoRepository
from app.modules.ordenes.repository import (
    EstadoOrdenRepository,
    HistorialEstadoOrdenRepository,
    ItemOrdenRepository,
    OrdenRepository,
)
from app.modules.repuestos.repository import MovimientoStockRepository, RepuestoRepository

__all__ = ["OrdenesUoW", "OrdenesUoWDep", "get_ordenes_uow"]


class OrdenesUoW(UnitOfWork):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.estados = EstadoOrdenRepository(session)
        self.ordenes = OrdenRepository(session)
        self.items = ItemOrdenRepository(session)
        self.historial = HistorialEstadoOrdenRepository(session)
        self.vehiculos = VehiculoRepository(session)
        self.repuestos = RepuestoRepository(session)
        self.movimientos = MovimientoStockRepository(session)


def get_ordenes_uow(session: SessionDep) -> OrdenesUoW:
    """Dependencia que CONSTRUYE el UoW (sin abrirlo): el servicio lo abre con ``async with``."""
    return OrdenesUoW(session)


OrdenesUoWDep = Annotated[OrdenesUoW, Depends(get_ordenes_uow)]
