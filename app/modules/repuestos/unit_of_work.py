"""Unit of Work del modulo repuestos: catalogo, movimientos e historial sobre la MISMA sesion (D9)."""
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionDep
from app.core.unit_of_work import UnitOfWork
from app.modules.repuestos.repository import (
    HistorialPrecioRepository,
    MovimientoStockRepository,
    RepuestoRepository,
)

__all__ = ["RepuestosUoW", "RepuestosUoWDep", "get_repuestos_uow"]


class RepuestosUoW(UnitOfWork):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.repuestos = RepuestoRepository(session)
        self.movimientos = MovimientoStockRepository(session)
        self.precios = HistorialPrecioRepository(session)


def get_repuestos_uow(session: SessionDep) -> RepuestosUoW:
    """Dependencia que CONSTRUYE el UoW (sin abrirlo): el servicio lo abre con ``async with``."""
    return RepuestosUoW(session)


RepuestosUoWDep = Annotated[RepuestosUoW, Depends(get_repuestos_uow)]
