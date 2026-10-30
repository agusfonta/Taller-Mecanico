"""SoftDeleteRepository contra PostgreSQL real (D4)."""
from sqlalchemy import text

from app.core.repository import SoftDeleteRepository
from test.integration.modelos_prueba import ItemBorrable


def _repo(sesion):
    return SoftDeleteRepository(sesion, ItemBorrable)


async def test_soft_delete_oculta_en_get_list_y_count(fabrica_prueba):
    async with fabrica_prueba() as sesion:
        repo = _repo(sesion)
        a = await repo.add(ItemBorrable(nombre="a"))
        b = await repo.add(ItemBorrable(nombre="b"))
        await repo.soft_delete(a)
        assert await repo.get_by_id(a.id) is None
        assert [i.id for i in await repo.list(offset=0, limit=10)] == [b.id]
        assert await repo.count() == 1


async def test_incluyendo_borrados_devuelve_la_fila_con_zona_horaria(fabrica_prueba):
    async with fabrica_prueba() as sesion:
        repo = _repo(sesion)
        a = await repo.add(ItemBorrable(nombre="a"))
        await repo.soft_delete(a)
        fila = await repo.get_by_id_including_deleted(a.id)
        assert fila is not None and fila.borrado_en is not None
        assert fila.borrado_en.tzinfo is not None


async def test_baja_confirmada_no_elimina_la_fila(fabrica_prueba):
    async with fabrica_prueba() as sesion:
        repo = _repo(sesion)
        a = await repo.add(ItemBorrable(nombre="a"))
        await repo.soft_delete(a)
        id_ = a.id
        await sesion.commit()
    async with fabrica_prueba() as otra:
        valor = (
            await otra.execute(
                text("SELECT borrado_en FROM c02_item_borrable WHERE id = :id"), {"id": id_}
            )
        ).scalar_one()
    assert valor is not None and valor.tzinfo is not None


async def test_baja_con_rollback_reaparece_en_todo(fabrica_prueba):
    async with fabrica_prueba() as sesion:
        repo = _repo(sesion)
        a = await repo.add(ItemBorrable(nombre="a"))
        await sesion.commit()
        id_ = a.id
        await repo.soft_delete(a)
        await sesion.rollback()
        assert await repo.get_by_id(id_) is not None
        assert len(await repo.list(offset=0, limit=10)) == 1
        assert await repo.count() == 1


async def test_fila_no_borrada_sigue_visible(fabrica_prueba):
    async with fabrica_prueba() as sesion:
        repo = _repo(sesion)
        a = await repo.add(ItemBorrable(nombre="a"))
        assert (await repo.get_by_id(a.id)).borrado_en is None
        assert await repo.count() == 1
