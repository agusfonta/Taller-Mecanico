"""Servicio ``terminar_orden`` con UoW real: stock, permisos y concurrencia (C-10, grupo 5)."""
import asyncio
import inspect

import pytest
from sqlalchemy import event

from app.modules.ordenes import service
from app.modules.ordenes.unit_of_work import OrdenesUoW
from app.modules.repuestos.stock import MOTIVO_ORDEN_TERMINADA, mover_stock
from app.modules.repuestos.unit_of_work import RepuestosUoW
from app.modules.usuarios.models import Rol
from test.integration.ordenes.ayudantes import (
    _movimiento_inicial,
    actor,
    conteos_ciclo,
    escenario_c11,
    fila_de_orden,
    historial_de_orden,
    movimientos_de_orden,
    sembrar_orden_completa,
    sembrar_repuesto,
    stock_de,
)

pytestmark = pytest.mark.integration


async def terminar(fabrica, orden_id, usuario):
    async with fabrica() as sesion:
        return await service.terminar_orden(OrdenesUoW(sesion), orden_id, usuario)


async def repuesto_con_stock(db, codigo, stock, admin):
    rid = await sembrar_repuesto(db, codigo=codigo, precio="10.00", stock=stock)
    await _movimiento_inicial(db, rid, admin, stock)
    return rid


async def suma_de_movimientos(db, rid) -> int:
    filas = await db.filas(
        "SELECT COALESCE(SUM(cantidad), 0) AS s FROM movimiento_stock WHERE repuesto_id = :i", i=rid
    )
    return filas[0]["s"]


@pytest.fixture
def sentencias(motor_auth):
    capturadas: list[tuple[str, object]] = []

    def capturar(conn, cursor, statement, parameters, context, executemany):
        capturadas.append((statement, parameters))

    event.listen(motor_auth.sync_engine, "before_cursor_execute", capturar)
    yield capturadas
    event.remove(motor_auth.sync_engine, "before_cursor_execute", capturar)


# --- 5.1 camino feliz --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pedidos",
    [[(2, 3)], [(2, 3), (1, 1)]],
    ids=["un_item", "dos_items"],
)
async def test_terminar_descuenta_cada_repuesto_y_deja_un_movimiento_por_item(
    fabrica, db_auth, mundo_ciclo, pedidos
):
    """``pedidos`` = (cantidad pedida, stock que debe quedar)."""
    m = mundo_ciclo
    quedan, items = [], []
    for n, (cantidad, final) in enumerate(pedidos):
        rid = await repuesto_con_stock(db_auth, f"R{n}", final + cantidad, m["admin"])
        quedan.append((rid, final, cantidad))
        items.append((rid, cantidad, "10.00"))
    oid = await sembrar_orden_completa(
        db_auth, m["vehiculo"], "EN_REPARACION", mecanico_id=m["mecanico"], items=tuple(items)
    )
    detalle = await terminar(fabrica, oid, actor(m["mecanico"], Rol.MECANICO))
    assert detalle.estado == "TERMINADA"
    fila = await fila_de_orden(db_auth, oid)
    assert fila["estado"] == "TERMINADA" and fila["mecanico_id"] == m["mecanico"]
    for rid, final, _ in quedan:
        assert await stock_de(db_auth, rid) == final
        assert await suma_de_movimientos(db_auth, rid) == final
    movs = await movimientos_de_orden(db_auth, oid)
    assert [(x["repuesto_id"], x["cantidad"], x["orden_id"], x["usuario_id"], x["motivo"]) for x in movs] == [
        (rid, -cantidad, oid, m["mecanico"], MOTIVO_ORDEN_TERMINADA) for rid, _, cantidad in sorted(quedan)
    ]
    historial = await historial_de_orden(db_auth, oid)
    assert [(h["desde_estado"], h["hasta_estado"], h["usuario_id"]) for h in historial] == [
        ("EN_REPARACION", "TERMINADA", m["mecanico"])
    ]
    assert [h.hasta_estado for h in detalle.historial] == ["TERMINADA"]


async def test_cuando_termina_un_admin_el_mecanico_asignado_no_cambia(fabrica, db_auth, mundo_ciclo):
    m = mundo_ciclo
    rid = await repuesto_con_stock(db_auth, "R1", 4, m["admin"])
    oid = await sembrar_orden_completa(
        db_auth, m["vehiculo"], "EN_REPARACION", mecanico_id=m["mecanico"], items=((rid, 1, "10.00"),)
    )
    await terminar(fabrica, oid, actor(m["admin"], Rol.ADMIN))
    assert (await fila_de_orden(db_auth, oid))["mecanico_id"] == m["mecanico"]
    assert [x["usuario_id"] for x in await movimientos_de_orden(db_auth, oid)] == [m["admin"]]
    assert (await historial_de_orden(db_auth, oid))[0]["usuario_id"] == m["admin"]
    assert await stock_de(db_auth, rid) == 3


