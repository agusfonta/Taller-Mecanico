"""Modelos de tabla de acceso y seguridad (C-03, D1).

Se importa ``app.core.models`` PRIMERO: fija la convencion de nombres antes de
declarar tablas. Solo columnas, PK, FK y restricciones; las relaciones llegan
con ``lazy="raise"`` (precargar en el repositorio con ``selectinload`` /
``joinedload``).
"""
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, Index, UniqueConstraint, text
from sqlmodel import Relationship, SQLModel

from app.core.models import booleano, fecha, fk, pk_identidad, texto

if TYPE_CHECKING:
    from app.modules.clientes.models import Cliente
    from app.modules.ordenes.models import OrdenTrabajo

__all__ = ["Rol", "Usuario", "AsignacionRol", "IntentoAcceso", "EventoSeguridad"]


class Rol(StrEnum):
    """Vocabulario de ``asignacion_rol.rol`` (fuente unica del CHECK)."""

    ADMIN = "ADMIN"
    RECEPCION = "RECEPCION"
    MECANICO = "MECANICO"
    CLIENTE = "CLIENTE"


_ROLES_SQL = ", ".join("'" + rol.value + "'" for rol in Rol)


class Usuario(SQLModel, table=True):
    __tablename__ = "usuario"
    __table_args__ = (UniqueConstraint("email"),)

    id: int | None = pk_identidad()
    email: str = texto()
    nombre: str = texto()
    password_hash: str = texto()
    activo: bool = booleano(server_default="true", default=True)
    debe_cambiar_password: bool = booleano(server_default="false", default=False)
    password_cambiada_en: datetime | None = fecha(nullable=True)

    # lazy="raise": precargar en el repositorio con selectinload/joinedload.
    asignaciones: list["AsignacionRol"] = Relationship(
        back_populates="usuario", sa_relationship_kwargs={"lazy": "raise", "foreign_keys": "[AsignacionRol.usuario_id]"}
    )
    cliente: Optional["Cliente"] = Relationship(  # noqa: UP045
        back_populates="usuario", sa_relationship_kwargs={"lazy": "raise", "uselist": False}
    )
    ordenes_asignadas: list["OrdenTrabajo"] = Relationship(
        back_populates="mecanico", sa_relationship_kwargs={"lazy": "raise"}
    )


class AsignacionRol(SQLModel, table=True):
    __tablename__ = "asignacion_rol"
    __table_args__ = (
        CheckConstraint("rol IN (" + _ROLES_SQL + ")", name="rol_valido"),
        Index(
            "uq_asignacion_rol_abierta",
            "usuario_id",
            "rol",
            unique=True,
            postgresql_where=text("revocada_en IS NULL"),
        ),
    )

    id: int | None = pk_identidad()
    usuario_id: int = fk("usuario.id", index=True)
    rol: str = texto()
    desde: datetime = fecha(server_default_now=True)
    vence_en: datetime | None = fecha(nullable=True)
    revocada_en: datetime | None = fecha(nullable=True)
    otorgada_por: int | None = fk("usuario.id", nullable=True, index=True)

    usuario: Optional["Usuario"] = Relationship(  # noqa: UP045
        back_populates="asignaciones", sa_relationship_kwargs={"lazy": "raise", "foreign_keys": "[AsignacionRol.usuario_id]"}
    )


class IntentoAcceso(SQLModel, table=True):
    __tablename__ = "intento_acceso"
    __table_args__ = (Index("ix_intento_acceso_email_ip_cuando", "email", "ip", "cuando"),)

    id: int | None = pk_identidad()
    cuando: datetime = fecha(server_default_now=True)
    email: str = texto()
    ip: str = texto()
    exito: bool = booleano()


class EventoSeguridad(SQLModel, table=True):
    __tablename__ = "evento_seguridad"

    id: int | None = pk_identidad()
    cuando: datetime = fecha(server_default_now=True)
    actor: str = texto()
    accion: str = texto()
