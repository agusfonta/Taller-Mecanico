"""Punto unico de escritura de stock contra PostgreSQL real (C-08, 4.1, 4.3, 4.4, D4/D5)."""
import asyncio

import pytest

from app.core.database import crear_fabrica_sesiones
from app.modules.repuestos.stock import (
    STOCK_MAXIMO,
    RepuestoNoEncontradoError,
    StockFueraDeRangoError,
    StockInsuficienteError,
    mover_stock,
)
from app.modules.repuestos.unit_of_work import RepuestosUoW
from test.integration.ayudantes_clientes import (
    sembrar_catalogo,
    sembrar_cliente,
    sembrar_orden,
    sembrar_vehiculo,
)
from test.integration.repuestos.ayudantes import fila_de, movimientos_de, sembrar_repuesto

pytestmark = pytest.mark.integration


@pytest.fixture
def fabrica(motor_auth):
    return crear_fabrica_sesiones(motor_auth)


@pytest.fixture
async def admin(db_auth) -> int:
    return await db_auth.crear_usuario("admin@example.com", "x" * 10, roles=("ADMIN",))


async def stock_de(db, rid: int) -> int:
    return (await fila_de(db, rid))["stock"]


async def test_mover_stock_devuelve_el_nuevo_y_deja_un_movimiento(fabrica, db_auth, admin):
    rid = await sembrar_repuesto(db_auth, stock=2)
    async with fabrica() as sesion:
        async with RepuestosUoW(sesion) as uow:
            nuevo = await mover_stock(
                uow, repuesto_id=rid, cantidad=5, motivo="Reposición", usuario_id=admin
            )
    assert nuevo == 7
    assert await stock_de(db_auth, rid) == 7
    movs = await movimientos_de(db_auth, rid)
    assert [(m["cantidad"], m["motivo"], m["usuario_id"], m["orden_id"]) for m in movs] == [
        (5, "Reposición", admin, None)
    ]


@pytest.mark.parametrize(("cantidad", "motivo"), [(0, "Reposición"), (5, ""), (5, "   ")])
async def test_mover_stock_con_argumentos_invalidos_es_value_error_sin_escrituras(
    fabrica, db_auth, admin, cantidad, motivo
):
    rid = await sembrar_repuesto(db_auth, stock=2)
    async with fabrica() as sesion:
        with pytest.raises(ValueError):
            async with RepuestosUoW(sesion) as uow:
                await mover_stock(
                    uow, repuesto_id=rid, cantidad=cantidad, motivo=motivo, usuario_id=admin
                )
    assert await stock_de(db_auth, rid) == 2
    assert await movimientos_de(db_auth, rid) == []


async def test_salida_mayor_que_el_stock_es_stock_insuficiente_sin_efectos(fabrica, db_auth, admin):
    rid = await sembrar_repuesto(db_auth, stock=2)
    async with fabrica() as sesion:
        with pytest.raises(StockInsuficienteError) as info:
            async with RepuestosUoW(sesion) as uow:
                await mover_stock(
                    uow, repuesto_id=rid, cantidad=-4, motivo="Salida", usuario_id=admin
                )
    assert info.value.repuesto_id == rid
    assert await stock_de(db_auth, rid) == 2
    assert await movimientos_de(db_auth, rid) == []


async def test_salida_exacta_deja_el_stock_en_cero(fabrica, db_auth, admin):
    rid = await sembrar_repuesto(db_auth, stock=2)
    async with fabrica() as sesion:
        async with RepuestosUoW(sesion) as uow:
            assert (
                await mover_stock(uow, repuesto_id=rid, cantidad=-2, motivo="S", usuario_id=admin) == 0
            )
    assert [m["cantidad"] for m in await movimientos_de(db_auth, rid)] == [-2]


async def test_repuesto_inexistente(fabrica, admin):
    async with fabrica() as sesion:
        with pytest.raises(RepuestoNoEncontradoError) as info:
            async with RepuestosUoW(sesion) as uow:
                await mover_stock(uow, repuesto_id=999999, cantidad=1, motivo="R", usuario_id=admin)
    assert info.value.repuesto_id == 999999


async def test_salida_de_repuesto_inexistente_tambien_es_no_encontrado(fabrica, admin):
    async with fabrica() as sesion:
        with pytest.raises(RepuestoNoEncontradoError):
            async with RepuestosUoW(sesion) as uow:
                await mover_stock(uow, repuesto_id=999999, cantidad=-1, motivo="S", usuario_id=admin)


