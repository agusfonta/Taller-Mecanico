"""Servicio ``cancelar_orden`` con UoW real (C-10, grupo 6, caso C-13)."""
import asyncio

import pytest

from app.modules.ordenes import service
from app.modules.ordenes.unit_of_work import OrdenesUoW
from app.modules.usuarios.models import Rol
from test.integration.ordenes.ayudantes import (
    actor,
    conteos_ciclo,
    fila_de_orden,
    historial_de_orden,
    movimientos_de_orden,
    sembrar_cliente,
    sembrar_orden_completa,
    sembrar_repuesto,
    sembrar_vehiculo,
    stock_de,
)

pytestmark = pytest.mark.integration


async def cancelar(fabrica, orden_id, usuario):
    async with fabrica() as sesion:
        return await service.cancelar_orden(OrdenesUoW(sesion), orden_id, usuario)


async def iniciar(fabrica, orden_id, usuario):
    async with fabrica() as sesion:
        return await service.iniciar_orden(OrdenesUoW(sesion), orden_id, usuario)


@pytest.fixture
async def duenos(db_auth, mundo_ciclo):
    """Dos clientes con usuario y vehiculo propio: ``dueno`` y ``otro``."""
    resultado = {}
    for nombre, doc, patente in (("dueno", "30", "DDD111"), ("otro", "40", "OOO222")):
        uid = await db_auth.crear_usuario(f"{nombre}@example.com", "x" * 10, roles=("CLIENTE",))
        cid = await sembrar_cliente(db_auth, doc, usuario_id=uid)
        resultado[nombre] = {"uid": uid, "vehiculo": await sembrar_vehiculo(db_auth, cid, patente)}
    return resultado


# --- 6.1 camino feliz ----------------------------------------------------------------------------------


@pytest.mark.parametrize("quien", ["recepcion", "admin", "dueno"])
async def test_recepcion_admin_y_dueno_cancelan_una_pendiente(fabrica, db_auth, mundo_ciclo, duenos, quien):
    m = mundo_ciclo
    rid = await sembrar_repuesto(db_auth, codigo="R1", stock=5)
    oid = await sembrar_orden_completa(db_auth, duenos["dueno"]["vehiculo"], items=((rid, 2, "10.00"),))
    usuario = {
        "recepcion": actor(m["recepcion"], Rol.RECEPCION),
        "admin": actor(m["admin"], Rol.ADMIN),
        "dueno": actor(duenos["dueno"]["uid"], Rol.CLIENTE),
    }[quien]
    detalle = await cancelar(fabrica, oid, usuario)
    assert detalle.estado == "CANCELADA"
    assert (await fila_de_orden(db_auth, oid))["estado"] == "CANCELADA"
    lineas = await historial_de_orden(db_auth, oid)
    assert [(h["desde_estado"], h["hasta_estado"], h["usuario_id"]) for h in lineas] == [
        ("PENDIENTE", "CANCELADA", usuario.id)
    ]
    assert [h.hasta_estado for h in detalle.historial] == ["CANCELADA"]
    assert await movimientos_de_orden(db_auth, oid) == [] and await stock_de(db_auth, rid) == 5


# --- 6.2 rechazos ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("estado", ["PENDIENTE", "EN_REPARACION", "TERMINADA", "CANCELADA"])
@pytest.mark.parametrize("quien", ["otro", "mecanico"])
async def test_sin_permiso_es_403_aun_sobre_estados_invalidos(fabrica, db_auth, mundo_ciclo, duenos, estado, quien):
    m = mundo_ciclo
    oid = await sembrar_orden_completa(
        db_auth, duenos["dueno"]["vehiculo"], estado, mecanico_id=m["mecanico"]
    )
    usuario = (
        actor(duenos["otro"]["uid"], Rol.CLIENTE) if quien == "otro" else actor(m["mecanico"], Rol.MECANICO)
    )
    antes, fila = await conteos_ciclo(db_auth), await fila_de_orden(db_auth, oid)
    with pytest.raises(service.SinPermisoSobreOrdenError):
        await cancelar(fabrica, oid, usuario)
    assert await conteos_ciclo(db_auth) == antes and await fila_de_orden(db_auth, oid) == fila


