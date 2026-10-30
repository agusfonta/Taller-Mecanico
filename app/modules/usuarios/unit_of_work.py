"""Unit of Work del módulo usuarios: los cinco repositorios sobre la MISMA sesion (C-05)."""
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionDep
from app.core.unit_of_work import UnitOfWork
from app.modules.clientes.repository import ClienteRepository
from app.modules.usuarios.repository import (
    AsignacionRolRepository,
    EventoSeguridadRepository,
    IntentoAccesoRepository,
    UsuarioRepository,
)

__all__ = ["UsuariosUoW", "UsuariosUoWDep", "get_usuarios_uow"]


class UsuariosUoW(UnitOfWork):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.usuarios = UsuarioRepository(session)
        self.asignaciones = AsignacionRolRepository(session)
        self.clientes = ClienteRepository(session)
        self.eventos = EventoSeguridadRepository(session)
        self.intentos = IntentoAccesoRepository(session)


def get_usuarios_uow(session: SessionDep) -> UsuariosUoW:
    """Dependencia que CONSTRUYE el UoW (sin abrirlo): el servicio lo abre con ``async with``.

    Vive aqui y no en ``router.py`` (como sugeria el diseno) para que ``core.dependencies``
    pueda usarla sin importar el router, que a su vez importa ``core.dependencies``.
    """
    return UsuariosUoW(session)


UsuariosUoWDep = Annotated[UsuariosUoW, Depends(get_usuarios_uow)]
