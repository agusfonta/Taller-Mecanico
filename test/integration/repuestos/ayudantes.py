"""Siembra y lectura con SQL ligado para los tests de C-08 (no pasa por la API)."""
from datetime import UTC, datetime
from decimal import Decimal


async def sembrar_repuesto(
    db,
    codigo: str = "FIL-001",
    descripcion: str = "Filtro de aceite",
    precio: Decimal | str = "8000.00",
    stock: int = 0,
    borrado: bool = False,
) -> int:
    """Inserta un repuesto directo (sin movimiento: el invariante no aplica a lo sembrado)."""
    from sqlalchemy import text

    async with db.motor.begin() as c:
        return (
            await c.execute(
                text(
                    "INSERT INTO repuesto (codigo, descripcion, precio, stock, borrado_en) "
                    "VALUES (:c, :d, :p, :s, :b) RETURNING id"
                ),
                {
                    "c": codigo,
                    "d": descripcion,
                    "p": Decimal(str(precio)),
                    "s": stock,
                    "b": datetime.now(UTC) if borrado else None,
                },
            )
        ).scalar_one()


async def movimientos_de(db, repuesto_id: int) -> list[dict]:
    return await db.filas(
        "SELECT id, repuesto_id, orden_id, usuario_id, cantidad, motivo FROM movimiento_stock "
        "WHERE repuesto_id = :i ORDER BY id",
        i=repuesto_id,
    )


async def historial_de(db, repuesto_id: int) -> list[dict]:
    return await db.filas(
        "SELECT id, repuesto_id, usuario_id, precio_anterior, precio_nuevo FROM historial_precio_repuesto "
        "WHERE repuesto_id = :i ORDER BY id",
        i=repuesto_id,
    )


async def fila_de(db, repuesto_id: int) -> dict | None:
    filas = await db.filas("SELECT * FROM repuesto WHERE id = :i", i=repuesto_id)
    return filas[0] if filas else None
