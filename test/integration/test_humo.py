"""Humo: el andamiaje de integracion funciona contra PostgreSQL real."""
from sqlalchemy import text


async def test_select_1_en_esquema_efimero(fabrica_prueba, esquema_prueba):
    async with fabrica_prueba() as sesion:
        assert (await sesion.execute(text("SELECT 1"))).scalar_one() == 1
        actual = (await sesion.execute(text("SELECT current_schema()"))).scalar_one()
    assert actual == esquema_prueba
    assert esquema_prueba.startswith("c02_prueba_")


async def test_tablas_de_prueba_creadas_solo_en_el_esquema_efimero(fabrica_prueba, esquema_prueba):
    async with fabrica_prueba() as sesion:
        filas = (
            await sesion.execute(
                text("SELECT table_name FROM information_schema.tables WHERE table_schema = :s"),
                {"s": esquema_prueba},
            )
        ).scalars().all()
    assert {"c02_item_prueba", "c02_item_borrable", "c02_item_pk_compuesta"} <= set(filas)
