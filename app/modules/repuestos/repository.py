"""Repositorios de repuestos, movimientos de stock e historial de precios (C-08, D5/D6/D8/D9).

Solo ``flush()``: confirmar es de la Unit of Work. Ninguna relacion se lee sin precarga
(``lazy="raise"``): estos repositorios solo cargan columnas.

``RepuestoRepository.sumar_stock`` es el UNICO lugar de ``app/`` que escribe ``repuesto.stock``
(RN-14); lo invoca ``stock.mover_stock``. Movimientos e historial son de SOLO agregado: la base
rechaza UPDATE/DELETE con un disparador y aqui ``update``/``delete`` lanzan
``NotImplementedError`` (defensa en profundidad).
"""
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import BigInteger, Select, any_, cast, func, literal, select, update
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import attributes
from sqlalchemy.orm.util import identity_key

from app.core.repository import BaseRepository, SoftDeleteRepository
from app.modules.repuestos.models import HistorialPrecioRepuesto, MovimientoStock, Repuesto

__all__ = [
    "HistorialPrecioRepository",
    "MovimientoStockRepository",
    "RepuestoRepository",
    "STOCK_MAXIMO",
    "escapar_like",
]

STOCK_MAXIMO = 2_147_483_647  # maximo de la columna INTEGER


def escapar_like(texto: str) -> str:
    """Escapa la barra invertida, ``%`` y ``_`` para buscar ``texto`` como literal en un LIKE."""
    return texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class RepuestoRepository(SoftDeleteRepository[Repuesto]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Repuesto)

    async def update(self, entidad: Repuesto, cambios: Mapping[str, Any]) -> Repuesto:
        """Actualiza columnas, salvo ``stock`` (RN-14: solo cambia por ``sumar_stock``)."""
        if "stock" in cambios:
            raise ValueError("El stock solo se modifica mediante mover_stock (RN-14)")
        return await super().update(entidad, cambios)

    async def get_by_id_para_actualizar(self, id_: int) -> Repuesto | None:
        """Repuesto vigente bloqueado con ``FOR UPDATE`` y releido de la base (D6)."""
        consulta = (
            self._consulta()
            .where(self._pk == id_)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return (await self.session.execute(consulta)).scalar_one_or_none()

    async def listar_vigentes_para_orden(self, ids: Sequence[int]) -> Sequence[Repuesto]:
        """Repuestos vigentes entre ``ids`` con ``FOR SHARE``, por ``id`` (C-09, D5/D6).

        Una sola sentencia con ids ligados (``= ANY(:ids)``). El orden por ``id`` es el mismo que
        exige ``mover_stock`` con varios repuestos: sin interbloqueos entre altas y terminaciones.
        La baja y el PATCH de precio esperan a que el alta confirme.
        """
        if not ids:
            return []
        consulta = (
            self._consulta()
            .where(Repuesto.id == any_(literal(list(ids), ARRAY(BigInteger))))
            .order_by(Repuesto.id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        return (await self.session.execute(consulta)).scalars().all()

    async def sumar_stock(self, repuesto_id: int, delta: int) -> int | None:
        """``UPDATE ... SET stock = stock + :delta`` atomico (D5); devuelve el stock nuevo.

        Devuelve ``None`` si el repuesto no existe o si el resultado superaria ``STOCK_MAXIMO``
        (la guarda en BIGINT evita un ``DataError``). Un resultado negativo lo rechaza el
        ``CHECK stock >= 0`` de la base con ``IntegrityError``. No filtra borrados logicos.
        """
        sentencia = (
            update(Repuesto)
            .where(
                Repuesto.id == repuesto_id,
                cast(Repuesto.stock, BigInteger) + delta <= STOCK_MAXIMO,
            )
            .values(stock=Repuesto.stock + delta)
            .returning(Repuesto.stock)
            .execution_options(synchronize_session=False)
        )
        nuevo = (await self.session.execute(sentencia)).scalar_one_or_none()
        if nuevo is not None:
            # La entidad ya cargada en la sesion ve el stock nuevo sin una lectura extra.
            cargada = self.session.identity_map.get(identity_key(Repuesto, repuesto_id))
            if cargada is not None:
                attributes.set_committed_value(cargada, "stock", nuevo)
        return nuevo

    def _filtrada(self, q: str | None) -> Select[tuple[Repuesto]]:
        consulta = self._consulta()
        if q is not None:
            patron = f"%{escapar_like(q)}%"
            consulta = consulta.where(Repuesto.descripcion.ilike(patron, escape="\\"))
        return consulta

    async def buscar(self, q: str | None, *, offset: int, limit: int) -> Sequence[Repuesto]:
        """Vigentes cuya descripcion contiene ``q`` (literal, sin distinguir mayusculas), por id."""
        consulta = self._filtrada(q).order_by(Repuesto.id).offset(offset).limit(limit)
        return (await self.session.execute(consulta)).scalars().all()

    async def contar(self, q: str | None) -> int:
        consulta = select(func.count()).select_from(self._filtrada(q).subquery())
        return (await self.session.execute(consulta)).scalar_one()


class MovimientoStockRepository(BaseRepository[MovimientoStock]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, MovimientoStock)

    async def update(self, entidad: MovimientoStock, cambios: Mapping[str, Any]) -> MovimientoStock:
        raise NotImplementedError("movimiento_stock es de solo agregado")

    async def delete(self, entidad: MovimientoStock) -> None:
        raise NotImplementedError("movimiento_stock es de solo agregado")

    async def listar_por_repuesto(
        self, repuesto_id: int, *, offset: int, limit: int
    ) -> Sequence[MovimientoStock]:
        consulta = (
            select(MovimientoStock)
            .where(MovimientoStock.repuesto_id == repuesto_id)
            .order_by(MovimientoStock.id)
            .offset(offset)
            .limit(limit)
        )
        return (await self.session.execute(consulta)).scalars().all()

    async def contar_por_repuesto(self, repuesto_id: int) -> int:
        consulta = select(func.count()).where(MovimientoStock.repuesto_id == repuesto_id)
        return (await self.session.execute(consulta)).scalar_one()


class HistorialPrecioRepository(BaseRepository[HistorialPrecioRepuesto]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, HistorialPrecioRepuesto)

    async def update(
        self, entidad: HistorialPrecioRepuesto, cambios: Mapping[str, Any]
    ) -> HistorialPrecioRepuesto:
        raise NotImplementedError("historial_precio_repuesto es de solo agregado")

    async def delete(self, entidad: HistorialPrecioRepuesto) -> None:
        raise NotImplementedError("historial_precio_repuesto es de solo agregado")

    async def listar_por_repuesto(
        self, repuesto_id: int, *, offset: int, limit: int
    ) -> Sequence[HistorialPrecioRepuesto]:
        consulta = (
            select(HistorialPrecioRepuesto)
            .where(HistorialPrecioRepuesto.repuesto_id == repuesto_id)
            .order_by(HistorialPrecioRepuesto.id)
            .offset(offset)
            .limit(limit)
        )
        return (await self.session.execute(consulta)).scalars().all()

    async def contar_por_repuesto(self, repuesto_id: int) -> int:
        consulta = select(func.count()).where(HistorialPrecioRepuesto.repuesto_id == repuesto_id)
        return (await self.session.execute(consulta)).scalar_one()
