"""Siembra y lectura con SQL ligado para los tests de C-09 (no pasa por la API)."""
from decimal import Decimal

from sqlalchemy import text

from test.integration.ayudantes_clientes import (  # noqa: F401  (reexportados)
    sembrar_catalogo,
    sembrar_cliente,
    sembrar_vehiculo,
)
from test.integration.repuestos.ayudantes import sembrar_repuesto  # noqa: F401

TABLAS_DE_ORDEN = ("orden_trabajo", "item_orden", "historial_estado_orden")


async def sembrar_orden_completa(
    db,
    vehiculo_id: int,
    estado: str = "PENDIENTE",
    *,
    mecanico_id: int | None = None,
    items: tuple[tuple[int, int, str], ...] = (),
    falla: str = "ruido",
) -> int:
    """Inserta una orden con ``items`` = ``(repuesto_id, cantidad, precio_unitario)``."""
    total = sum((Decimal(p) * c for _, c, p in items), Decimal("0"))
    async with db.motor.begin() as c:
        oid = (
            await c.execute(
                text(
                    "INSERT INTO orden_trabajo (vehiculo_id, mecanico_id, estado, falla, total) "
                    "VALUES (:v, :m, :e, :f, :t) RETURNING id"
                ),
                {"v": vehiculo_id, "m": mecanico_id, "e": estado, "f": falla, "t": total},
            )
        ).scalar_one()
        for repuesto_id, cantidad, precio in items:
            await c.execute(
                text(
                    "INSERT INTO item_orden (orden_id, repuesto_id, cantidad, precio_unitario) "
                    "VALUES (:o, :r, :c, :p)"
                ),
                {"o": oid, "r": repuesto_id, "c": cantidad, "p": Decimal(precio)},
            )
    return oid


async def conteos_de_orden(db) -> dict[str, int]:
    return await db.conteos(*TABLAS_DE_ORDEN)


async def historial_de_orden(db, orden_id: int) -> list[dict]:
    return await db.filas(
        "SELECT id, orden_id, desde_estado, hasta_estado, usuario_id FROM historial_estado_orden "
        "WHERE orden_id = :i ORDER BY id",
        i=orden_id,
    )


async def items_de_orden(db, orden_id: int) -> list[dict]:
    return await db.filas(
        "SELECT id, orden_id, repuesto_id, cantidad, precio_unitario FROM item_orden "
        "WHERE orden_id = :i ORDER BY repuesto_id",
        i=orden_id,
    )


async def fila_de_orden(db, orden_id: int) -> dict | None:
    filas = await db.filas("SELECT * FROM orden_trabajo WHERE id = :i", i=orden_id)
    return filas[0] if filas else None


# --- C-10: ciclo de vida -------------------------------------------------------------------


async def stock_de(db, repuesto_id: int) -> int:
    return (await db.filas("SELECT stock FROM repuesto WHERE id = :i", i=repuesto_id))[0]["stock"]


async def movimientos_de_orden(db, orden_id: int) -> list[dict]:
    return await db.filas(
        "SELECT id, repuesto_id, orden_id, usuario_id, cantidad, motivo FROM movimiento_stock "
        "WHERE orden_id = :i ORDER BY repuesto_id, id",
        i=orden_id,
    )


async def conteos_ciclo(db) -> dict:
    """Conteos de las tablas que tocan las transiciones mas el stock de cada repuesto."""
    cuentas: dict = await db.conteos("orden_trabajo", "historial_estado_orden", "movimiento_stock")
    filas = await db.filas("SELECT id, stock FROM repuesto ORDER BY id")
    cuentas["stocks"] = {f["id"]: f["stock"] for f in filas}
    return cuentas


async def _movimiento_inicial(db, repuesto_id: int, usuario_id: int, cantidad: int) -> None:
    await db.ejecutar(
        "INSERT INTO movimiento_stock (repuesto_id, usuario_id, cantidad, motivo) "
        "VALUES (:r, :u, :c, 'Stock inicial')",
        r=repuesto_id,
        u=usuario_id,
        c=cantidad,
    )


async def escenario_c11(db) -> dict:
    """Replica el seed de la KB 04: orden EN_REPARACION de Jorge con mas bujias de las que hay.

    Filtro (stock 10) con id menor que la bujia (stock 2); la orden pide 1 filtro y 4 bujias y
    esta asignada al mecanico, con su historial previo. Cada stock cargado como "Stock inicial".
    """
    await sembrar_catalogo(db)
    admin = await db.crear_usuario("admin-c11@example.com", "x" * 10, roles=("ADMIN",))
    mecanico = await db.crear_usuario("mecanico@example.com", "x" * 10, roles=("MECANICO",))
    cliente = await sembrar_cliente(db, "20111222", nombre="Jorge")
    vehiculo = await sembrar_vehiculo(db, cliente, "JJJ222")
    filtro = await sembrar_repuesto(db, codigo="FIL-001", precio="8500.00", stock=10)
    bujia = await sembrar_repuesto(db, codigo="BUJ-001", descripcion="Bujía", precio="3000.00", stock=2)
    await _movimiento_inicial(db, filtro, admin, 10)
    await _movimiento_inicial(db, bujia, admin, 2)
    orden = await sembrar_orden_completa(
        db,
        vehiculo,
        "EN_REPARACION",
        mecanico_id=mecanico,
        items=((filtro, 1, "8500.00"), (bujia, 4, "3000.00")),
    )
    for desde, hasta, quien in ((None, "PENDIENTE", admin), ("PENDIENTE", "EN_REPARACION", mecanico)):
        await db.ejecutar(
            "INSERT INTO historial_estado_orden (orden_id, desde_estado, hasta_estado, usuario_id) "
            "VALUES (:o, :d, :h, :u)",
            o=orden,
            d=desde,
            h=hasta,
            u=quien,
        )
    return {
        "orden": orden,
        "mecanico": mecanico,
        "admin": admin,
        "cliente": cliente,
        "vehiculo": vehiculo,
        "filtro": filtro,
        "bujia": bujia,
    }


def actor(uid: int, *roles) -> "UsuarioActual":
    """``UsuarioActual`` de prueba para llamar a los servicios sin pasar por HTTP."""
    from app.core.dependencies import UsuarioActual

    return UsuarioActual(
        id=uid,
        email=f"u{uid}@example.com",
        nombre="U",
        debe_cambiar_password=False,
        roles_vigentes=frozenset(roles),
        roles_token=tuple(r.value for r in roles),
    )


async def sembrar_historial(db, orden_id: int, desde: str | None, hasta: str, usuario_id: int) -> None:
    await db.ejecutar(
        "INSERT INTO historial_estado_orden (orden_id, desde_estado, hasta_estado, usuario_id) "
        "VALUES (:o, :d, :h, :u)",
        o=orden_id,
        d=desde,
        h=hasta,
        u=usuario_id,
    )
