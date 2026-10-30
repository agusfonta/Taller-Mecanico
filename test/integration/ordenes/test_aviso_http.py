"""Aviso al cliente al terminar una orden, por HTTP (C-10, tarea 8.4, spec aviso-cliente)."""
import logging

import pytest
from fastapi import BackgroundTasks

from app.modules.ordenes import avisos
from app.modules.ordenes import router as router_ordenes
from app.modules.ordenes.unit_of_work import OrdenesUoW
from app.modules.usuarios.models import Rol
from test.integration.ordenes.ayudantes import (
    _movimiento_inicial,
    actor,
    escenario_c11,
    sembrar_cliente,
    sembrar_orden_completa,
    sembrar_repuesto,
    sembrar_vehiculo,
)

pytestmark = pytest.mark.integration

LOGGER = "app.modules.ordenes.avisos"


@pytest.fixture(autouse=True)
def sin_demora(monkeypatch):
    monkeypatch.setattr(avisos, "DEMORA_AVISO", 0)


@pytest.fixture
def cab(cookie_de, mundo_ciclo):
    roles = {"mecanico": "MECANICO", "admin": "ADMIN", "recepcion": "RECEPCION"}
    return {k: cookie_de(mundo_ciclo[k], (r,)) for k, r in roles.items()}


def avisos_registrados(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == LOGGER]


async def test_un_solo_aviso_con_cliente_y_orden_correctos_tras_el_200(http, db_auth, mundo_ciclo, cab, caplog):
    m = mundo_ciclo  # cliente sin usuario: igual recibe aviso (D7-a)
    caplog.set_level(logging.INFO, logger=LOGGER)
    oid = await sembrar_orden_completa(db_auth, m["vehiculo"], "EN_REPARACION", mecanico_id=m["mecanico"])
    r = await http.post(f"/ordenes/{oid}/terminar", headers=cab["mecanico"])
    assert r.status_code == 200
    assert avisos_registrados(caplog) == [f"Aviso a cliente {m['cliente']}: orden {oid} terminada"]


async def test_el_aviso_usa_el_cliente_de_la_orden_aunque_el_que_termina_sea_admin(
    http, db_auth, mundo_ciclo, cab, caplog
):
    caplog.set_level(logging.INFO, logger=LOGGER)
    otro_cliente = await sembrar_cliente(db_auth, "99", nombre="Otro")
    veh = await sembrar_vehiculo(db_auth, otro_cliente, "XXX999")
    oid = await sembrar_orden_completa(db_auth, veh, "EN_REPARACION", mecanico_id=mundo_ciclo["mecanico"])
    assert (await http.post(f"/ordenes/{oid}/terminar", headers=cab["admin"])).status_code == 200
    assert avisos_registrados(caplog) == [f"Aviso a cliente {otro_cliente}: orden {oid} terminada"]


async def test_sin_aviso_tras_el_409_del_caso_c11(http, db_auth, cookie_de, caplog):
    e = await escenario_c11(db_auth)
    caplog.set_level(logging.INFO, logger=LOGGER)
    r = await http.post(f"/ordenes/{e['orden']}/terminar", headers=cookie_de(e["mecanico"], ("MECANICO",)))
    assert r.status_code == 409
    assert avisos_registrados(caplog) == []


async def test_sin_aviso_tras_403_404_ni_409_de_estado(http, db_auth, mundo_ciclo, cab, caplog):
    m = mundo_ciclo
    caplog.set_level(logging.INFO, logger=LOGGER)
    ajena = await sembrar_orden_completa(db_auth, m["vehiculo"], "EN_REPARACION", mecanico_id=m["mecanico2"])
    pendiente = await sembrar_orden_completa(db_auth, m["vehiculo"], "PENDIENTE", mecanico_id=m["mecanico"])
    assert (await http.post(f"/ordenes/{ajena}/terminar", headers=cab["mecanico"])).status_code == 403
    assert (await http.post("/ordenes/999999/terminar", headers=cab["mecanico"])).status_code == 404
    assert (await http.post(f"/ordenes/{pendiente}/terminar", headers=cab["mecanico"])).status_code == 409
    assert (await http.post(f"/ordenes/{ajena}/terminar", headers=cab["recepcion"])).status_code == 403
    assert avisos_registrados(caplog) == []


async def test_iniciar_y_cancelar_no_avisan(http, db_auth, mundo_ciclo, cab, caplog):
    m = mundo_ciclo
    caplog.set_level(logging.INFO, logger=LOGGER)
    a = await sembrar_orden_completa(db_auth, m["vehiculo"])
    b = await sembrar_orden_completa(db_auth, m["vehiculo"])
    assert (await http.post(f"/ordenes/{a}/iniciar", headers=cab["mecanico"])).status_code == 200
    assert (await http.post(f"/ordenes/{b}/cancelar", headers=cab["recepcion"])).status_code == 200
    assert avisos_registrados(caplog) == []


async def test_el_handler_agenda_el_aviso_y_todavia_no_lo_ejecuta(fabrica, db_auth, mundo_ciclo, caplog):
    m = mundo_ciclo
    caplog.set_level(logging.INFO, logger=LOGGER)
    oid = await sembrar_orden_completa(db_auth, m["vehiculo"], "EN_REPARACION", mecanico_id=m["mecanico"])
    tareas = BackgroundTasks()
    async with fabrica() as sesion:
        detalle = await router_ordenes.terminar_orden(
            orden_id=oid,
            usuario=actor(m["mecanico"], Rol.MECANICO),
            uow=OrdenesUoW(sesion),
            background_tasks=tareas,
        )
    assert detalle.estado == "TERMINADA"
    assert [(t.func, t.args) for t in tareas.tasks] == [(avisos.avisar_cliente, (m["cliente"], oid))]
    assert avisos_registrados(caplog) == []  # agendado, no ejecutado
    await tareas()
    assert avisos_registrados(caplog) == [f"Aviso a cliente {m['cliente']}: orden {oid} terminada"]


async def test_el_handler_no_agenda_nada_si_el_servicio_falla(fabrica, db_auth, mundo_ciclo):
    from fastapi import HTTPException

    m = mundo_ciclo
    oid = await sembrar_orden_completa(db_auth, m["vehiculo"], "PENDIENTE", mecanico_id=m["mecanico"])
    tareas = BackgroundTasks()
    async with fabrica() as sesion:
        with pytest.raises(HTTPException) as info:
            await router_ordenes.terminar_orden(
                orden_id=oid,
                usuario=actor(m["mecanico"], Rol.MECANICO),
                uow=OrdenesUoW(sesion),
                background_tasks=tareas,
            )
    assert info.value.status_code == 409 and tareas.tasks == []
