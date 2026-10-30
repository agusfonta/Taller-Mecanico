"""Siembra con SQL ligado para los tests de C-07 (clientes, vehiculos, catalogo y ordenes).

Las ordenes no tienen API hasta C-09: se insertan directo. Funciones sueltas sobre
``db_auth`` (``AyudantesAuth``) para no ampliar el ``conftest.py`` compartido.
"""
from datetime import UTC, datetime

CATALOGO = (
    ("PENDIENTE", 1, False),
    ("EN_REPARACION", 2, False),
    ("TERMINADA", 3, True),
    ("CANCELADA", 4, True),
)


async def sembrar_catalogo(db, estados=CATALOGO) -> None:
    for codigo, posicion, es_final in estados:
        await db.ejecutar(
            "INSERT INTO estado_orden (codigo, descripcion, posicion, es_final) "
            "VALUES (:c, :c, :p, :f) ON CONFLICT (codigo) DO NOTHING",
            c=codigo,
            p=posicion,
            f=es_final,
        )


async def sembrar_cliente(db, documento: str, usuario_id: int | None = None, nombre: str = "Cliente") -> int:
    async with db.motor.begin() as c:
        from sqlalchemy import text

        return (
            await c.execute(
                text(
                    "INSERT INTO cliente (usuario_id, nombre, documento, telefono) "
                    "VALUES (:u, :n, :d, '555') RETURNING id"
                ),
                {"u": usuario_id, "n": nombre, "d": documento},
            )
        ).scalar_one()


async def sembrar_vehiculo(
    db, cliente_id: int, patente: str, *, baja: bool = False, marca: str = "Fiat", anio: int = 2020
) -> int:
    from sqlalchemy import text

    async with db.motor.begin() as c:
        return (
            await c.execute(
                text(
                    "INSERT INTO vehiculo (cliente_id, patente, marca, modelo, anio, borrado_en) "
                    "VALUES (:c, :p, :m, 'Uno', :a, :b) RETURNING id"
                ),
                {
                    "c": cliente_id,
                    "p": patente,
                    "m": marca,
                    "a": anio,
                    "b": datetime.now(UTC) if baja else None,
                },
            )
        ).scalar_one()


async def sembrar_orden(db, vehiculo_id: int, estado: str) -> int:
    from sqlalchemy import text

    async with db.motor.begin() as c:
        return (
            await c.execute(
                text(
                    "INSERT INTO orden_trabajo (vehiculo_id, estado, falla) "
                    "VALUES (:v, :e, 'ruido') RETURNING id"
                ),
                {"v": vehiculo_id, "e": estado},
            )
        ).scalar_one()


def cabecera(uid: int, roles, settings) -> dict[str, str]:
    """Cookie de sesion firmada (sin bcrypt por peticion); los roles del token son informativos."""
    from app.core.security import emitir_token

    return {"Cookie": f"access_token={emitir_token(uid, list(roles), settings)}"}


async def personal(db, settings, rol: str = "RECEPCION", email: str | None = None):
    """Siembra un usuario con ``rol`` y devuelve ``(id, cabecera)``."""
    uid = await db.crear_usuario(email or f"{rol.lower()}@example.com", "x" * 10, roles=(rol,))
    return uid, cabecera(uid, (rol,), settings)
