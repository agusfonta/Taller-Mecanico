"""Repositorios de ordenes de trabajo (C-09, D3/D7/D9).

Solo ``flush()``: confirmar es de la Unit of Work. Ninguna relacion se lee sin precarga
(``lazy="raise"``): ``get_detalle`` declara explicitamente como se carga cada una.

* ``EstadoOrdenRepository`` NO hereda de ``BaseRepository``: el catalogo es de solo lectura desde
  la API (RN-19) y no existe ningun metodo de escritura que invocar.
* ``HistorialEstadoOrdenRepository`` es de solo agregado (la base rechaza UPDATE/DELETE con un
  disparador; aqui ``update``/``delete`` lanzan ``NotImplementedError``).
"""
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.core.repository import BaseRepository
from app.modules.clientes.models import Cliente, Vehiculo
from app.modules.ordenes.models import EstadoOrden, HistorialEstadoOrden, ItemOrden, OrdenTrabajo

__all__ = [
    "EstadoOrdenRepository",
    "HistorialEstadoOrdenRepository",
    "ItemOrdenRepository",
    "OrdenRepository",
]


class EstadoOrdenRepository:
    """Catalogo ``estado_orden``: solo lectura (RN-19)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def listar_por_posicion(self) -> Sequence[EstadoOrden]:
        consulta = select(EstadoOrden).order_by(EstadoOrden.posicion)
        return (await self.session.execute(consulta)).scalars().all()

    async def get_por_codigo(self, codigo: str) -> EstadoOrden | None:
        consulta = select(EstadoOrden).where(EstadoOrden.codigo == codigo)
        return (await self.session.execute(consulta)).scalar_one_or_none()


class OrdenRepository(BaseRepository[OrdenTrabajo]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, OrdenTrabajo)

    async def get_detalle(self, id_: int) -> OrdenTrabajo | None:
        """Orden con todo lo que muestra el detalle, en 3 sentencias fijas (caso C-15, D7).

        Las tres opciones de carga, sin importar cuantos items o lineas de historial haya:

        1. ``joinedload`` vehiculo -> cliente: un JOIN dentro de la sentencia principal. El
           vehiculo se lee SIN filtrar ``borrado_en`` (una orden de un vehiculo dado de baja
           sigue siendo consultable).
        2. ``selectinload`` items (+ ``joinedload`` repuesto): una sentencia ``IN`` con el JOIN
           del repuesto; nunca una sentencia por item.
        3. ``selectinload`` historial: una sentencia ``IN``.

        Total: 3 sentencias sobre ``orden_trabajo``/``item_orden``/``historial_estado_orden``.
        ``populate_existing`` es necesario porque, tras el alta, la orden ya esta en el mapa de
        identidad con ``creada_en`` expirado (default del servidor) y relaciones sin cargar: sin
        el, el acceso dispararia carga implicita (``lazy="raise"`` / ``MissingGreenlet``).

        Evidencia para C-12 (DD-22): arrancar con ``SQL_ECHO=true`` y pedir
        ``GET /ordenes/{id}``; en el log aparecen exactamente esas 3 sentencias (mas las 2
        constantes de la sesion: usuario y roles), iguales con 2 o con 20 items.
        """
        consulta = (
            select(OrdenTrabajo)
            .where(OrdenTrabajo.id == id_)
            .options(
                joinedload(OrdenTrabajo.vehiculo).joinedload(Vehiculo.cliente),
                selectinload(OrdenTrabajo.items).joinedload(ItemOrden.repuesto),
                selectinload(OrdenTrabajo.historial),
            )
            .execution_options(populate_existing=True)
        )
        return (await self.session.execute(consulta)).scalar_one_or_none()

    async def bloquear(self, id_: int) -> OrdenTrabajo | None:
        """Orden con ``FOR UPDATE`` y SIN relaciones: una sola sentencia (C-10, D2).

        Serializa las transiciones concurrentes sobre la misma orden: la segunda transaccion espera
        aqui y, al liberarse, lee la fila ya confirmada. ``populate_existing`` evita decidir con un
        estado viejo del mapa de identidad. Orden global de bloqueos: orden -> repuestos (D3).
        """
        consulta = (
            select(OrdenTrabajo)
            .where(OrdenTrabajo.id == id_)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return (await self.session.execute(consulta)).scalar_one_or_none()

    def _filtrada(self, estado: str | None, mecanico_visible: int | None) -> Select[tuple[OrdenTrabajo]]:
        consulta = select(OrdenTrabajo)
        if estado is not None:
            consulta = consulta.where(OrdenTrabajo.estado == estado)
        if mecanico_visible is not None:
            consulta = consulta.where(
                (OrdenTrabajo.mecanico_id == mecanico_visible) | OrdenTrabajo.mecanico_id.is_(None)
            )
        return consulta

    async def buscar(
        self, estado: str | None, mecanico_visible: int | None, *, offset: int, limit: int
    ) -> Sequence[OrdenTrabajo]:
        """Ordenes (resumen, sin relaciones) por ``id``; ``mecanico_visible`` = suyas + sin asignar."""
        consulta = self._filtrada(estado, mecanico_visible).order_by(OrdenTrabajo.id).offset(offset).limit(limit)
        return (await self.session.execute(consulta)).scalars().all()

    async def contar(self, estado: str | None, mecanico_visible: int | None) -> int:
        consulta = select(func.count()).select_from(self._filtrada(estado, mecanico_visible).subquery())
        return (await self.session.execute(consulta)).scalar_one()

    def _de_usuario(self, usuario_id: int) -> Select[tuple[OrdenTrabajo]]:
        # Sin filtrar vehiculo.borrado_en: el historial del cliente no desaparece (D9-a).
        return (
            select(OrdenTrabajo)
            .join(Vehiculo, Vehiculo.id == OrdenTrabajo.vehiculo_id)
            .join(Cliente, Cliente.id == Vehiculo.cliente_id)
            .where(Cliente.usuario_id == usuario_id)
        )

    async def listar_de_usuario(self, usuario_id: int, *, offset: int, limit: int) -> Sequence[OrdenTrabajo]:
        consulta = self._de_usuario(usuario_id).order_by(OrdenTrabajo.id).offset(offset).limit(limit)
        return (await self.session.execute(consulta)).scalars().all()

    async def contar_de_usuario(self, usuario_id: int) -> int:
        consulta = select(func.count()).select_from(self._de_usuario(usuario_id).subquery())
        return (await self.session.execute(consulta)).scalar_one()


class ItemOrdenRepository(BaseRepository[ItemOrden]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ItemOrden)

    async def add_todos(self, items: Sequence[ItemOrden]) -> Sequence[ItemOrden]:
        """Inserta todos los items con un solo ``flush`` (insercion por lotes)."""
        self.session.add_all(items)
        await self.session.flush()
        return items


class HistorialEstadoOrdenRepository(BaseRepository[HistorialEstadoOrden]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, HistorialEstadoOrden)

    async def update(
        self, entidad: HistorialEstadoOrden, cambios: Mapping[str, Any]
    ) -> HistorialEstadoOrden:
        raise NotImplementedError("historial_estado_orden es de solo agregado")

    async def delete(self, entidad: HistorialEstadoOrden) -> None:
        raise NotImplementedError("historial_estado_orden es de solo agregado")
