"""Repositorios y UoW de clientes contra PostgreSQL real (C-07, tareas 3.x)."""
import pytest
from sqlalchemy import event

from app.core.database import crear_fabrica_sesiones
from app.modules.clientes.unit_of_work import ClientesUoW
from test.integration.ayudantes_clientes import (
    sembrar_catalogo,
    sembrar_cliente,
    sembrar_orden,
    sembrar_vehiculo,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def fabrica(motor_auth):
    return crear_fabrica_sesiones(motor_auth)


# --- get_con_vehiculos_vigentes (3.1) ------------------------------------------


async def test_cliente_con_solo_vehiculos_vigentes_y_precargados(fabrica, db_auth):
    cid = await sembrar_cliente(db_auth, "1")
    v1 = await sembrar_vehiculo(db_auth, cid, "AAA111")
    await sembrar_vehiculo(db_auth, cid, "BBB222", baja=True)
    v2 = await sembrar_vehiculo(db_auth, cid, "CCC333")
    async with fabrica() as sesion:
        async with ClientesUoW(sesion) as uow:
            cliente = await uow.clientes.get_con_vehiculos_vigentes(cid)
            assert cliente is not None
            assert sorted(v.id for v in cliente.vehiculos) == [v1, v2]  # sin lazy raise


async def test_cliente_sin_vehiculos_devuelve_lista_vacia(fabrica, db_auth):
    cid = await sembrar_cliente(db_auth, "2")
    async with fabrica() as sesion:
        async with ClientesUoW(sesion) as uow:
            assert (await uow.clientes.get_con_vehiculos_vigentes(cid)).vehiculos == []


async def test_cliente_inexistente_devuelve_none(fabrica):
    async with fabrica() as sesion:
        async with ClientesUoW(sesion) as uow:
            assert await uow.clientes.get_con_vehiculos_vigentes(999999) is None


# --- listar_vigentes_de_usuario (3.3) ---------------------------------------------


async def test_listar_vigentes_de_usuario_aisla_y_ordena(fabrica, db_auth):
    u1 = await db_auth.crear_usuario("a@example.com", "x" * 10)
    u2 = await db_auth.crear_usuario("b@example.com", "x" * 10)
    c1 = await sembrar_cliente(db_auth, "10", u1)
    c2 = await sembrar_cliente(db_auth, "11", u2)
    sin_usuario = await sembrar_cliente(db_auth, "12")
    a1 = await sembrar_vehiculo(db_auth, c1, "AAA222")
    a2 = await sembrar_vehiculo(db_auth, c1, "AAA111")
    await sembrar_vehiculo(db_auth, c1, "AAA333", baja=True)
    b1 = await sembrar_vehiculo(db_auth, c2, "BBB111")
    await sembrar_vehiculo(db_auth, sin_usuario, "ZZZ111")
    async with fabrica() as sesion:
        async with ClientesUoW(sesion) as uow:
            de_u1 = [v.id for v in await uow.vehiculos.listar_vigentes_de_usuario(u1)]
            de_u2 = [v.id for v in await uow.vehiculos.listar_vigentes_de_usuario(u2)]
    assert de_u1 == [a1, a2]  # por id
    assert de_u2 == [b1]


async def test_listar_vigentes_de_usuario_sin_ficha_es_vacio(fabrica, db_auth):
    uid = await db_auth.crear_usuario("c@example.com", "x" * 10, roles=("ADMIN",))
    cid = await sembrar_cliente(db_auth, "13")
    await sembrar_vehiculo(db_auth, cid, "QQQ111")
    async with fabrica() as sesion:
        async with ClientesUoW(sesion) as uow:
            assert list(await uow.vehiculos.listar_vigentes_de_usuario(uid)) == []


# --- tiene_ordenes_abiertas (3.4) ---------------------------------------------------


async def _abiertas(fabrica, vid) -> bool:
    async with fabrica() as sesion:
        async with ClientesUoW(sesion) as uow:
            return await uow.vehiculos.tiene_ordenes_abiertas(vid)


async def test_sin_ordenes_no_hay_abiertas(fabrica, db_auth):
    await sembrar_catalogo(db_auth)
    vid = await sembrar_vehiculo(db_auth, await sembrar_cliente(db_auth, "20"), "AAA111")
    assert await _abiertas(fabrica, vid) is False


@pytest.mark.parametrize("estado", ["PENDIENTE", "EN_REPARACION"])
async def test_orden_en_estado_no_final_cuenta_como_abierta(fabrica, db_auth, estado):
    await sembrar_catalogo(db_auth)
    vid = await sembrar_vehiculo(db_auth, await sembrar_cliente(db_auth, "21"), "AAA111")
    await sembrar_orden(db_auth, vid, estado)
    assert await _abiertas(fabrica, vid) is True


async def test_solo_ordenes_finales_no_cuentan(fabrica, db_auth):
    await sembrar_catalogo(db_auth)
    vid = await sembrar_vehiculo(db_auth, await sembrar_cliente(db_auth, "22"), "AAA111")
    await sembrar_orden(db_auth, vid, "TERMINADA")
    await sembrar_orden(db_auth, vid, "CANCELADA")
    assert await _abiertas(fabrica, vid) is False


async def test_ordenes_de_otro_vehiculo_no_cuentan(fabrica, db_auth):
    await sembrar_catalogo(db_auth)
    cid = await sembrar_cliente(db_auth, "23")
    v1 = await sembrar_vehiculo(db_auth, cid, "AAA111")
    v2 = await sembrar_vehiculo(db_auth, cid, "BBB222")
    await sembrar_orden(db_auth, v2, "PENDIENTE")
    assert await _abiertas(fabrica, v1) is False


@pytest.mark.parametrize(("es_final", "esperado"), [(True, False), (False, True)])
async def test_el_catalogo_decide_con_estado_de_nombre_arbitrario(fabrica, db_auth, es_final, esperado):
    await sembrar_catalogo(db_auth, (("EN_REVISION_X", 9, es_final),))
    vid = await sembrar_vehiculo(db_auth, await sembrar_cliente(db_auth, "24"), "AAA111")
    await sembrar_orden(db_auth, vid, "EN_REVISION_X")
    assert await _abiertas(fabrica, vid) is esperado


# --- get_vigente_para_baja (3.5) ------------------------------------------------------


async def test_get_vigente_para_baja_devuelve_vigente(fabrica, db_auth):
    vid = await sembrar_vehiculo(db_auth, await sembrar_cliente(db_auth, "30"), "AAA111")
    async with fabrica() as sesion:
        async with ClientesUoW(sesion) as uow:
            v = await uow.vehiculos.get_vigente_para_baja(vid)
            assert v is not None and v.id == vid


async def test_get_vigente_para_baja_none_si_baja_o_inexistente(fabrica, db_auth):
    vid = await sembrar_vehiculo(db_auth, await sembrar_cliente(db_auth, "31"), "AAA111", baja=True)
    async with fabrica() as sesion:
        async with ClientesUoW(sesion) as uow:
            assert await uow.vehiculos.get_vigente_para_baja(vid) is None
            assert await uow.vehiculos.get_vigente_para_baja(999999) is None


async def test_get_vigente_para_baja_emite_for_update(fabrica, db_auth, motor_auth):
    vid = await sembrar_vehiculo(db_auth, await sembrar_cliente(db_auth, "32"), "AAA111")
    sentencias: list[str] = []

    def capturar(conn, cursor, statement, parameters, context, executemany):
        sentencias.append(statement)

    event.listen(motor_auth.sync_engine, "before_cursor_execute", capturar)
    try:
        async with fabrica() as sesion:
            async with ClientesUoW(sesion) as uow:
                await uow.vehiculos.get_vigente_para_baja(vid)
    finally:
        event.remove(motor_auth.sync_engine, "before_cursor_execute", capturar)
    selects = [s for s in sentencias if "FROM vehiculo" in s]
    assert len(selects) == 1 and "FOR UPDATE" in selects[0]
    assert "borrado_en IS NULL" in selects[0]
