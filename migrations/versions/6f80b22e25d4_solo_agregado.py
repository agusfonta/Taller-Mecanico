"""solo agregado

Escrita a mano: autogenerate no detecta funciones ni disparadores (C-03, KB 04
seccion Migraciones). Instala la proteccion de solo agregado (RN-15): una funcion y un
disparador BEFORE UPDATE OR DELETE FOR EACH ROW sobre historial_estado_orden,
movimiento_stock e historial_precio_repuesto.

- Por fila: un UPDATE/DELETE que no afecta filas no falla; si afecta alguna, falla.
- TRUNCATE NO se bloquea (los disparadores de fila no corren en TRUNCATE): seed.py
  (C-11) vacia con TRUNCATE ... RESTART IDENTITY CASCADE.
- ERRCODE P0001 (raise_exception): llega como error de base de datos generico, nunca
  como IntegrityError, para que no se traduzca a un 409 por error.
- Las tablas se listan aca (no se importan los modelos): una migracion no debe
  depender del codigo vivo.

Revision ID: 6f80b22e25d4
Revises: acf6d613aa1c
Create Date: 2026-10-27 09:40:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '6f80b22e25d4'
down_revision: Union[str, Sequence[str], None] = 'acf6d613aa1c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLAS_SOLO_AGREGADO = (
    "historial_estado_orden",
    "movimiento_stock",
    "historial_precio_repuesto",
)

CREAR_FUNCION = """
CREATE FUNCTION rechazar_modificacion_solo_agregado() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'La tabla % es de sólo agregado: % no permitido', TG_TABLE_NAME, TG_OP
    USING ERRCODE = 'P0001';
END
$$
"""


def upgrade() -> None:
    """Upgrade schema: funcion + un disparador por tabla de solo agregado."""
    op.execute(CREAR_FUNCION)
    for tabla in TABLAS_SOLO_AGREGADO:
        op.execute(
            f"CREATE TRIGGER solo_agregado_{tabla} BEFORE UPDATE OR DELETE ON {tabla} "
            "FOR EACH ROW EXECUTE FUNCTION rechazar_modificacion_solo_agregado()"
        )


def downgrade() -> None:
    """Downgrade schema: elimina los disparadores y la funcion."""
    for tabla in reversed(TABLAS_SOLO_AGREGADO):
        op.execute(f"DROP TRIGGER solo_agregado_{tabla} ON {tabla}")
    op.execute("DROP FUNCTION rechazar_modificacion_solo_agregado()")