# --- 5.2 orden del descuento ---------------------------------------------------------------------


async def test_los_updates_de_stock_salen_en_orden_ascendente_de_repuesto_id(
    fabrica, db_auth, mundo_ciclo, sentencias
):
    m = mundo_ciclo
    r1 = await repuesto_con_stock(db_auth, "R1", 5, m["admin"])
    r2 = await repuesto_con_stock(db_auth, "R2", 5, m["admin"])
    r3 = await repuesto_con_stock(db_auth, "R3", 5, m["admin"])
    oid = await sembrar_orden_completa(  # items insertados en orden inverso de repuesto_id
        db_auth,
        m["vehiculo"],
        "EN_REPARACION",
        mecanico_id=m["mecanico"],
        items=((r3, 1, "10.00"), (r1, 1, "10.00"), (r2, 1, "10.00")),
    )
    sentencias.clear()
    await terminar(fabrica, oid, actor(m["mecanico"], Rol.MECANICO))
    ids = [p[1] for s, p in sentencias if s.lstrip().upper().startswith("UPDATE REPUESTO")]
    assert ids == [r1, r2, r3]
    assert [x["repuesto_id"] for x in await movimientos_de_orden(db_auth, oid)] == [r1, r2, r3]


def test_terminar_orden_usa_mover_stock_y_no_escribe_stock_directamente():
    fuente = inspect.getsource(service.terminar_orden)
    assert "mover_stock(" in fuente
    assert "sumar_stock" not in fuente
    assert ".stock" not in fuente and "stock=" not in fuente.replace(" ", "")


def test_stock_insuficiente_se_captura_solo_fuera_del_bloque_del_uow():
    lineas = inspect.getsource(service.terminar_orden).splitlines()
    sangria = lambda texto: len(texto) - len(texto.lstrip())  # noqa: E731
    bloque = next(i for i, l in enumerate(lineas) if l.strip() == "async with uow:")
    captura = next(i for i, l in enumerate(lineas) if "except StockInsuficienteError" in l)
    assert captura > bloque and sangria(lineas[captura]) < sangria(lineas[bloque])


# --- 5.3 casos C-11 / C-12 ------------------------------------------------------------------------


async def test_c11_stock_insuficiente_no_deja_rastro_y_nombra_la_bujia(fabrica, db_auth):
    e = await escenario_c11(db_auth)
    antes, fila = await conteos_ciclo(db_auth), await fila_de_orden(db_auth, e["orden"])
    with pytest.raises(service.StockInsuficienteOrdenError) as info:
        await terminar(fabrica, e["orden"], actor(e["mecanico"], Rol.MECANICO))
    assert "BUJ-001" in info.value.mensaje and "FIL-001" not in info.value.mensaje
    assert await conteos_ciclo(db_auth) == antes and await fila_de_orden(db_auth, e["orden"]) == fila
    assert await stock_de(db_auth, e["filtro"]) == 10 and await stock_de(db_auth, e["bujia"]) == 2
    assert await movimientos_de_orden(db_auth, e["orden"]) == []
    assert len(await historial_de_orden(db_auth, e["orden"])) == 2


async def test_c12_tras_reponer_las_bujias_la_orden_se_termina(fabrica, db_auth):
    e = await escenario_c11(db_auth)
    with pytest.raises(service.StockInsuficienteOrdenError):
        await terminar(fabrica, e["orden"], actor(e["mecanico"], Rol.MECANICO))
    async with fabrica() as sesion:
        async with RepuestosUoW(sesion) as uow:
            await mover_stock(uow, repuesto_id=e["bujia"], cantidad=2, motivo="Reposición", usuario_id=e["admin"])
    detalle = await terminar(fabrica, e["orden"], actor(e["mecanico"], Rol.MECANICO))
    assert detalle.estado == "TERMINADA"
    assert await stock_de(db_auth, e["bujia"]) == 0 and await stock_de(db_auth, e["filtro"]) == 9
    movs = await movimientos_de_orden(db_auth, e["orden"])
    assert [(x["repuesto_id"], x["cantidad"]) for x in movs] == [(e["filtro"], -1), (e["bujia"], -4)]
    assert len(await historial_de_orden(db_auth, e["orden"])) == 3


