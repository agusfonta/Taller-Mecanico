"""Repositorios genericos (D4).

Los repositorios escriben con ``flush()``: la confirmacion es exclusiva de la
Unit of Work y el cierre de la sesion es de ``get_session``. Sin carga
perezosa: los metodos base no cargan relaciones; los repositorios de modulo
declaran ``selectinload``/``joinedload`` sobrescribiendo ``_consulta()`` o con
metodos propios (recomendacion para C-03: relaciones con ``lazy="raise"``).
"""
import builtins
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, func, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel

__all__ = ["BaseRepository", "SoftDeleteRepository"]


class BaseRepository[T: SQLModel]:
    def __init__(self, session: AsyncSession, model: type[T]) -> None:
        pk = inspect(model).primary_key
        if len(pk) != 1:
            raise TypeError(
                f"{model.__name__} necesita una PK de una sola columna (tiene {len(pk)})"
            )
        self.session = session
        self.model = model
        self._pk = pk[0]

    def _consulta(self) -> Select[tuple[T]]:
        """Punto de extension de filtros y opciones de carga."""
        return select(self.model)

    async def get_by_id(self, id_: int) -> T | None:
        resultado = await self.session.execute(self._consulta().where(self._pk == id_))
        return resultado.scalar_one_or_none()

    async def list(self, *, offset: int, limit: int) -> Sequence[T]:
        consulta = self._consulta().order_by(self._pk).offset(offset).limit(limit)
        return (await self.session.execute(consulta)).scalars().all()

    async def count(self) -> int:
        consulta = select(func.count()).select_from(self._consulta().subquery())
        return (await self.session.execute(consulta)).scalar_one()

    async def add(self, entidad: T) -> T:
        self.session.add(entidad)
        await self.session.flush()
        return entidad

    async def update(self, entidad: T, cambios: Mapping[str, Any]) -> T:
        validas = {a.key for a in inspect(self.model).column_attrs}
        desconocidas = builtins.set(cambios) - validas
        if desconocidas:
            raise ValueError(f"Campos desconocidos: {sorted(desconocidas)}")
        for clave, valor in cambios.items():
            setattr(entidad, clave, valor)
        await self.session.flush()
        return entidad

    async def delete(self, entidad: T) -> None:
        await self.session.delete(entidad)
        await self.session.flush()


class SoftDeleteRepository[T: SQLModel](BaseRepository[T]):
    """Repositorio con borrado logico.

    El modelo debe tener ``borrado_en`` (TIMESTAMPTZ NULL). Por defecto excluye
    las filas con ``borrado_en`` no nulo de ``get_by_id``, ``list`` y ``count``.
    El indice unico parcial (``WHERE borrado_en IS NULL``) lo define C-03 (DD-03).
    """

    def _consulta(self) -> Select[tuple[T]]:
        return super()._consulta().where(self.model.borrado_en.is_(None))  # type: ignore[attr-defined]

    async def get_by_id_including_deleted(self, id_: int) -> T | None:
        consulta = select(self.model).where(self._pk == id_)
        return (await self.session.execute(consulta)).scalar_one_or_none()

    async def soft_delete(self, entidad: T) -> T:
        entidad.borrado_en = datetime.now(UTC)  # type: ignore[attr-defined]
        await self.session.flush()
        return entidad
