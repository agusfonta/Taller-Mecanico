"""Servicios ``iniciar_orden``, ``terminar_orden`` y ``cancelar_orden`` con UoW real (C-10, grupos 4 a 6)."""
import asyncio

import pytest

from app.modules.ordenes import service
from app.modules.ordenes.repository import HistorialEstadoOrdenRepository
from app.modules.ordenes.unit_of_work import OrdenesUoW
from app.modules.usuarios.models import Rol
from test.integration.ordenes.ayudantes import (
    actor,
    conteos_ciclo,
    escenario_c11,
    fila_de_orden,
    historial_de_orden,
    items_de_orden,
    movimientos_de_orden,
    sembrar_catalogo,
    sembrar_cliente,
    sembrar_orden_completa,
    sembrar_repuesto,
    sembrar_vehiculo,
    stock_de,
)

pytestmark = pytest.mark.integration


async def iniciar(fabrica, orden_id, usuario):
    async with fabrica() as sesion:
        return await service.iniciar_orden(OrdenesUoW(sesion), orden_id, usuario)


@pytest.fixture
async def mundo(db_auth):
    await sembrar_catalogo(db_auth)
    cid = await sembrar_cliente(db_auth, "10")
    return {
        "vehiculo": await sembrar_vehiculo(db_auth, cid, "AAA111"),
        "mecanico": await db_auth.crear_usuario("mec1@example.com", "x" * 10, roles=("MECANICO",)),
        "mecanico2": await db_auth.crear_usuario("mec2@example.com", "x" * 10, roles=("MECANICO",)),
    }


# --- iniciar: camino feliz (4.2) --------------------------------------------------------------


@pytest.mark.parametrize("quien", ["mecanico", "mecanico2"])
async def test_iniciar_asigna_al_actor_y_firma_la_linea_de_historial(fabrica, db_auth, mundo, quien):
    oid = await sembrar_orden_completa(db_auth, mundo["vehiculo"], "PENDIENTE")
    uid = mundo[quien]
    detalle = await iniciar(fabrica, oid, actor(uid, Rol.MECANICO))
    fila = await fila_de_orden(db_auth, oid)
    assert fila["estado"] == "EN_REPARACION" and fila["mecanico_id"] == uid
    lineas = await historial_de_orden(db_auth, oid)
    assert [(h["desde_estado"], h["hasta_estado"], h["usuario_id"]) for h in lineas] == [
        ("PENDIENTE", "EN_REPARACION", uid)
    ]
    assert detalle.estado == "EN_REPARACION" and detalle.mecanico_id == uid


async def test_iniciar_devuelve_el_detalle_con_el_historial_nuevo_y_los_items(fabrica, db_auth, mundo):
    rid = await sembrar_repuesto(db_auth, codigo="R1", precio="10.00", stock=5)
    oid = await sembrar_orden_completa(db_auth, mundo["vehiculo"], items=((rid, 2, "10.00"),))
    async with fabrica() as sesion:
        detalle = await service.iniciar_orden(OrdenesUoW(sesion), oid, actor(mundo["mecanico"], Rol.MECANICO))
        assert [h.hasta_estado for h in detalle.historial] == ["EN_REPARACION"]
        assert [(i.repuesto.codigo, i.cantidad) for i in detalle.items] == [("R1", 2)]
        assert detalle.vehiculo.cliente.id is not None
    assert await stock_de(db_auth, rid) == 5
    assert await movimientos_de_orden(db_auth, oid) == []


# --- iniciar: rechazos sin escrituras (4.3) ----------------------------------------------------


async def test_iniciar_inexistente_es_orden_no_encontrada(fabrica, db_auth, mundo):
    antes = await conteos_ciclo(db_auth)
    with pytest.raises(service.OrdenNoEncontradaError):
        await iniciar(fabrica, 9999, actor(mundo["mecanico"], Rol.MECANICO))
    assert await conteos_ciclo(db_auth) == antes


@pytest.mark.parametrize("estado", ["EN_REPARACION", "TERMINADA", "CANCELADA"])
async def test_iniciar_desde_otro_estado_es_transicion_invalida_sin_escrituras(fabrica, db_auth, mundo, estado):
    oid = await sembrar_orden_completa(db_auth, mundo["vehiculo"], estado, mecanico_id=mundo["mecanico2"])
    antes, fila = await conteos_ciclo(db_auth), await fila_de_orden(db_auth, oid)
    with pytest.raises(service.TransicionInvalidaError) as info:
        await iniciar(fabrica, oid, actor(mundo["mecanico"], Rol.MECANICO))
    assert estado in info.value.mensaje and "iniciar" in info.value.mensaje
    assert await conteos_ciclo(db_auth) == antes and await fila_de_orden(db_auth, oid) == fila


