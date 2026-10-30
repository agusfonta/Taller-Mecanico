"""Modelos de tabla de ordenes de trabajo (C-03, D1).

``estado_orden`` es un catalogo (PK textual ``codigo``) que carga ``seed.py``;
``historial_estado_orden`` es de solo agregado.
"""
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, Text, UniqueConstraint
from sqlmodel import Relationship, SQLModel

from app.core.models import booleano, dinero, entero, fecha, fk, pk_identidad, texto

if TYPE_CHECKING:
    from app.modules.clientes.models import Vehiculo
    from app.modules.repuestos.models import Repuesto
    from app.modules.usuarios.models import Usuario

__all__ = ["EstadoOrdenCodigo", "EstadoOrden", "OrdenTrabajo", "ItemOrden", "HistorialEstadoOrden"]


class EstadoOrdenCodigo(StrEnum):
    """Vocabulario de estados (DD-02); el catalogo ``estado_orden`` sigue siendo la fuente de verdad."""

    PENDIENTE = "PENDIENTE"
    EN_REPARACION = "EN_REPARACION"
    TERMINADA = "TERMINADA"
    CANCELADA = "CANCELADA"


class EstadoOrden(SQLModel, table=True):
    __tablename__ = "estado_orden"
    __table_args__ = (UniqueConstraint("posicion"),)

    codigo: str = texto(primary_key=True)
    descripcion: str = texto()
    posicion: int = entero()
    es_final: bool = booleano()

    # lazy="raise": precargar en el repositorio con selectinload/joinedload.
    ordenes: list["OrdenTrabajo"] = Relationship(
        back_populates="estado_orden", sa_relationship_kwargs={"lazy": "raise"}
    )


class OrdenTrabajo(SQLModel, table=True):
    __tablename__ = "orden_trabajo"
    __table_args__ = (CheckConstraint("total >= 0", name="total_no_negativo"),)

    id: int | None = pk_identidad()
    vehiculo_id: int = fk("vehiculo.id", index=True)
    mecanico_id: int | None = fk("usuario.id", nullable=True, index=True)
    estado: str = fk("estado_orden.codigo", tipo=Text, index=True)
    falla: str = texto()
    creada_en: datetime = fecha(server_default_now=True)
    total: Decimal = dinero(12, 2, cero_por_defecto=True)

    # lazy="raise": precargar en el repositorio con selectinload/joinedload.
    # La columna se llama estado (nombre obligatorio): la relacion es estado_orden.
    vehiculo: Optional["Vehiculo"] = Relationship(  # noqa: UP045
        back_populates="ordenes", sa_relationship_kwargs={"lazy": "raise"}
    )
    mecanico: Optional["Usuario"] = Relationship(  # noqa: UP045
        back_populates="ordenes_asignadas", sa_relationship_kwargs={"lazy": "raise"}
    )
    estado_orden: Optional["EstadoOrden"] = Relationship(  # noqa: UP045
        back_populates="ordenes", sa_relationship_kwargs={"lazy": "raise"}
    )
    items: list["ItemOrden"] = Relationship(
        back_populates="orden", sa_relationship_kwargs={"lazy": "raise"}
    )
    historial: list["HistorialEstadoOrden"] = Relationship(
        back_populates="orden", sa_relationship_kwargs={"lazy": "raise"}
    )


class ItemOrden(SQLModel, table=True):
    __tablename__ = "item_orden"
    # UNIQUE(orden_id, repuesto_id) cubre orden_id como primer campo: sin indice propio.
    __table_args__ = (
        CheckConstraint("cantidad > 0", name="cantidad_positiva"),
        CheckConstraint("precio_unitario > 0", name="precio_unitario_positivo"),
        UniqueConstraint("orden_id", "repuesto_id"),
    )

    id: int | None = pk_identidad()
    orden_id: int = fk("orden_trabajo.id")
    repuesto_id: int = fk("repuesto.id", index=True)
    cantidad: int = entero()
    precio_unitario: Decimal = dinero(10, 2)

    # lazy="raise": precargar en el repositorio con selectinload/joinedload.
    orden: Optional["OrdenTrabajo"] = Relationship(  # noqa: UP045
        back_populates="items", sa_relationship_kwargs={"lazy": "raise"}
    )
    repuesto: Optional["Repuesto"] = Relationship(  # noqa: UP045
        back_populates="items_orden", sa_relationship_kwargs={"lazy": "raise"}
    )


class HistorialEstadoOrden(SQLModel, table=True):
    __tablename__ = "historial_estado_orden"

    id: int | None = pk_identidad()
    orden_id: int = fk("orden_trabajo.id", index=True)
    desde_estado: str | None = fk("estado_orden.codigo", tipo=Text, nullable=True, index=True)
    hasta_estado: str = fk("estado_orden.codigo", tipo=Text, index=True)
    usuario_id: int = fk("usuario.id", index=True)
    cuando: datetime = fecha(server_default_now=True)

    orden: Optional["OrdenTrabajo"] = Relationship(  # noqa: UP045
        back_populates="historial", sa_relationship_kwargs={"lazy": "raise"}
    )
