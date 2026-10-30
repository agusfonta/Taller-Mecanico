"""Unit of Work: frontera transaccional de una operacion de negocio (D5).

Confirma al salir del bloque sin error y revierte ante cualquier excepcion
(incluida ``CancelledError``). No cierra la sesion: quien la crea
(``get_session``) es quien la cierra. No es reentrante: un bloque por
operacion de negocio.

Extension por modulo::

    class ClientesUoW(UnitOfWork):
        def __init__(self, session):
            super().__init__(session)
            self.clientes = ClienteRepository(session)
"""
from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["UnitOfWork"]


class UnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        if exc_type is not None:
            await self.session.rollback()
            return False
        try:
            await self.session.commit()
        except BaseException:
            await self.session.rollback()
            raise
        return False