@pytest.mark.parametrize("estado", ["EN_REPARACION", "TERMINADA", "CANCELADA"])
@pytest.mark.parametrize("quien", ["recepcion", "admin", "dueno"])
async def test_con_permiso_sobre_estado_no_pendiente_es_transicion_invalida(
    fabrica, db_auth, mundo_ciclo, duenos, estado, quien
):
    m = mundo_ciclo
    oid = await sembrar_orden_completa(
        db_auth, duenos["dueno"]["vehiculo"], estado, mecanico_id=m["mecanico"]
    )
    usuario = {
        "recepcion": actor(m["recepcion"], Rol.RECEPCION),
        "admin": actor(m["admin"], Rol.ADMIN),
        "dueno": actor(duenos["dueno"]["uid"], Rol.CLIENTE),
    }[quien]
    antes, fila = await conteos_ciclo(db_auth), await fila_de_orden(db_auth, oid)
    with pytest.raises(service.TransicionInvalidaError) as info:
        await cancelar(fabrica, oid, usuario)
    assert estado in info.value.mensaje and "cancelar" in info.value.mensaje
    assert await conteos_ciclo(db_auth) == antes and await fila_de_orden(db_auth, oid) == fila


@pytest.mark.parametrize("rol", [Rol.CLIENTE, Rol.RECEPCION, Rol.ADMIN])
async def test_cancelar_inexistente_es_404(fabrica, db_auth, mundo_ciclo, rol):
    antes = await conteos_ciclo(db_auth)
    with pytest.raises(service.OrdenNoEncontradaError):
        await cancelar(fabrica, 9999, actor(mundo_ciclo["recepcion"], rol))
    assert await conteos_ciclo(db_auth) == antes


async def test_mecanico_que_ademas_es_recepcion_si_cancela(fabrica, db_auth, mundo_ciclo):
    m = mundo_ciclo
    oid = await sembrar_orden_completa(db_auth, m["vehiculo"])
    await cancelar(fabrica, oid, actor(m["mecanico"], Rol.MECANICO, Rol.RECEPCION))
    assert (await fila_de_orden(db_auth, oid))["estado"] == "CANCELADA"


async def test_cancelar_con_catalogo_sin_cancelada_es_catalogo_sin_cargar(fabrica, db_auth, mundo_ciclo):
    oid = await sembrar_orden_completa(db_auth, mundo_ciclo["vehiculo"])
    await db_auth.ejecutar("DELETE FROM estado_orden WHERE codigo = 'CANCELADA'")
    antes = await conteos_ciclo(db_auth)
    with pytest.raises(service.CatalogoSinCargarError):
        await cancelar(fabrica, oid, actor(mundo_ciclo["recepcion"], Rol.RECEPCION))
    assert await conteos_ciclo(db_auth) == antes


# --- 6.3 concurrencia -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("repeticion", range(5))
async def test_iniciar_y_cancelar_a_la_vez_gana_uno_solo(fabrica, db_auth, mundo_ciclo, repeticion):
    m = mundo_ciclo
    oid = await sembrar_orden_completa(db_auth, m["vehiculo"])
    resultados = await asyncio.gather(
        iniciar(fabrica, oid, actor(m["mecanico"], Rol.MECANICO)),
        cancelar(fabrica, oid, actor(m["recepcion"], Rol.RECEPCION)),
        return_exceptions=True,
    )
    assert sum(isinstance(r, service.TransicionInvalidaError) for r in resultados) == 1
    assert sum(not isinstance(r, BaseException) for r in resultados) == 1
    lineas = await historial_de_orden(db_auth, oid)
    assert len(lineas) == 1
    estado = (await fila_de_orden(db_auth, oid))["estado"]
    assert estado == lineas[0]["hasta_estado"] and estado in ("EN_REPARACION", "CANCELADA")
