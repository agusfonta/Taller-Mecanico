"""Repositorios y UoW de ordenes contra PostgreSQL real (C-09, tareas 3.2 a 3.7)."""
from decimal import Decimal

import pytest
from sqlalchemy import event

from app.modules.ordenes.models import HistorialEstadoOrden, ItemOrden, OrdenTrabajo
from app.modules.ordenes.unit_of_work import OrdenesUoW
from app.modules.repuestos.stock import ConStock, mover_stock
from test.integration.ordenes.ayudantes import (
    sembrar_catalogo,
    sembrar_cliente,
    sembrar_orden_completa,
    sembrar_repuesto,
    sembrar_vehiculo,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def sentencias(motor_auth):
    """Lista viva con el SQL ejecutado mientras dura el test."""
    capturadas: list[str] = []

    def capturar(conn, cursor, statement, parameters, context, executemany):
        capturadas.append(statement)

    event.listen(motor_auth.sync_engine, "before_cursor_execute", capturar)
    yield capturadas
    event.remove(motor_auth.sync_engine, "before_cursor_execute", capturar)


# --- Catalogo de estados (3.2) --------------------------------------------------


async def test_listar_por_posicion_ordena_el_catalogo_sembrado_desordenado(fabrica, db_auth):
    await sembrar_catalogo(
        db_auth,
        (("CANCELADA", 4, True), ("PENDIENTE", 1, False), ("TERMINADA", 3, True), ("EN_REPARACION", 2, False)),
    )
    async with fabrica() as sesion:
        async with OrdenesUoW(sesion) as uow:
            estados = await uow.estados.listar_por_posicion()
    assert [e.codigo for e in estados] == ["PENDIENTE", "EN_REPARACION", "TERMINADA", "CANCELADA"]
    assert [e.es_final for e in estados] == [False, False, True, True]


async def test_listar_por_posicion_con_catalogo_vacio_devuelve_lista_vacia(fabrica):
    async with fabrica() as sesion:
        async with OrdenesUoW(sesion) as uow:
            assert list(await uow.estados.listar_por_posicion()) == []


async def test_get_por_codigo_encuentra_pendiente_y_none_para_ausente(fabrica, db_auth):
    await sembrar_catalogo(db_auth)
    async with fabrica() as sesion:
        async with OrdenesUoW(sesion) as uow:
            pendiente = await uow.estados.get_por_codigo("PENDIENTE")
            assert pendiente is not None and pendiente.posicion == 1
            assert await uow.estados.get_por_codigo("ARCHIVADA") is None


# --- VehiculoRepository.get_vigente_para_orden (3.3) ------------------------------


async def test_get_vigente_para_orden_devuelve_el_vigente(fabrica, db_auth):
    vid = await sembrar_vehiculo(db_auth, await sembrar_cliente(db_auth, "1"), "AAA111")
    async with fabrica() as sesion:
        async with OrdenesUoW(sesion) as uow:
            v = await uow.vehiculos.get_vigente_para_orden(vid)
            assert v is not None and v.id == vid


async def test_get_vigente_para_orden_none_si_baja_o_inexistente(fabrica, db_auth):
    cid = await sembrar_cliente(db_auth, "2")
    baja = await sembrar_vehiculo(db_auth, cid, "AAA111", baja=True)
    async with fabrica() as sesion:
        async with OrdenesUoW(sesion) as uow:
            assert await uow.vehiculos.get_vigente_para_orden(baja) is None
            assert await uow.vehiculos.get_vigente_para_orden(999999) is None


async def test_get_vigente_para_orden_emite_una_sentencia_for_share(fabrica, db_auth, sentencias):
    vid = await sembrar_vehiculo(db_auth, await sembrar_cliente(db_auth, "3"), "AAA111")
    sentencias.clear()
    async with fabrica() as sesion:
        async with OrdenesUoW(sesion) as uow:
            await uow.vehiculos.get_vigente_para_orden(vid)
    selects = [s for s in sentencias if "FROM vehiculo" in s]
    assert len(selects) == 1 and "FOR SHARE" in selects[0]
    assert "borrado_en IS NULL" in selects[0]
    assert "FOR UPDATE" not in selects[0]


# --- RepuestoRepository.listar_vigentes_para_orden (3.4) ----------------------------


async def test_listar_vigentes_para_orden_ordena_por_id_y_excluye_baja_e_inexistentes(fabrica, db_auth):
    a = await sembrar_repuesto(db_auth, codigo="A")
    b = await sembrar_repuesto(db_auth, codigo="B", borrado=True)
    c = await sembrar_repuesto(db_auth, codigo="C")
    async with fabrica() as sesion:
        async with OrdenesUoW(sesion) as uow:
            repuestos = await uow.repuestos.listar_vigentes_para_orden([c, 999999, b, a])
    assert [r.id for r in repuestos] == [a, c]


async def test_listar_vigentes_para_orden_con_ids_repetidos_o_vacios(fabrica, db_auth):
    a = await sembrar_repuesto(db_auth, codigo="A")
    async with fabrica() as sesion:
        async with OrdenesUoW(sesion) as uow:
            assert [r.id for r in await uow.repuestos.listar_vigentes_para_orden([a, a])] == [a]
            assert list(await uow.repuestos.listar_vigentes_para_orden([])) == []


async def test_listar_vigentes_para_orden_es_una_sentencia_for_share_con_ids_ligados(
    fabrica, db_auth, sentencias
):
    a = await sembrar_repuesto(db_auth, codigo="A")
    b = await sembrar_repuesto(db_auth, codigo="B")
    sentencias.clear()
    async with fabrica() as sesion:
        async with OrdenesUoW(sesion) as uow:
            await uow.repuestos.listar_vigentes_para_orden([a, b])
    selects = [s for s in sentencias if "FROM repuesto" in s]
    assert len(selects) == 1
    assert "FOR SHARE" in selects[0] and "ORDER BY repuesto.id" in selects[0]
    assert "borrado_en IS NULL" in selects[0]
    assert "= ANY ($1::BIGINT[])" in selects[0]  # ligados en un arreglo, no concatenados
    assert "IN (" not in selects[0]


# --- OrdenRepository.get_detalle (3.5) ----------------------------------------------


@pytest.fixture
async def escenario(db_auth):
    cid = await sembrar_cliente(db_auth, "10", nombre="Ana")
    vid = await sembrar_vehiculo(db_auth, cid, "AAA111")
    r1 = await sembrar_repuesto(db_auth, codigo="R1", precio="100.00")
    r2 = await sembrar_repuesto(db_auth, codigo="R2", precio="0.10")
    await sembrar_catalogo(db_auth)
    return {"cliente": cid, "vehiculo": vid, "r1": r1, "r2": r2}


async def test_get_detalle_precarga_vehiculo_cliente_items_repuesto_e_historial(fabrica, db_auth, escenario):
    oid = await sembrar_orden_completa(
        db_auth,
        escenario["vehiculo"],
        items=((escenario["r2"], 3, "0.10"), (escenario["r1"], 2, "100.00")),
    )
    await db_auth.ejecutar(
        "INSERT INTO usuario (email, nombre, password_hash) VALUES ('u@e.com', 'u', 'h')"
    )
    uid = (await db_auth.filas("SELECT id FROM usuario"))[0]["id"]
    await db_auth.ejecutar(
        "INSERT INTO historial_estado_orden (orden_id, desde_estado, hasta_estado, usuario_id) "
        "VALUES (:o, NULL, 'PENDIENTE', :u)",
        o=oid,
        u=uid,
    )
    async with fabrica() as sesion:
        async with OrdenesUoW(sesion) as uow:
            orden = await uow.ordenes.get_detalle(oid)
            assert orden is not None
            assert orden.vehiculo.cliente.nombre == "Ana"
            assert {i.repuesto.codigo for i in orden.items} == {"R1", "R2"}
            assert [h.hasta_estado for h in orden.historial] == ["PENDIENTE"]


async def test_get_detalle_devuelve_none_si_no_existe(fabrica):
    async with fabrica() as sesion:
        async with OrdenesUoW(sesion) as uow:
            assert await uow.ordenes.get_detalle(999999) is None


async def test_get_detalle_carga_el_vehiculo_aunque_este_dado_de_baja(fabrica, db_auth, escenario):
    cid = await sembrar_cliente(db_auth, "11")
    baja = await sembrar_vehiculo(db_auth, cid, "ZZZ999", baja=True)
    oid = await sembrar_orden_completa(db_auth, baja, "TERMINADA")
    async with fabrica() as sesion:
        async with OrdenesUoW(sesion) as uow:
            orden = await uow.ordenes.get_detalle(oid)
            assert orden.vehiculo.borrado_en is not None
            assert orden.vehiculo.cliente.id == cid
            assert orden.items == [] and orden.historial == []


async def test_get_detalle_tras_el_alta_en_la_misma_sesion_no_dispara_carga_implicita(
    fabrica, db_auth, escenario
):
    """``populate_existing``: la orden ya esta en el mapa de identidad con relaciones sin cargar."""
    async with fabrica() as sesion:
        async with OrdenesUoW(sesion) as uow:
            orden = await uow.ordenes.add(
                OrdenTrabajo(vehiculo_id=escenario["vehiculo"], estado="PENDIENTE", falla="f", total=Decimal("200"))
            )
            await uow.items.add_todos(
                [ItemOrden(orden_id=orden.id, repuesto_id=escenario["r1"], cantidad=2, precio_unitario=Decimal("100"))]
            )
            detalle = await uow.ordenes.get_detalle(orden.id)
            assert detalle is orden
            assert detalle.creada_en is not None
            assert [i.repuesto.codigo for i in detalle.items] == ["R1"]
            assert detalle.vehiculo.cliente.nombre == "Ana"


async def test_get_detalle_son_tres_sentencias_sobre_las_tablas_de_orden(
    fabrica, db_auth, escenario, sentencias
):
    oid = await sembrar_orden_completa(
        db_auth, escenario["vehiculo"], items=((escenario["r1"], 1, "100.00"), (escenario["r2"], 1, "0.10"))
    )
    sentencias.clear()
    async with fabrica() as sesion:
        async with OrdenesUoW(sesion) as uow:
            orden = await uow.ordenes.get_detalle(oid)
            _ = [i.repuesto.codigo for i in orden.items]
    tocan = [
        s
        for s in sentencias
        if any(t in s for t in ("FROM orden_trabajo", "FROM item_orden", "FROM historial_estado_orden"))
    ]
    assert len(tocan) == 3


# --- buscar / contar / listar_de_usuario (3.6) ----------------------------------------


@pytest.fixture
async def ordenes_variadas(db_auth):
    """Ordenes de dos clientes, dos mecanicos, dos estados y un vehiculo dado de baja."""
    m1 = await db_auth.crear_usuario("m1@example.com", "x" * 10, roles=("MECANICO",))
    m2 = await db_auth.crear_usuario("m2@example.com", "x" * 10, roles=("MECANICO",))
    u1 = await db_auth.crear_usuario("c1@example.com", "x" * 10)
    u2 = await db_auth.crear_usuario("c2@example.com", "x" * 10)
    c1 = await sembrar_cliente(db_auth, "21", usuario_id=u1)
    c2 = await sembrar_cliente(db_auth, "22", usuario_id=u2)
    v1 = await sembrar_vehiculo(db_auth, c1, "AAA111")
    v1b = await sembrar_vehiculo(db_auth, c1, "AAA222", baja=True)
    v2 = await sembrar_vehiculo(db_auth, c2, "BBB111")
    await sembrar_catalogo(db_auth)
    o_sin = await sembrar_orden_completa(db_auth, v1, "PENDIENTE")
    o_m1 = await sembrar_orden_completa(db_auth, v1b, "EN_REPARACION", mecanico_id=m1)
    o_m2 = await sembrar_orden_completa(db_auth, v2, "EN_REPARACION", mecanico_id=m2)
    o_m1_fin = await sembrar_orden_completa(db_auth, v2, "TERMINADA", mecanico_id=m1)
    return {
        "m1": m1, "m2": m2, "u1": u1, "u2": u2,
        "sin": o_sin, "m1_rep": o_m1, "m2_rep": o_m2, "m1_fin": o_m1_fin,
    }


async def ids_de(uow, estado=None, visible=None):
    return [o.id for o in await uow.ordenes.buscar(estado, visible, offset=0, limit=100)]


async def test_buscar_sin_filtros_devuelve_todas_por_id(fabrica, ordenes_variadas):
    o = ordenes_variadas
    async with fabrica() as sesion:
        async with OrdenesUoW(sesion) as uow:
            assert await ids_de(uow) == [o["sin"], o["m1_rep"], o["m2_rep"], o["m1_fin"]]
            assert await uow.ordenes.contar(None, None) == 4


async def test_buscar_filtra_por_estado(fabrica, ordenes_variadas):
    o = ordenes_variadas
    async with fabrica() as sesion:
        async with OrdenesUoW(sesion) as uow:
            assert await ids_de(uow, "EN_REPARACION") == [o["m1_rep"], o["m2_rep"]]
            assert await ids_de(uow, "PENDIENTE") == [o["sin"]]
            assert await uow.ordenes.contar("EN_REPARACION", None) == 2
            assert await ids_de(uow, "CANCELADA") == []


async def test_buscar_con_mecanico_visible_incluye_suyas_y_sin_asignar(fabrica, ordenes_variadas):
    o = ordenes_variadas
    async with fabrica() as sesion:
        async with OrdenesUoW(sesion) as uow:
            assert await ids_de(uow, None, o["m1"]) == [o["sin"], o["m1_rep"], o["m1_fin"]]
            assert await ids_de(uow, None, o["m2"]) == [o["sin"], o["m2_rep"]]
            assert await ids_de(uow, "EN_REPARACION", o["m1"]) == [o["m1_rep"]]
            assert await uow.ordenes.contar(None, o["m2"]) == 2
            assert await uow.ordenes.contar("TERMINADA", o["m2"]) == 0


async def test_contar_coincide_con_buscar_sin_paginar_y_paginacion_recorta(fabrica, ordenes_variadas):
    o = ordenes_variadas
    async with fabrica() as sesion:
        async with OrdenesUoW(sesion) as uow:
            for estado, visible in [(None, None), ("EN_REPARACION", None), (None, o["m1"])]:
                assert await uow.ordenes.contar(estado, visible) == len(await ids_de(uow, estado, visible))
            pagina = await uow.ordenes.buscar(None, None, offset=1, limit=2)
            assert [x.id for x in pagina] == [o["m1_rep"], o["m2_rep"]]


async def test_listar_de_usuario_incluye_vehiculos_dados_de_baja_y_solo_los_propios(fabrica, ordenes_variadas):
    o = ordenes_variadas
    async with fabrica() as sesion:
        async with OrdenesUoW(sesion) as uow:
            propias = await uow.ordenes.listar_de_usuario(o["u1"], offset=0, limit=100)
            assert [x.id for x in propias] == [o["sin"], o["m1_rep"]]  # m1_rep: vehiculo dado de baja
            assert await uow.ordenes.contar_de_usuario(o["u1"]) == 2
            del_otro = await uow.ordenes.listar_de_usuario(o["u2"], offset=0, limit=100)
            assert [x.id for x in del_otro] == [o["m2_rep"], o["m1_fin"]]
            assert await uow.ordenes.contar_de_usuario(o["u2"]) == 2


async def test_listar_de_usuario_sin_ficha_es_vacio_y_pagina(fabrica, ordenes_variadas):
    o = ordenes_variadas
    async with fabrica() as sesion:
        async with OrdenesUoW(sesion) as uow:
            assert list(await uow.ordenes.listar_de_usuario(o["m1"], offset=0, limit=10)) == []
            assert await uow.ordenes.contar_de_usuario(o["m1"]) == 0
            segunda = await uow.ordenes.listar_de_usuario(o["u1"], offset=1, limit=1)
            assert [x.id for x in segunda] == [o["m1_rep"]]


# --- add_todos y OrdenesUoW (3.7) ------------------------------------------------------


async def test_add_todos_inserta_en_un_flush_y_devuelve_las_entidades(fabrica, db_auth, escenario):
    async with fabrica() as sesion:
        async with OrdenesUoW(sesion) as uow:
            orden = await uow.ordenes.add(
                OrdenTrabajo(vehiculo_id=escenario["vehiculo"], estado="PENDIENTE", falla="f", total=Decimal("1"))
            )
            items = await uow.items.add_todos(
                [
                    ItemOrden(orden_id=orden.id, repuesto_id=escenario["r1"], cantidad=1, precio_unitario=Decimal("1")),
                    ItemOrden(orden_id=orden.id, repuesto_id=escenario["r2"], cantidad=2, precio_unitario=Decimal("1")),
                ]
            )
            assert [i.id is not None for i in items] == [True, True]
    assert len(await db_auth.filas("SELECT 1 FROM item_orden")) == 2


async def test_add_todos_con_lista_vacia_no_falla(fabrica):
    async with fabrica() as sesion:
        async with OrdenesUoW(sesion) as uow:
            assert list(await uow.items.add_todos([])) == []


async def test_el_uow_comparte_una_sola_sesion_entre_todos_los_repositorios(fabrica):
    async with fabrica() as sesion:
        uow = OrdenesUoW(sesion)
        repos = [uow.estados, uow.ordenes, uow.items, uow.historial, uow.vehiculos, uow.repuestos, uow.movimientos]
        assert all(r.session is sesion for r in repos)
        assert uow.session is sesion


async def test_el_uow_satisface_con_stock_y_mover_stock_funciona_dentro(fabrica, db_auth, escenario):
    admin = await db_auth.crear_usuario("admin@example.com", "x" * 10, roles=("ADMIN",))
    uow: ConStock
    async with fabrica() as sesion:
        uow = OrdenesUoW(sesion)
        nuevo = await mover_stock(uow, repuesto_id=escenario["r1"], cantidad=5, motivo="prueba", usuario_id=admin)
        assert nuevo == 5
        await sesion.rollback()  # el test no confirma nada
    assert (await db_auth.filas("SELECT stock FROM repuesto WHERE id = :i", i=escenario["r1"]))[0]["stock"] == 0
    assert await db_auth.contar("movimiento_stock") == 0


async def test_historial_agrega_lineas_firmadas(fabrica, db_auth, escenario):
    admin = await db_auth.crear_usuario("admin@example.com", "x" * 10, roles=("ADMIN",))
    oid = await sembrar_orden_completa(db_auth, escenario["vehiculo"])
    async with fabrica() as sesion:
        async with OrdenesUoW(sesion) as uow:
            h = await uow.historial.add(
                HistorialEstadoOrden(orden_id=oid, desde_estado=None, hasta_estado="PENDIENTE", usuario_id=admin)
            )
            assert h.id is not None
