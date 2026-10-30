"""Unit of Work del modulo clientes: clientes y vehiculos sobre la MISMA sesion (C-07, D9)."""
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionDep
from app.core.unit_of_work import UnitOfWork
from app.modules.clientes.repository import ClienteRepository, VehiculoRepository

__all__ = ["ClientesUoW", "ClientesUoWDep", "get_clientes_uow"]


class ClientesUoW(UnitOfWork):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.clientes = ClienteRepository(session)
        self.vehiculos = VehiculoRepository(session)


def get_clientes_uow(session: SessionDep) -> ClientesUoW:
    """Dependencia que CONSTRUYE el UoW (sin abrirlo): el servicio lo abre con ``async with``."""
    return ClientesUoW(session)


ClientesUoWDep = Annotated[ClientesUoW, Depends(get_clientes_uow)]
