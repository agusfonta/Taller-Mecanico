"""Bloqueo de la orden por transiciones: ``OrdenRepository.bloquear`` (C-10, D2, tareas 3.1 y 3.2)."""
import asyncio

import pytest
from sqlalchemy import event

from app.modules.ordenes.unit_of_work import OrdenesUoW
from test.integration.ordenes.ayudantes import (
    sembrar_catalogo,
    sembrar_cliente,
    sembrar_orden_completa,
    sembrar_vehiculo,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def sentencias(motor_auth):
    capturadas: list[tuple[str, object]] = []

    def capturar(conn, cursor, statement, parameters, context, executemany):
        capturadas.append((statement, parameters))

    event.listen(motor_auth.sync_engine, "before_cursor_execute", capturar)
    yield capturadas
    event.remove(motor_auth.sync_engine, "before_cursor_execute", capturar)


@pytest.fixture
async def vehiculo(db_auth) -> int:
    await sembrar_catalogo(db_auth)
    return await sembrar_vehiculo(db_auth, await sembrar_cliente(db_auth, "10"), "AAA111")


async def test_bloquear_devuelve_la_orden_sin_relaciones(fabrica, db_auth, vehiculo):
    oid = await sembrar_orden_completa(db_auth, vehiculo, "PENDIENTE")
    async with fabrica() as sesion:
        async with OrdenesUoW(sesion) as uow:
            orden = await uow.ordenes.bloquear(oid)
            assert orden is not None and orden.id == oid and orden.estado == "PENDIENTE"
            assert "items" not in orden.__dict__ and "historial" not in orden.__dict__
            assert "vehiculo" not in orden.__dict__


async def test_bloquear_devuelve_none_si_no_existe(fabrica, vehiculo):
    async with fabrica() as sesion:
        async with OrdenesUoW(sesion) as uow:
            assert await uow.ordenes.bloquear(9999) is None


async def test_bloquear_es_una_sola_sentencia_for_update_con_el_id_ligado(fabrica, db_auth, vehiculo, sentencias):
    oid = await sembrar_orden_completa(db_auth, vehiculo, "PENDIENTE")
    async with fabrica() as sesion:
        async with OrdenesUoW(sesion) as uow:
            sentencias.clear()
            await uow.ordenes.bloquear(oid)
            propias = [s for s in sentencias if "orden_trabajo" in s[0]]
    assert len(propias) == 1
    sql, parametros = propias[0]
    assert "FOR UPDATE" in sql.upper() and "FOR SHARE" not in sql.upper()
    assert "JOIN" not in sql.upper()
    assert tuple(parametros) == (oid,) and "$1" in sql and f"= {oid} " not in sql


async def test_bloquear_ordenes_distintas_devuelve_cada_una(fabrica, db_auth, vehiculo):
    a = await sembrar_orden_completa(db_auth, vehiculo, "PENDIENTE")
    b = await sembrar_orden_completa(db_auth, vehiculo, "TERMINADA")
    async with fabrica() as sesion:
        async with OrdenesUoW(sesion) as uow:
            assert (await uow.ordenes.bloquear(b)).estado == "TERMINADA"
            assert (await uow.ordenes.bloquear(a)).estado == "PENDIENTE"


# --- 3.2: dos sesiones reales ----------------------------------------------------------


async def test_la_segunda_sesion_espera_y_lee_el_estado_ya_confirmado(fabrica, db_auth, vehiculo):
    oid = await sembrar_orden_completa(db_auth, vehiculo, "PENDIENTE")
    async with fabrica() as sesion_a, fabrica() as sesion_b:
        uow_a, uow_b = OrdenesUoW(sesion_a), OrdenesUoW(sesion_b)
        async with uow_b:
            # B ya conoce la orden con el estado viejo en su mapa de identidad.
            vieja = await uow_b.ordenes.get_by_id(oid)
            assert vieja.estado == "PENDIENTE"

            async with uow_a:
                en_a = await uow_a.ordenes.bloquear(oid)
                await uow_a.ordenes.update(en_a, {"estado": "EN_REPARACION"})  # sin confirmar

                tarea_b = asyncio.create_task(uow_b.ordenes.bloquear(oid))
                await asyncio.sleep(0.5)
                assert not tarea_b.done(), "B debia esperar el bloqueo de A"
            # A confirma al salir del bloque
            en_b = await asyncio.wait_for(tarea_b, timeout=10)
            assert en_b is vieja and en_b.estado == "EN_REPARACION"


async def test_sin_bloqueo_pendiente_la_segunda_sesion_no_espera(fabrica, db_auth, vehiculo):
    oid = await sembrar_orden_completa(db_auth, vehiculo, "PENDIENTE")
    async with fabrica() as sesion_a, fabrica() as sesion_b:
        async with OrdenesUoW(sesion_a) as uow_a:
            await uow_a.ordenes.bloquear(oid)
        async with OrdenesUoW(sesion_b) as uow_b:
            orden = await asyncio.wait_for(uow_b.ordenes.bloquear(oid), timeout=5)
            assert orden.estado == "PENDIENTE"
