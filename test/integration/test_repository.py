"""BaseRepository contra PostgreSQL real: escribe con flush, nunca confirma (D4)."""
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.repository import BaseRepository
from test.integration.modelos_prueba import ItemPrueba


def _repo(sesion):
    return BaseRepository(sesion, ItemPrueba)


async def _contar_en_otra_sesion(fabrica):
    async with fabrica() as otra:
        return (await otra.execute(select(func.count()).select_from(ItemPrueba))).scalar_one()


async def test_add_asigna_id_visible_en_la_misma_sesion_pero_no_en_otra(fabrica_prueba):
    async with fabrica_prueba() as sesion:
        repo = _repo(sesion)
        item = await repo.add(ItemPrueba(nombre="a", precio=Decimal("1.50")))
        assert item.id is not None
        assert (await repo.get_by_id(item.id)) is item
        async with fabrica_prueba() as otra:
            assert await _repo(otra).get_by_id(item.id) is None
        assert await _contar_en_otra_sesion(fabrica_prueba) == 0


async def test_add_y_rollback_deja_la_base_vacia(fabrica_prueba):
    async with fabrica_prueba() as sesion:
        await _repo(sesion).add(ItemPrueba(nombre="a"))
        await sesion.rollback()
    assert await _contar_en_otra_sesion(fabrica_prueba) == 0


async def test_get_by_id_inexistente_devuelve_none(fabrica_prueba):
    async with fabrica_prueba() as sesion:
        assert await _repo(sesion).get_by_id(999_999) is None


async def test_list_y_count(fabrica_prueba):
    async with fabrica_prueba() as sesion:
        repo = _repo(sesion)
        items = [await repo.add(ItemPrueba(nombre=f"n{i}")) for i in range(5)]
        ids = sorted(i.id for i in items)
        pagina = await repo.list(offset=2, limit=2)
        assert [i.id for i in pagina] == ids[2:4]
        assert await repo.count() == 5
        assert await repo.list(offset=10, limit=2) == []
        assert [i.id for i in await repo.list(offset=0, limit=100)] == ids


async def test_update_cambia_solo_lo_indicado(fabrica_prueba):
    async with fabrica_prueba() as sesion:
        repo = _repo(sesion)
        item = await repo.add(ItemPrueba(nombre="a", precio=Decimal("9.99")))
        actualizado = await repo.update(item, {"nombre": "b"})
        assert actualizado.nombre == "b"
        assert actualizado.precio == Decimal("9.99")
        assert isinstance(actualizado.precio, Decimal)


async def test_update_clave_desconocida_lanza_y_no_cambia_nada(fabrica_prueba):
    async with fabrica_prueba() as sesion:
        repo = _repo(sesion)
        item = await repo.add(ItemPrueba(nombre="a", precio=Decimal("1.00")))
        with pytest.raises(ValueError):
            await repo.update(item, {"nombre": "cambiado", "no_existe": 1})
        assert item.nombre == "a"
        await sesion.flush()
        await sesion.refresh(item)
        assert item.nombre == "a"


async def test_update_y_rollback_restaura_el_valor(fabrica_prueba):
    async with fabrica_prueba() as sesion:
        repo = _repo(sesion)
        item = await repo.add(ItemPrueba(nombre="a"))
        await sesion.commit()
        id_ = item.id
        await repo.update(item, {"nombre": "b"})
        await sesion.rollback()
        assert (await repo.get_by_id(id_)).nombre == "a"


async def test_delete_desaparece_y_rollback_reaparece(fabrica_prueba):
    async with fabrica_prueba() as sesion:
        repo = _repo(sesion)
        item = await repo.add(ItemPrueba(nombre="a"))
        await sesion.commit()
        id_ = item.id
        await repo.delete(item)
        assert await repo.get_by_id(id_) is None
        await sesion.rollback()
        assert await repo.get_by_id(id_) is not None