async def test_iniciar_pendiente_preasignada_a_otro_es_conflicto_sin_escrituras(fabrica, db_auth, mundo):
    oid = await sembrar_orden_completa(db_auth, mundo["vehiculo"], "PENDIENTE", mecanico_id=mundo["mecanico2"])
    antes, fila = await conteos_ciclo(db_auth), await fila_de_orden(db_auth, oid)
    with pytest.raises(service.OrdenAsignadaAOtroError):
        await iniciar(fabrica, oid, actor(mundo["mecanico"], Rol.MECANICO))
    assert await conteos_ciclo(db_auth) == antes and await fila_de_orden(db_auth, oid) == fila


async def test_iniciar_pendiente_preasignada_al_mismo_se_inicia(fabrica, db_auth, mundo):
    oid = await sembrar_orden_completa(db_auth, mundo["vehiculo"], "PENDIENTE", mecanico_id=mundo["mecanico"])
    await iniciar(fabrica, oid, actor(mundo["mecanico"], Rol.MECANICO))
    fila = await fila_de_orden(db_auth, oid)
    assert fila["estado"] == "EN_REPARACION" and fila["mecanico_id"] == mundo["mecanico"]
    assert len(await historial_de_orden(db_auth, oid)) == 1


async def test_iniciar_con_catalogo_sin_en_reparacion_es_catalogo_sin_cargar(fabrica, db_auth, mundo):
    oid = await sembrar_orden_completa(db_auth, mundo["vehiculo"], "PENDIENTE")
    await db_auth.ejecutar("DELETE FROM estado_orden WHERE codigo = 'EN_REPARACION'")
    antes, fila = await conteos_ciclo(db_auth), await fila_de_orden(db_auth, oid)
    with pytest.raises(service.CatalogoSinCargarError):
        await iniciar(fabrica, oid, actor(mundo["mecanico"], Rol.MECANICO))
    assert await conteos_ciclo(db_auth) == antes and await fila_de_orden(db_auth, oid) == fila


# --- iniciar: IntegrityError traducido fuera del bloque (4.4) ----------------------------------


def _historial_con(monkeypatch, **cambios):
    """Doble de ``HistorialEstadoOrdenRepository.add``: corrompe la linea DESPUES del update de la orden."""
    original = HistorialEstadoOrdenRepository.add

    async def add(self, entidad):
        for campo, valor in cambios.items():
            setattr(entidad, campo, valor)
        return await original(self, entidad)

    monkeypatch.setattr(HistorialEstadoOrdenRepository, "add", add)


async def test_fk_del_estado_destino_se_traduce_a_catalogo_sin_cargar_con_rollback_total(
    fabrica, db_auth, mundo, monkeypatch
):
    oid = await sembrar_orden_completa(db_auth, mundo["vehiculo"], "PENDIENTE")
    antes, fila = await conteos_ciclo(db_auth), await fila_de_orden(db_auth, oid)
    _historial_con(monkeypatch, hasta_estado="INEXISTENTE")
    with pytest.raises(service.CatalogoSinCargarError) as info:
        await iniciar(fabrica, oid, actor(mundo["mecanico"], Rol.MECANICO))
    assert "fk_" not in info.value.mensaje and "violates" not in info.value.mensaje
    assert await conteos_ciclo(db_auth) == antes and await fila_de_orden(db_auth, oid) == fila


async def test_restriccion_desconocida_es_conflicto_generico_sin_texto_de_la_base(
    fabrica, db_auth, mundo, monkeypatch
):
    oid = await sembrar_orden_completa(db_auth, mundo["vehiculo"], "PENDIENTE")
    antes, fila = await conteos_ciclo(db_auth), await fila_de_orden(db_auth, oid)
    _historial_con(monkeypatch, usuario_id=987654)
    with pytest.raises(service.ConflictoError) as info:
        await iniciar(fabrica, oid, actor(mundo["mecanico"], Rol.MECANICO))
    assert type(info.value) is service.ConflictoError
    assert info.value.mensaje == service.ConflictoError.mensaje
    assert await conteos_ciclo(db_auth) == antes and await fila_de_orden(db_auth, oid) == fila


# --- iniciar: concurrencia (4.5) -----------------------------------------------------------------


@pytest.mark.parametrize("repeticion", range(5))
async def test_dos_mecanicos_inician_a_la_vez_gana_uno(fabrica, db_auth, mundo, repeticion):
    oid = await sembrar_orden_completa(db_auth, mundo["vehiculo"], "PENDIENTE")
    a, b = mundo["mecanico"], mundo["mecanico2"]
    resultados = await asyncio.gather(
        iniciar(fabrica, oid, actor(a, Rol.MECANICO)),
        iniciar(fabrica, oid, actor(b, Rol.MECANICO)),
        return_exceptions=True,
    )
    fallos = [r for r in resultados if isinstance(r, service.TransicionInvalidaError)]
    exitos = [r for r in resultados if not isinstance(r, BaseException)]
    assert len(fallos) == 1 and len(exitos) == 1
    lineas = await historial_de_orden(db_auth, oid)
    assert len(lineas) == 1 and lineas[0]["hasta_estado"] == "EN_REPARACION"
    ganador = (await fila_de_orden(db_auth, oid))["mecanico_id"]
    assert ganador == exitos[0].mecanico_id == lineas[0]["usuario_id"] and ganador in (a, b)