async def test_desborde_es_fuera_de_rango_sin_efectos(fabrica, db_auth, admin):
    rid = await sembrar_repuesto(db_auth, stock=2147483000)
    async with fabrica() as sesion:
        with pytest.raises(StockFueraDeRangoError):
            async with RepuestosUoW(sesion) as uow:
                await mover_stock(uow, repuesto_id=rid, cantidad=1000, motivo="R", usuario_id=admin)
    assert await stock_de(db_auth, rid) == 2147483000
    assert await movimientos_de(db_auth, rid) == []
    assert STOCK_MAXIMO == 2_147_483_647


async def test_repuesto_dado_de_baja_se_mueve_igual(fabrica, db_auth, admin):
    """SU-C08-9: C-10 debe poder terminar una orden cuyo repuesto se dio de baja despues."""
    rid = await sembrar_repuesto(db_auth, stock=3, borrado=True)
    async with fabrica() as sesion:
        async with RepuestosUoW(sesion) as uow:
            assert (
                await mover_stock(uow, repuesto_id=rid, cantidad=-1, motivo="S", usuario_id=admin) == 2
            )


async def test_orden_id_se_guarda_cuando_se_pasa(fabrica, db_auth, admin):
    # Se siembra una orden minima por SQL ligado con el catalogo de estados de C-07.
    await sembrar_catalogo(db_auth)
    vehiculo = await sembrar_vehiculo(db_auth, await sembrar_cliente(db_auth, "30111222"), "AB123CD")
    orden = await sembrar_orden(db_auth, vehiculo, "EN_REPARACION")
    rid = await sembrar_repuesto(db_auth, stock=3)
    async with fabrica() as sesion:
        async with RepuestosUoW(sesion) as uow:
            await mover_stock(
                uow, repuesto_id=rid, cantidad=-1, motivo="S", usuario_id=admin, orden_id=orden
            )
    assert (await movimientos_de(db_auth, rid))[0]["orden_id"] == orden


async def test_falla_al_registrar_el_movimiento_revierte_el_stock(fabrica, db_auth, admin):
    rid = await sembrar_repuesto(db_auth, stock=2)
    async with fabrica() as sesion:
        with pytest.raises(Exception):  # usuario inexistente: viola la FK del movimiento
            async with RepuestosUoW(sesion) as uow:
                await mover_stock(uow, repuesto_id=rid, cantidad=5, motivo="R", usuario_id=999999)
    assert await stock_de(db_auth, rid) == 2
    assert await movimientos_de(db_auth, rid) == []


async def _mover(fabrica, rid: int, cantidad: int, usuario: int):
    async with fabrica() as sesion:
        async with RepuestosUoW(sesion) as uow:
            return await mover_stock(
                uow, repuesto_id=rid, cantidad=cantidad, motivo="Concurrente", usuario_id=usuario
            )


@pytest.mark.parametrize("repeticion", range(5))
async def test_salidas_concurrentes_que_juntas_no_alcanzan(fabrica, db_auth, admin, repeticion):
    rid = await sembrar_repuesto(db_auth, codigo=f"C{repeticion}", stock=3)
    resultados = await asyncio.gather(
        _mover(fabrica, rid, -2, admin), _mover(fabrica, rid, -2, admin), return_exceptions=True
    )
    fallos = [r for r in resultados if isinstance(r, StockInsuficienteError)]
    exitos = [r for r in resultados if isinstance(r, int)]
    assert len(fallos) == 1 and exitos == [1]
    assert await stock_de(db_auth, rid) == 1
    assert [m["cantidad"] for m in await movimientos_de(db_auth, rid)] == [-2]


@pytest.mark.parametrize("repeticion", range(5))
async def test_entradas_concurrentes_se_suman_ambas(fabrica, db_auth, admin, repeticion):
    rid = await sembrar_repuesto(db_auth, codigo=f"E{repeticion}", stock=0)
    resultados = await asyncio.gather(_mover(fabrica, rid, 5, admin), _mover(fabrica, rid, 5, admin))
    assert sorted(resultados) == [5, 10]
    assert await stock_de(db_auth, rid) == 10
    assert [m["cantidad"] for m in await movimientos_de(db_auth, rid)] == [5, 5]
