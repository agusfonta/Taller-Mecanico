"""UnitOfWork contra PostgreSQL real."""
import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError

from app.core.database import SessionDep, get_session
from app.core.repository import BaseRepository, SoftDeleteRepository
from app.core.unit_of_work import UnitOfWork
from test.integration.modelos_prueba import ItemBorrable, ItemPrueba


class ModuloUoW(UnitOfWork):
    def __init__(self, session):
        super().__init__(session)
        self.items = BaseRepository(session, ItemPrueba)
        self.borrables = SoftDeleteRepository(session, ItemBorrable)


async def _contar(fabrica, modelo=ItemPrueba):
    async with fabrica() as otra:
        return (await otra.execute(select(func.count()).select_from(modelo))).scalar_one()


async def test_bloque_sin_error_confirma_y_es_visible_desde_otra_sesion(fabrica_prueba):
    async with fabrica_prueba() as sesion:
        async with ModuloUoW(sesion) as uow:
            await uow.items.add(ItemPrueba(nombre="a"))
    assert await _contar(fabrica_prueba) == 1


async def test_excepcion_en_bloque_propaga_y_no_persiste(fabrica_prueba):
    error = RuntimeError("boom")
    async with fabrica_prueba() as sesion:
        with pytest.raises(RuntimeError) as info:
            async with ModuloUoW(sesion) as uow:
                await uow.items.add(ItemPrueba(nombre="a"))
                raise error
        assert info.value is error
    assert await _contar(fabrica_prueba) == 0


async def test_falla_al_confirmar_propaga_integrity_error_y_sesion_sigue_usable(fabrica_prueba):
    async with fabrica_prueba() as sesion:
        with pytest.raises(IntegrityError):
            async with ModuloUoW(sesion) as uow:
                await uow.items.add(ItemPrueba(nombre="dup"))
                await uow.items.add(ItemPrueba(nombre="dup"))  # el flush pasa (UNIQUE diferido)
        assert await _contar(fabrica_prueba) == 0
        async with ModuloUoW(sesion) as uow:
            await uow.items.add(ItemPrueba(nombre="otro"))
    assert await _contar(fabrica_prueba) == 1


async def test_no_cierra_la_sesion_y_atributos_legibles_sin_consultas(fabrica_prueba, motor_prueba):
    sentencias: list[str] = []

    def espiar(conn, cursor, statement, *args):
        sentencias.append(statement)

    async with fabrica_prueba() as sesion:
        async with ModuloUoW(sesion) as uow:
            item = await uow.items.add(ItemPrueba(nombre="a"))
        event.listen(motor_prueba.sync_engine, "before_cursor_execute", espiar)
        try:
            assert item.id is not None
            assert item.nombre == "a"
        finally:
            event.remove(motor_prueba.sync_engine, "before_cursor_execute", espiar)
        assert sentencias == []
        async with ModuloUoW(sesion) as uow:  # misma sesion, nuevo bloque
            await uow.items.add(ItemPrueba(nombre="b"))
    assert await _contar(fabrica_prueba) == 2


async def test_uow_de_modulo_dos_repositorios_atomicos(fabrica_prueba):
    async with fabrica_prueba() as sesion:
        with pytest.raises(RuntimeError):
            async with ModuloUoW(sesion) as uow:
                await uow.items.add(ItemPrueba(nombre="a"))
                await uow.borrables.add(ItemBorrable(nombre="b"))
                raise RuntimeError
    assert await _contar(fabrica_prueba) == 0
    assert await _contar(fabrica_prueba, ItemBorrable) == 0


async def test_uow_de_modulo_sin_error_confirma_ambos(fabrica_prueba):
    async with fabrica_prueba() as sesion:
        async with ModuloUoW(sesion) as uow:
            await uow.items.add(ItemPrueba(nombre="a"))
            await uow.borrables.add(ItemBorrable(nombre="b"))
    assert await _contar(fabrica_prueba) == 1
    assert await _contar(fabrica_prueba, ItemBorrable) == 1


def _app(fabrica):
    import main

    router = APIRouter()

    def get_uow(session: SessionDep) -> ModuloUoW:
        return ModuloUoW(session)

    @router.post("/items/{nombre}")
    async def crear(nombre: str, uow: ModuloUoW = Depends(get_uow)):
        async with uow:
            item = await uow.items.add(ItemPrueba(nombre=nombre))
            return {"id": item.id}

    @router.post("/falla/{nombre}")
    async def falla(nombre: str, uow: ModuloUoW = Depends(get_uow)):
        async with uow:
            await uow.items.add(ItemPrueba(nombre=nombre))
            raise RuntimeError("falla controlada del test")

    app = main.crear_app(abiertos=[router])

    async def sesion_de_prueba():
        async with fabrica() as sesion:
            yield sesion

    app.dependency_overrides[get_session] = sesion_de_prueba
    return app


async def test_http_post_persiste_y_ruta_que_falla_no_persiste(fabrica_prueba):
    import httpx

    app = _app(fabrica_prueba)
    transporte = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transporte, base_url="http://t") as cliente:
        ok = await cliente.post("/items/uno")
        assert ok.status_code == 200
        assert ok.json()["id"] is not None
        malo = await cliente.post("/falla/dos")
        assert malo.status_code == 500
    async with fabrica_prueba() as otra:
        nombres = (await otra.execute(select(ItemPrueba.nombre))).scalars().all()
    assert nombres == ["uno"]
