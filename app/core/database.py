"""Motor y sesiones de PostgreSQL (D1).

Fabricas puras: nada a nivel de modulo crea motor, pool ni sesiones (EA-08).
Solo el lifespan llama a ``crear_motor`` / ``crear_fabrica_sesiones``.
``get_session`` entrega una sesion por peticion y la cierra al terminar; la
UoW nunca la cierra.
"""
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings

__all__ = ["crear_motor", "crear_fabrica_sesiones", "get_session", "SessionDep"]


def crear_motor(settings: Settings) -> AsyncEngine:
    """Crea el motor asincrono; no abre conexiones hasta que se usa."""
    return create_async_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        echo=settings.sql_echo,
        pool_pre_ping=True,
    )


def crear_fabrica_sesiones(motor: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """``expire_on_commit=False``: leer atributos tras confirmar no consulta la base."""
    return async_sessionmaker(motor, expire_on_commit=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Una sesion por peticion, tomada de ``app.state``; se cierra aun con error."""
    fabrica = request.app.state.session_factory
    async with fabrica() as sesion:
        yield sesion


SessionDep = Annotated[AsyncSession, Depends(get_session)]
