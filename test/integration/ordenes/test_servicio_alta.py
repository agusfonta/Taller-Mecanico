"""Servicio de alta de ordenes con UoW real sobre PostgreSQL (C-09, tareas 4.1 a 4.4)."""
import asyncio
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.modules.clientes import service as servicio_clientes
from app.modules.clientes.unit_of_work import ClientesUoW
from app.modules.ordenes import service
from app.modules.ordenes.schemas import ItemAlta, OrdenAlta
from app.modules.ordenes.unit_of_work import OrdenesUoW
from test.integration.ordenes.ayudantes import (
    conteos_de_orden,
    historial_de_orden,
    items_de_orden,
    fila_de_orden,
    sembrar_catalogo,
    sembrar_cliente,
    sembrar_repuesto,
    sembrar_vehiculo,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def usuario(db_auth) -> int:
    return await db_auth.crear_usuario("recepcion@example.com", "x" * 10, roles=("RECEPCION",))


@pytest.fixture
async def escenario(db_auth, usuario):
    await sembrar_catalogo(db_auth)
    cid = await sembrar_cliente(db_auth, "10")
    return {
        "vehiculo": await sembrar_vehiculo(db_auth, cid, "AAA111"),
        "cliente": cid,
        "r1": await sembrar_repuesto(db_auth, codigo="R1", precio="8500.00"),
        "r2": await sembrar_repuesto(db_auth, codigo="R2", precio="0.10"),
        "r3": await sembrar_repuesto(db_auth, codigo="R3", precio="1234.56"),
    }


def orden(vehiculo, *items, falla="Ruido en el motor"):
    return OrdenAlta(
        vehiculo_id=vehiculo,
        falla=falla,
        items=[ItemAlta(repuesto_id=r, cantidad=c) for r, c in items],
    )


async def crear(fabrica, datos, usuario_id):
    async with fabrica() as sesion:
        return await service.crear_orden(OrdenesUoW(sesion), datos, usuario_id)


# --- Camino feliz (4.1) -------------------------------------------------------------


async def test_alta_con_un_item_deja_orden_pendiente_sin_mecanico_y_precio_copiado(
    fabrica, db_auth, escenario, usuario
):
    e = escenario
    creada = await crear(fabrica, orden(e["vehiculo"], (e["r1"], 2)), usuario)
    fila = await fila_de_orden(db_auth, creada.id)
    assert fila["estado"] == "PENDIENTE" and fila["mecanico_id"] is None
    assert fila["vehiculo_id"] == e["vehiculo"] and fila["falla"] == "Ruido en el motor"
    assert fila["total"] == Decimal("17000.00")
    assert await items_de_orden(db_auth, creada.id) == [
        {
            "id": 1, "orden_id": creada.id, "repuesto_id": e["r1"], "cantidad": 2,
            "precio_unitario": Decimal("8500.00"),
        }
    ]


async def test_alta_con_dos_items_suma_el_total_exacto_con_centavos(fabrica, db_auth, escenario, usuario):
    e = escenario
    creada = await crear(fabrica, orden(e["vehiculo"], (e["r3"], 3), (e["r2"], 3), (e["r1"], 1)), usuario)
    assert (await fila_de_orden(db_auth, creada.id))["total"] == Decimal("3703.68") + Decimal("0.30") + Decimal("8500.00")
    assert creada.total == Decimal("12203.98")
    items = await items_de_orden(db_auth, creada.id)
    assert [(i["repuesto_id"], i["cantidad"], i["precio_unitario"]) for i in items] == [
        (e["r1"], 1, Decimal("8500.00")),
        (e["r2"], 3, Decimal("0.10")),
        (e["r3"], 3, Decimal("1234.56")),
    ]


async def test_alta_deja_una_linea_de_historial_nula_a_pendiente_firmada(fabrica, db_auth, escenario, usuario):
    e = escenario
    creada = await crear(fabrica, orden(e["vehiculo"], (e["r1"], 1)), usuario)
    assert await historial_de_orden(db_auth, creada.id) == [
        {"id": 1, "orden_id": creada.id, "desde_estado": None, "hasta_estado": "PENDIENTE", "usuario_id": usuario}
    ]


async def test_alta_devuelve_el_detalle_precargado_listo_para_serializar(fabrica, escenario, usuario):
    e = escenario
    async with fabrica() as sesion:
        creada = await service.crear_orden(OrdenesUoW(sesion), orden(e["vehiculo"], (e["r1"], 2)), usuario)
        assert creada.creada_en is not None
        assert [(i.repuesto.codigo, i.cantidad) for i in creada.items] == [("R1", 2)]
        assert [h.hasta_estado for h in creada.historial] == ["PENDIENTE"]
        assert creada.vehiculo.cliente.id == e["cliente"]


async def test_el_total_en_el_limite_exacto_se_admite(fabrica, db_auth, escenario, usuario):
    grande = await sembrar_repuesto(db_auth, codigo="G", precio="99999999.99")
    centavos = await sembrar_repuesto(db_auth, codigo="C", precio="0.99")
    creada = await crear(fabrica, orden(escenario["vehiculo"], (grande, 100), (centavos, 1)), usuario)
    assert creada.total == Decimal("9999999999.99")


# --- 409 sin rastro (4.2) -------------------------------------------------------------


async def assert_sin_rastro(db, antes):
    assert await conteos_de_orden(db) == antes


async def test_catalogo_vacio_lanza_catalogo_sin_cargar_sin_rastro(fabrica, db_auth, usuario):
    cid = await sembrar_cliente(db_auth, "10")
    vid = await sembrar_vehiculo(db_auth, cid, "AAA111")
    rid = await sembrar_repuesto(db_auth)
    antes = await conteos_de_orden(db_auth)
    with pytest.raises(service.CatalogoSinCargarError) as info:
        await crear(fabrica, orden(vid, (rid, 1)), usuario)
    assert info.value.mensaje == "El catálogo de estados de orden no está cargado"
    await assert_sin_rastro(db_auth, antes)


async def test_catalogo_sin_pendiente_tambien_lanza_catalogo_sin_cargar(fabrica, db_auth, escenario, usuario):
    await db_auth.ejecutar("DELETE FROM estado_orden WHERE codigo = 'PENDIENTE'")
    e = escenario
    antes = await conteos_de_orden(db_auth)
    with pytest.raises(service.CatalogoSinCargarError):
        await crear(fabrica, orden(e["vehiculo"], (e["r1"], 1)), usuario)
    await assert_sin_rastro(db_auth, antes)


async def test_vehiculo_inexistente_o_dado_de_baja_lanza_no_disponible_sin_rastro(
    fabrica, db_auth, escenario, usuario
):
    e = escenario
    baja = await sembrar_vehiculo(db_auth, e["cliente"], "ZZZ999", baja=True)
    antes = await conteos_de_orden(db_auth)
    for vehiculo in (999999, baja):
        with pytest.raises(service.VehiculoNoDisponibleError) as info:
            await crear(fabrica, orden(vehiculo, (e["r1"], 1)), usuario)
        assert info.value.mensaje == "El vehículo no existe o fue dado de baja"
    await assert_sin_rastro(db_auth, antes)


async def test_repuesto_inexistente_o_dado_de_baja_lanza_no_disponible_sin_rastro(
    fabrica, db_auth, escenario, usuario
):
    e = escenario
    baja = await sembrar_repuesto(db_auth, codigo="BAJA", borrado=True)
    antes = await conteos_de_orden(db_auth)
    for faltante in (999999, baja):
        with pytest.raises(service.RepuestoNoDisponibleError) as info:
            await crear(fabrica, orden(e["vehiculo"], (e["r1"], 1), (faltante, 1)), usuario)
        assert info.value.mensaje == "Algún repuesto no existe o fue dado de baja"
    await assert_sin_rastro(db_auth, antes)


async def test_total_fuera_de_rango_lanza_error_propio_sin_rastro(fabrica, db_auth, escenario, usuario):
    grande = await sembrar_repuesto(db_auth, codigo="G", precio="99999999.99")
    centavos = await sembrar_repuesto(db_auth, codigo="C", precio="1.00")
    antes = await conteos_de_orden(db_auth)
    for items in ([(grande, 1000)], [(grande, 100), (centavos, 1)]):
        with pytest.raises(service.TotalFueraDeRangoError):
            await crear(fabrica, orden(escenario["vehiculo"], *items), usuario)
    await assert_sin_rastro(db_auth, antes)


# --- IntegrityError traducido fuera del bloque (4.3) ---------------------------------


class _OrigConRestriccion(Exception):
    def __init__(self, nombre: str | None, texto: str = 'viola la restriccion "SECRETO_DE_LA_BASE"') -> None:
        super().__init__(texto)
        self.constraint_name = nombre


def uow_que_falla_en_items(sesion, nombre: str | None):
    uow = OrdenesUoW(sesion)

    async def explotar(items):
        raise IntegrityError("INSERT INTO item_orden ...", {}, _OrigConRestriccion(nombre))

    uow.items.add_todos = explotar
    return uow


@pytest.mark.parametrize(
    ("restriccion", "esperado", "mensaje"),
    [
        ("fk_orden_trabajo_vehiculo_id_vehiculo", "VehiculoNoDisponibleError", "El vehículo no existe o fue dado de baja"),
        ("fk_item_orden_repuesto_id_repuesto", "RepuestoNoDisponibleError", "Algún repuesto no existe o fue dado de baja"),
        ("uq_item_orden_orden_id_repuesto_id", "ConflictoError", "Los datos chocan con un registro existente"),
        ("restriccion_desconocida", "ConflictoError", "Los datos chocan con un registro existente"),
        (None, "ConflictoError", "Los datos chocan con un registro existente"),
    ],
)
async def test_integrity_error_se_traduce_por_nombre_con_rollback_total_y_sin_texto_de_la_base(
    fabrica, db_auth, escenario, usuario, restriccion, esperado, mensaje
):
    e = escenario
    antes = await conteos_de_orden(db_auth)
    async with fabrica() as sesion:
        uow = uow_que_falla_en_items(sesion, restriccion)
        with pytest.raises(service.ConflictoError) as info:
            await service.crear_orden(uow, orden(e["vehiculo"], (e["r1"], 1)), usuario)
    assert type(info.value).__name__ == esperado
    assert info.value.mensaje == mensaje
    assert "SECRETO_DE_LA_BASE" not in str(info.value) and "SECRETO_DE_LA_BASE" not in info.value.mensaje
    assert info.value.__cause__ is None
    await assert_sin_rastro(db_auth, antes)  # la orden ya insertada tras el primer flush se revirtio


# --- Concurrencia con la baja del vehiculo (4.4, D6) ----------------------------------


async def esperar_bloqueada(tarea: asyncio.Task) -> None:
    await asyncio.sleep(0.5)
    assert not tarea.done(), "la operacion debia esperar el bloqueo de fila"


async def test_baja_primero_el_alta_espera_y_responde_vehiculo_no_disponible(
    fabrica, db_auth, escenario, usuario
):
    e = escenario
    antes = await conteos_de_orden(db_auth)
    async with fabrica() as sesion_baja:
        uow_baja = ClientesUoW(sesion_baja)
        vehiculo = await uow_baja.vehiculos.get_vigente_para_baja(e["vehiculo"])  # FOR UPDATE, sin cerrar
        alta = asyncio.create_task(crear(fabrica, orden(e["vehiculo"], (e["r1"], 1)), usuario))
        await esperar_bloqueada(alta)
        await uow_baja.vehiculos.soft_delete(vehiculo)
        await sesion_baja.commit()
    with pytest.raises(service.VehiculoNoDisponibleError):
        await alta
    await assert_sin_rastro(db_auth, antes)
    assert (await db_auth.filas("SELECT borrado_en FROM vehiculo"))[0]["borrado_en"] is not None


async def test_alta_primero_la_baja_espera_y_ve_la_orden_abierta(fabrica, db_auth, escenario, usuario):
    e = escenario
    async with fabrica() as sesion_alta:
        uow = OrdenesUoW(sesion_alta)
        assert await uow.vehiculos.get_vigente_para_orden(e["vehiculo"]) is not None  # FOR SHARE, sin cerrar
        baja = asyncio.create_task(_baja(fabrica, e["vehiculo"]))
        await esperar_bloqueada(baja)
        from app.modules.ordenes.models import OrdenTrabajo

        await uow.ordenes.add(
            OrdenTrabajo(vehiculo_id=e["vehiculo"], estado="PENDIENTE", falla="f", total=Decimal("0"))
        )
        await sesion_alta.commit()
    with pytest.raises(servicio_clientes.VehiculoConOrdenesAbiertasError):
        await baja
    assert (await db_auth.filas("SELECT borrado_en FROM vehiculo"))[0]["borrado_en"] is None


async def _baja(fabrica, vehiculo_id):
    async with fabrica() as sesion:
        await servicio_clientes.dar_de_baja_vehiculo(ClientesUoW(sesion), vehiculo_id)


async def test_alta_y_baja_secuenciales_nunca_dejan_vehiculo_dado_de_baja_con_orden_abierta(
    fabrica, db_auth, escenario, usuario
):
    e = escenario
    await crear(fabrica, orden(e["vehiculo"], (e["r1"], 1)), usuario)
    with pytest.raises(servicio_clientes.VehiculoConOrdenesAbiertasError):
        await _baja(fabrica, e["vehiculo"])
    filas = await db_auth.filas(
        "SELECT count(*) AS n FROM orden_trabajo o JOIN vehiculo v ON v.id = o.vehiculo_id "
        "WHERE v.borrado_en IS NOT NULL AND o.estado IN ('PENDIENTE', 'EN_REPARACION')"
    )
    assert filas[0]["n"] == 0
