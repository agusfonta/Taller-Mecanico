"""Ayudantes de los tests del seed (C-11): captura del estado de las 13 tablas.

``snapshot`` omite las marcas de tiempo y los hashes de contraseña: el seed los recalcula en cada
corrida (``now()``, sal nueva) y la idempotencia se define sin ellos (spec ``datos-iniciales``).
"""
from test.integration.conftest import tablas_de_negocio

COLUMNAS_SIN_COMPARAR = "password_hash"


async def snapshot(db) -> dict[str, list[tuple]]:
    """Contenido de las 13 tablas ordenado por la primera columna (id o codigo)."""
    capturado: dict[str, list[tuple]] = {}
    for tabla in tablas_de_negocio():
        columnas = [
            f["column_name"]
            for f in await db.filas(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = :t "
                "AND data_type NOT LIKE 'timestamp%' AND column_name <> :h "
                "ORDER BY ordinal_position",
                t=tabla,
                h=COLUMNAS_SIN_COMPARAR,
            )
        ]
        lista = ", ".join(f'"{c}"' for c in columnas)
        # tabla y columnas salen de la metadata / information_schema, nunca de la entrada del usuario
        filas = await db.filas(f'SELECT {lista} FROM "{tabla}" ORDER BY 1')
        capturado[tabla] = [tuple(f[c] for c in columnas) for f in filas]
    return capturado
