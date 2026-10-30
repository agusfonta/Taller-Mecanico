"""Repositorios de clientes y vehiculos (C-05 minimo, extendido en C-07).

``ClienteRepository`` conserva su constructor y su herencia: el registro (RN-02) solo usa
``add``. Los repositorios solo hacen ``flush()``; confirmar es de la Unit of Work (regla dura).
Ninguna relacion se lee sin precarga (``lazy="raise"``).
"""
from collections.abc import Sequence

from sqlalchemy import exists, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.repository import BaseRepository, SoftDeleteRepository
from app.modules.clientes.models import Cliente, Vehiculo
from app.modules.ordenes.models import EstadoOrden, OrdenTrabajo

__all__ = ["ClienteRepository", "VehiculoRepository"]


class ClienteRepository(BaseRepository[Cliente]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Cliente)

    async def get_con_vehiculos_vigentes(self, id_: int) -> Cliente | None:
        """Cliente con sus vehiculos NO dados de baja precargados (2 sentencias fijas, sin N+1)."""
        consulta = (
            select(Cliente)
            .where(Cliente.id == id_)
            .options(selectinload(Cliente.vehiculos.and_(Vehiculo.borrado_en.is_(None))))
        )
        return (await self.session.execute(consulta)).scalar_one_or_none()


class VehiculoRepository(SoftDeleteRepository[Vehiculo]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Vehiculo)

    async def get_vigente_para_baja(self, id_: int) -> Vehiculo | None:
        """Vehiculo vigente bloqueado con ``FOR UPDATE`` (serializa la baja con el alta de orden).

        C-09 debe leer el vehiculo con ``FOR SHARE`` para coordinarse con este bloqueo (D6/D10).
        """
        consulta = (
            select(Vehiculo).where(Vehiculo.id == id_, Vehiculo.borrado_en.is_(None)).with_for_update()
        )
        return (await self.session.execute(consulta)).scalar_one_or_none()

    async def get_vigente_para_orden(self, id_: int) -> Vehiculo | None:
        """Vehiculo vigente leido con ``FOR SHARE`` (C-09, D6): el alta de una orden espera a la baja.

        Coordina con ``get_vigente_para_baja`` (``FOR UPDATE``): si la baja llega primero, el alta
        espera y, al reevaluar ``borrado_en IS NULL``, ya no lo encuentra; si el alta llega
        primero, la baja espera su commit y ve la orden abierta. Una sola sentencia.
        """
        consulta = (
            select(Vehiculo)
            .where(Vehiculo.id == id_, Vehiculo.borrado_en.is_(None))
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        return (await self.session.execute(consulta)).scalar_one_or_none()

    async def tiene_ordenes_abiertas(self, vehiculo_id: int) -> bool:
        """Hay una orden cuyo estado del catalogo tiene ``es_final`` falso (el catalogo decide)."""
        abiertas = exists().where(
            OrdenTrabajo.vehiculo_id == vehiculo_id,
            OrdenTrabajo.estado == EstadoOrden.codigo,
            EstadoOrden.es_final.is_(False),
        )
        return bool((await self.session.execute(select(abiertas))).scalar_one())

    async def listar_vigentes_de_usuario(self, usuario_id: int) -> Sequence[Vehiculo]:
        """Vehiculos vigentes de la ficha vinculada al usuario, por id; una sola sentencia."""
        consulta = (
            select(Vehiculo)
            .join(Cliente, Cliente.id == Vehiculo.cliente_id)
            .where(Cliente.usuario_id == usuario_id, Vehiculo.borrado_en.is_(None))
            .order_by(Vehiculo.id)
        )
        return (await self.session.execute(consulta)).scalars().all()
