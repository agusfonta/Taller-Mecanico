"""Modelos de tabla de clientes y vehiculos (C-03, D1)."""
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, Index, UniqueConstraint, text
from sqlmodel import Relationship, SQLModel

from app.core.models import entero, fecha, fk, pk_identidad, texto

if TYPE_CHECKING:
    from app.modules.ordenes.models import OrdenTrabajo
    from app.modules.usuarios.models import Usuario

__all__ = ["Cliente", "Vehiculo"]


class Cliente(SQLModel, table=True):
    __tablename__ = "cliente"
    # UNIQUE(usuario_id) cubre la FK como primer campo: no lleva indice propio.
    __table_args__ = (UniqueConstraint("documento"), UniqueConstraint("usuario_id"))

    id: int | None = pk_identidad()
    usuario_id: int | None = fk("usuario.id", nullable=True)
    nombre: str = texto()
    documento: str = texto()
    telefono: str = texto()

    # lazy="raise": precargar en el repositorio con selectinload/joinedload.
    usuario: Optional["Usuario"] = Relationship(  # noqa: UP045
        back_populates="cliente", sa_relationship_kwargs={"lazy": "raise"}
    )
    vehiculos: list["Vehiculo"] = Relationship(
        back_populates="cliente", sa_relationship_kwargs={"lazy": "raise"}
    )


class Vehiculo(SQLModel, table=True):
    __tablename__ = "vehiculo"
    __table_args__ = (
        CheckConstraint("anio BETWEEN 1950 AND 2100", name="anio_rango"),
        Index(
            "uq_vehiculo_patente_vigente",
            "patente",
            unique=True,
            postgresql_where=text("borrado_en IS NULL"),
        ),
    )

    id: int | None = pk_identidad()
    cliente_id: int = fk("cliente.id", index=True)
    patente: str = texto()
    marca: str = texto()
    modelo: str = texto()
    anio: int = entero()
    borrado_en: datetime | None = fecha(nullable=True)

    # lazy="raise": precargar en el repositorio con selectinload/joinedload.
    cliente: Optional["Cliente"] = Relationship(  # noqa: UP045
        back_populates="vehiculos", sa_relationship_kwargs={"lazy": "raise"}
    )
    ordenes: list["OrdenTrabajo"] = Relationship(
        back_populates="vehiculo", sa_relationship_kwargs={"lazy": "raise"}
    )