async def test_si_falla_el_primer_repuesto_se_nombra_ese_y_no_queda_descontado_el_otro(
    fabrica, db_auth, mundo_ciclo
):
    m = mundo_ciclo
    corto = await repuesto_con_stock(db_auth, "AAA-CORTO", 1, m["admin"])
    largo = await repuesto_con_stock(db_auth, "ZZZ-LARGO", 10, m["admin"])
    oid = await sembrar_orden_completa(
        db_auth, m["vehiculo"], "EN_REPARACION", mecanico_id=m["mecanico"],
        items=((largo, 1, "10.00"), (corto, 3, "10.00")),
    )
    with pytest.raises(service.StockInsuficienteOrdenError) as info:
        await terminar(fabrica, oid, actor(m["mecanico"], Rol.MECANICO))
    assert "AAA-CORTO" in info.value.mensaje
    assert await stock_de(db_auth, largo) == 10 and await stock_de(db_auth, corto) == 1


# --- 5.4 permisos y estado ----------------------------------------------------------------------------


@pytest.mark.parametrize("estado", ["PENDIENTE", "EN_REPARACION", "TERMINADA", "CANCELADA"])
async def test_mecanico_no_asignado_recibe_403_aun_con_estado_invalido(fabrica, db_auth, mundo_ciclo, estado):
    m = mundo_ciclo
    oid = await sembrar_orden_completa(db_auth, m["vehiculo"], estado, mecanico_id=m["mecanico"])
    antes, fila = await conteos_ciclo(db_auth), await fila_de_orden(db_auth, oid)
    with pytest.raises(service.SinPermisoSobreOrdenError):
        await terminar(fabrica, oid, actor(m["mecanico2"], Rol.MECANICO))
    assert await conteos_ciclo(db_auth) == antes and await fila_de_orden(db_auth, oid) == fila


async def test_mecanico_en_orden_pendiente_sin_mecanico_tambien_es_403(fabrica, db_auth, mundo_ciclo):
    oid = await sembrar_orden_completa(db_auth, mundo_ciclo["vehiculo"], "PENDIENTE")
    with pytest.raises(service.SinPermisoSobreOrdenError):
        await terminar(fabrica, oid, actor(mundo_ciclo["mecanico"], Rol.MECANICO))


@pytest.mark.parametrize("estado", ["PENDIENTE", "TERMINADA", "CANCELADA"])
@pytest.mark.parametrize("quien", ["admin", "asignado"])
async def test_con_permiso_pero_estado_invalido_es_transicion_invalida_sin_escrituras(
    fabrica, db_auth, mundo_ciclo, estado, quien
):
    m = mundo_ciclo
    oid = await sembrar_orden_completa(db_auth, m["vehiculo"], estado, mecanico_id=m["mecanico"])
    usuario = actor(m["admin"], Rol.ADMIN) if quien == "admin" else actor(m["mecanico"], Rol.MECANICO)
    antes, fila = await conteos_ciclo(db_auth), await fila_de_orden(db_auth, oid)
    with pytest.raises(service.TransicionInvalidaError) as info:
        await terminar(fabrica, oid, usuario)
    assert estado in info.value.mensaje and "terminar" in info.value.mensaje
    assert await conteos_ciclo(db_auth) == antes and await fila_de_orden(db_auth, oid) == fila


@pytest.mark.parametrize("rol", [Rol.MECANICO, Rol.ADMIN, Rol.CLIENTE])
async def test_orden_inexistente_es_404_antes_que_el_permiso(fabrica, db_auth, mundo_ciclo, rol):
    antes = await conteos_ciclo(db_auth)
    with pytest.raises(service.OrdenNoEncontradaError):
        await terminar(fabrica, 9999, actor(mundo_ciclo["mecanico2"], rol))
    assert await conteos_ciclo(db_auth) == antes


async def test_terminar_con_catalogo_sin_terminada_es_catalogo_sin_cargar(fabrica, db_auth, mundo_ciclo):
    m = mundo_ciclo
    rid = await repuesto_con_stock(db_auth, "R1", 4, m["admin"])
    oid = await sembrar_orden_completa(
        db_auth, m["vehiculo"], "EN_REPARACION", mecanico_id=m["mecanico"], items=((rid, 1, "10.00"),)
    )
    await db_auth.ejecutar("DELETE FROM estado_orden WHERE codigo = 'TERMINADA'")
    antes = await conteos_ciclo(db_auth)
    with pytest.raises(service.CatalogoSinCargarError):
        await terminar(fabrica, oid, actor(m["mecanico"], Rol.MECANICO))
    assert await conteos_ciclo(db_auth) == antes


# --- 5.5 repuesto dado de baja despues del alta (D6-b) -----------------------------------------------------


