"""Modelos de tabla de inventario (C-03, D1). Movimientos e historial son de solo agregado."""
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, Index, text
from sqlmodel import Relationship, SQLModel

from app.core.models import dinero, entero, fecha, fk, pk_identidad, texto

if TYPE_CHECKING:
    from app.modules.ordenes.models import ItemOrden

__all__ = ["Repuesto", "MovimientoStock", "HistorialPrecioRepuesto"]


class Repuesto(SQLModel, table=True):
    __tablename__ = "repuesto"
    __table_args__ = (
        CheckConstraint("precio > 0", name="precio_positivo"),
        CheckConstraint("stock >= 0", name="stock_no_negativo"),
        Index(
            "uq_repuesto_codigo_vigente",
            "codigo",
            unique=True,
            postgresql_where=text("borrado_en IS NULL"),
        ),
    )

    id: int | None = pk_identidad()
    codigo: str = texto()
    descripcion: str = texto()
    precio: Decimal = dinero(10, 2)
    stock: int = entero(server_default="0", default=0)
    borrado_en: datetime | None = fecha(nullable=True)

    # lazy="raise": precargar en el repositorio con selectinload/joinedload.
    movimientos: list["MovimientoStock"] = Relationship(
        back_populates="repuesto", sa_relationship_kwargs={"lazy": "raise"}
    )
    historial_precios: list["HistorialPrecioRepuesto"] = Relationship(
        back_populates="repuesto", sa_relationship_kwargs={"lazy": "raise"}
    )
    items_orden: list["ItemOrden"] = Relationship(
        back_populates="repuesto", sa_relationship_kwargs={"lazy": "raise"}
    )


class MovimientoStock(SQLModel, table=True):
    __tablename__ = "movimiento_stock"
    __table_args__ = (CheckConstraint("cantidad <> 0", name="cantidad_distinta_de_cero"),)

    id: int | None = pk_identidad()
    repuesto_id: int = fk("repuesto.id", index=True)
    orden_id: int | None = fk("orden_trabajo.id", nullable=True, index=True)
    usuario_id: int = fk("usuario.id", index=True)
    cantidad: int = entero()
    motivo: str = texto()
    cuando: datetime = fecha(server_default_now=True)

    repuesto: Optional["Repuesto"] = Relationship(  # noqa: UP045
        back_populates="movimientos", sa_relationship_kwargs={"lazy": "raise"}
    )


class HistorialPrecioRepuesto(SQLModel, table=True):
    __tablename__ = "historial_precio_repuesto"
    __table_args__ = (
        CheckConstraint("precio_nuevo > 0", name="precio_nuevo_positivo"),
        CheckConstraint("precio_nuevo <> precio_anterior", name="precio_nuevo_distinto"),
    )

    id: int | None = pk_identidad()
    repuesto_id: int = fk("repuesto.id", index=True)
    usuario_id: int = fk("usuario.id", index=True)
    precio_anterior: Decimal = dinero(10, 2)
    precio_nuevo: Decimal = dinero(10, 2)
    cuando: datetime = fecha(server_default_now=True)

    repuesto: Optional["Repuesto"] = Relationship(  # noqa: UP045
        back_populates="historial_precios", sa_relationship_kwargs={"lazy": "raise"}
    )
