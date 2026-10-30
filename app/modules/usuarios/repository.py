"""Repositorios del módulo usuarios (C-05, D10).

Solo ``flush()`` (lo hace ``BaseRepository``): confirmar es de la Unit of Work. Todas las
consultas usan parametros ligados de SQLAlchemy; ningun SQL se arma por concatenacion.
Sin carga perezosa: ninguno de estos metodos lee relaciones.
"""
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.repository import BaseRepository
from app.modules.usuarios.models import AsignacionRol, EventoSeguridad, IntentoAcceso, Rol, Usuario

__all__ = [
    "AsignacionRolRepository",
    "EventoSeguridadRepository",
    "IntentoAccesoRepository",
    "UsuarioRepository",
]


class UsuarioRepository(BaseRepository[Usuario]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Usuario)

    async def get_by_email(self, email: str) -> Usuario | None:
        """Busqueda EXACTA: el llamador normaliza el correo (minusculas, sin espacios)."""
        resultado = await self.session.execute(select(Usuario).where(Usuario.email == email))
        return resultado.scalar_one_or_none()


class AsignacionRolRepository(BaseRepository[AsignacionRol]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, AsignacionRol)

    async def roles_vigentes(self, usuario_id: int, ahora: datetime) -> list[Rol]:
        """Roles no revocados y sin vencer a ``ahora`` (RN-04), ordenados por nombre."""
        consulta = (
            select(AsignacionRol.rol)
            .where(
                AsignacionRol.usuario_id == usuario_id,
                AsignacionRol.revocada_en.is_(None),
                (AsignacionRol.vence_en.is_(None)) | (AsignacionRol.vence_en > ahora),
            )
            .order_by(AsignacionRol.rol)
        )
        return [Rol(rol) for rol in (await self.session.execute(consulta)).scalars().all()]

    async def abierta(self, usuario_id: int, rol: Rol | str) -> AsignacionRol | None:
        """La asignacion NO revocada de ``(usuario, rol)``, vigente o vencida (a lo sumo una).

        ``uq_asignacion_rol_abierta`` garantiza que haya una sola con ``revocada_en IS NULL``.
        """
        consulta = select(AsignacionRol).where(
            AsignacionRol.usuario_id == usuario_id,
            AsignacionRol.rol == Rol(rol).value,
            AsignacionRol.revocada_en.is_(None),
        )
        return (await self.session.execute(consulta)).scalar_one_or_none()

    async def historial(self, usuario_id: int) -> Sequence[AsignacionRol]:
        """Todas las asignaciones del usuario (vigentes, vencidas y revocadas), por ``desde``, ``id``."""
        consulta = (
            select(AsignacionRol)
            .where(AsignacionRol.usuario_id == usuario_id)
            .order_by(AsignacionRol.desde, AsignacionRol.id)
        )
        return (await self.session.execute(consulta)).scalars().all()

    async def bloquear_admins_vigentes(self, ahora: datetime) -> list[int]:
        """``usuario_id`` de los ADMIN vigentes y ACTIVOS, bloqueando sus filas (RN-05, D5).

        ``FOR UPDATE OF asignacion_rol`` bloquea solo las asignaciones (no la fila de ``usuario``):
        una segunda revocacion de ADMIN espera y, al liberarse, PostgreSQL (READ COMMITTED)
        reevalua el ``WHERE`` y ya no ve la fila revocada. ``ORDER BY id`` da un orden de
        bloqueo unico y evita interbloqueos entre dos revocaciones simultaneas.
        """
        consulta = (
            select(AsignacionRol.usuario_id)
            .join(Usuario, Usuario.id == AsignacionRol.usuario_id)
            .where(
                AsignacionRol.rol == Rol.ADMIN.value,
                AsignacionRol.revocada_en.is_(None),
                (AsignacionRol.vence_en.is_(None)) | (AsignacionRol.vence_en > ahora),
                Usuario.activo.is_(True),
            )
            .order_by(AsignacionRol.id)
            .with_for_update(of=AsignacionRol)
        )
        return list((await self.session.execute(consulta)).scalars().all())


class IntentoAccesoRepository(BaseRepository[IntentoAcceso]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, IntentoAcceso)

    async def fallos_bloqueantes(
        self, email: str, ip: str, desde: datetime, limite: int = 5
    ) -> Sequence[datetime]:
        """Instantes (del mas nuevo al mas viejo, hasta ``limite``) de los fallos que cuentan (RN-08).

        Cuentan los fallos de ese (correo, IP) posteriores a ``desde`` Y al ultimo login
        correcto del MISMO (correo, IP): un exito reinicia solo esa cuenta. Usa el indice
        ``(email, ip, cuando)``.
        """
        ultimo_exito = (
            select(func.max(IntentoAcceso.cuando))
            .where(
                IntentoAcceso.email == email,
                IntentoAcceso.ip == ip,
                IntentoAcceso.exito.is_(True),
            )
            .scalar_subquery()
        )
        consulta = (
            select(IntentoAcceso.cuando)
            .where(
                IntentoAcceso.email == email,
                IntentoAcceso.ip == ip,
                IntentoAcceso.exito.is_(False),
                IntentoAcceso.cuando > desde,
                IntentoAcceso.cuando > func.coalesce(ultimo_exito, datetime.min.replace(tzinfo=UTC)),
            )
            .order_by(IntentoAcceso.cuando.desc())
            .limit(limite)
        )
        return (await self.session.execute(consulta)).scalars().all()


class EventoSeguridadRepository(BaseRepository[EventoSeguridad]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, EventoSeguridad)

    async def listar_recientes(self, *, offset: int, limit: int) -> Sequence[EventoSeguridad]:
        """Mas reciente primero; ``id`` desempata eventos con el mismo ``cuando`` (orden estable)."""
        consulta = (
            select(EventoSeguridad)
            .order_by(EventoSeguridad.cuando.desc(), EventoSeguridad.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return (await self.session.execute(consulta)).scalars().all()