async def test_un_repuesto_dado_de_baja_despues_del_alta_igual_se_descuenta(fabrica, db_auth, mundo_ciclo):
    m = mundo_ciclo
    rid = await repuesto_con_stock(db_auth, "R1", 6, m["admin"])
    oid = await sembrar_orden_completa(
        db_auth, m["vehiculo"], "EN_REPARACION", mecanico_id=m["mecanico"], items=((rid, 2, "10.00"),)
    )
    await db_auth.ejecutar("UPDATE repuesto SET borrado_en = now() WHERE id = :i", i=rid)
    await terminar(fabrica, oid, actor(m["mecanico"], Rol.MECANICO))
    assert await stock_de(db_auth, rid) == 4
    assert [(x["repuesto_id"], x["cantidad"]) for x in await movimientos_de_orden(db_auth, oid)] == [(rid, -2)]


# --- 5.6 concurrencia ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("repeticion", range(5))
async def test_asignado_y_admin_terminan_la_misma_orden_a_la_vez(fabrica, db_auth, mundo_ciclo, repeticion):
    m = mundo_ciclo
    rid = await repuesto_con_stock(db_auth, "R1", 5, m["admin"])
    oid = await sembrar_orden_completa(
        db_auth, m["vehiculo"], "EN_REPARACION", mecanico_id=m["mecanico"], items=((rid, 2, "10.00"),)
    )
    resultados = await asyncio.gather(
        terminar(fabrica, oid, actor(m["mecanico"], Rol.MECANICO)),
        terminar(fabrica, oid, actor(m["admin"], Rol.ADMIN)),
        return_exceptions=True,
    )
    assert sum(isinstance(r, service.TransicionInvalidaError) for r in resultados) == 1
    assert sum(not isinstance(r, BaseException) for r in resultados) == 1
    assert len(await movimientos_de_orden(db_auth, oid)) == 1
    assert await stock_de(db_auth, rid) == 3
    assert len(await historial_de_orden(db_auth, oid)) == 1


@pytest.mark.parametrize("repeticion", range(5))
async def test_dos_ordenes_que_piden_mas_de_lo_que_hay_una_gana_y_la_otra_es_409(
    fabrica, db_auth, mundo_ciclo, repeticion
):
    m = mundo_ciclo
    rid = await repuesto_con_stock(db_auth, "R1", 3, m["admin"])
    o1 = await sembrar_orden_completa(
        db_auth, m["vehiculo"], "EN_REPARACION", mecanico_id=m["mecanico"], items=((rid, 2, "10.00"),)
    )
    o2 = await sembrar_orden_completa(
        db_auth, m["vehiculo"], "EN_REPARACION", mecanico_id=m["mecanico2"], items=((rid, 2, "10.00"),)
    )
    resultados = await asyncio.gather(
        terminar(fabrica, o1, actor(m["mecanico"], Rol.MECANICO)),
        terminar(fabrica, o2, actor(m["mecanico2"], Rol.MECANICO)),
        return_exceptions=True,
    )
    assert sum(isinstance(r, service.StockInsuficienteOrdenError) for r in resultados) == 1
    assert sum(not isinstance(r, BaseException) for r in resultados) == 1
    assert await stock_de(db_auth, rid) == 1
    assert await suma_de_movimientos(db_auth, rid) == 1
    perdedora = o1 if isinstance(resultados[0], BaseException) else o2
    assert (await fila_de_orden(db_auth, perdedora))["estado"] == "EN_REPARACION"


@pytest.mark.parametrize("repeticion", range(5))
async def test_dos_ordenes_con_repuestos_compartidos_en_orden_opuesto_no_se_interbloquean(
    fabrica, db_auth, mundo_ciclo, repeticion
):
    m = mundo_ciclo
    ra = await repuesto_con_stock(db_auth, "RA", 10, m["admin"])
    rb = await repuesto_con_stock(db_auth, "RB", 10, m["admin"])
    o1 = await sembrar_orden_completa(
        db_auth, m["vehiculo"], "EN_REPARACION", mecanico_id=m["mecanico"],
        items=((ra, 1, "10.00"), (rb, 1, "10.00")),
    )
    o2 = await sembrar_orden_completa(
        db_auth, m["vehiculo"], "EN_REPARACION", mecanico_id=m["mecanico2"],
        items=((rb, 2, "10.00"), (ra, 2, "10.00")),
    )
    resultados = await asyncio.wait_for(
        asyncio.gather(
            terminar(fabrica, o1, actor(m["mecanico"], Rol.MECANICO)),
            terminar(fabrica, o2, actor(m["mecanico2"], Rol.MECANICO)),
        ),
        timeout=20,
    )
    assert [r.estado for r in resultados] == ["TERMINADA", "TERMINADA"]
    assert await stock_de(db_auth, ra) == 7 and await stock_de(db_auth, rb) == 7
