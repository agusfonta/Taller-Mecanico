"""Navegacion entre entidades sobre la base real (C-03, spec ``modelo-de-datos``, D5/D9).

Sesiones de la app (``crear_fabrica_sesiones``) sobre la conexion migrada: la transaccion externa
de ``conexion_migrada`` se revierte al final, de modo que nada persiste.
"""
from contextlib import contextmanager
from decimal import Decimal

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import joinedload, selectinload

from app.core.database import crear_fabrica_sesiones
from app.core.repository import SoftDeleteRepository
from app.core.unit_of_work import UnitOfWork
from app.modules.clientes.models import Cliente, Vehiculo
from app.modules.ordenes.models import ItemOrden, OrdenTrabajo
from app.modules.repuestos.models import Repuesto
from app.modules.usuarios.models import Usuario
from test.integration.filas import cliente, estado, repuesto, usuario, vehiculo

pytestmark = pytest.mark.integration


@contextmanager
def contar_consultas(conexion):
    """Cuenta las sentencias emitidas por la conexion subyacente mientras dura el bloque."""
    emitidas: list[str] = []

    def _antes(_conn, _cursor, sentencia, *_args):
        emitidas.append(sentencia)

    sync = conexion.sync_connection
    event.listen(sync, "before_cursor_execute", _antes)
    try:
        yield emitidas
    finally:
        event.remove(sync, "before_cursor_execute", _antes)


@pytest.fixture
async def sesion(conexion_migrada):
    fabrica = crear_fabrica_sesiones(conexion_migrada)  # la fabrica de la app, sobre la conexion de prueba
    async with fabrica() as s:
        yield s


async def _cliente_con_dos_vehiculos(c):
    cid = await cliente(c, "30111222")
    await vehiculo(c, cid, "AB123CD")
    await vehiculo(c, cid, "ZZ999ZZ")
    return cid


async def test_cliente_con_vehiculos_precargados_y_vuelta_al_mismo_cliente(conexion_migrada, sesion):
    cid = await _cliente_con_dos_vehiculos(conexion_migrada)

    resultado = await sesion.execute(
        select(Cliente).where(Cliente.id == cid).options(selectinload(Cliente.vehiculos).joinedload(Vehiculo.cliente))
    )
    laura = resultado.scalar_one()

    assert sorted(v.patente for v in laura.vehiculos) == ["AB123CD", "ZZ999ZZ"]
    assert all(v.cliente is laura for v in laura.vehiculos)


async def test_sin_precarga_la_relacion_falla_y_no_emite_consultas(conexion_migrada, sesion):
    cid = await _cliente_con_dos_vehiculos(conexion_migrada)
    laura = (await sesion.execute(select(Cliente).where(Cliente.id == cid))).scalar_one()

    with contar_consultas(conexion_migrada) as emitidas:
        with pytest.raises(InvalidRequestError):
            laura.vehiculos  # noqa: B018 - el acceso es lo que se prueba
    assert emitidas == []


async def test_usuario_con_cliente_es_un_objeto_y_sin_cliente_es_none(conexion_migrada, sesion):
    con_cliente = await usuario(conexion_migrada, "con@example.com")
    sin_cliente = await usuario(conexion_migrada, "sin@example.com")
    await cliente(conexion_migrada, "1", usuario_id=con_cliente)

    filas = (
        await sesion.execute(
            select(Usuario).where(Usuario.id.in_([con_cliente, sin_cliente])).options(joinedload(Usuario.cliente))
        )
    ).scalars().unique().all()
    por_email = {u.email: u for u in filas}

    assert isinstance(por_email["con@example.com"].cliente, Cliente)
    assert por_email["sin@example.com"].cliente is None


async def test_orden_con_dos_items_por_la_relacion_se_persiste_con_unit_of_work(conexion_migrada, sesion):
    c = conexion_migrada
    await estado(c)
    veh = await vehiculo(c, await cliente(c))
    r1, r2 = await repuesto(c, "A-1"), await repuesto(c, "B-2")

    async with UnitOfWork(sesion):
        sesion.add(
            OrdenTrabajo(
                vehiculo_id=veh,
                estado="PENDIENTE",
                falla="ruido",
                items=[
                    ItemOrden(repuesto_id=r1, cantidad=1, precio_unitario=Decimal("10.00")),
                    ItemOrden(repuesto_id=r2, cantidad=2, precio_unitario=Decimal("5.50")),
                ],
            )
        )

    filas = (await c.execute(select(ItemOrden.__table__.c.orden_id, ItemOrden.__table__.c.cantidad))).all()
    orden_ids = {f[0] for f in filas}
    ordenes = (await c.execute(select(OrdenTrabajo.__table__.c.id))).scalars().all()
    assert len(filas) == 2 and sorted(f[1] for f in filas) == [1, 2]
    assert orden_ids == set(ordenes) and len(ordenes) == 1


async def test_item_orden_navega_a_su_orden_y_repuesto(conexion_migrada, sesion):
    c = conexion_migrada
    await estado(c)
    rid = await repuesto(c, "A-1")
    sesion.add(
        OrdenTrabajo(
            vehiculo_id=await vehiculo(c, await cliente(c)), estado="PENDIENTE", falla="x",
            items=[ItemOrden(repuesto_id=rid, cantidad=1, precio_unitario=Decimal("1.00"))],
        )
    )
    await sesion.flush()
    orden = (
        await sesion.execute(
            select(OrdenTrabajo).options(selectinload(OrdenTrabajo.items).selectinload(ItemOrden.repuesto))
        )
    ).scalar_one()
    assert orden.items[0].repuesto.codigo == "A-1"
    assert isinstance(orden.items[0].repuesto, Repuesto)


async def test_soft_delete_repository_encaja_con_el_modelo(conexion_migrada, sesion):
    cid = await cliente(conexion_migrada)
    vid = await vehiculo(conexion_migrada, cid, "AB123CD")
    repo = SoftDeleteRepository(sesion, Vehiculo)

    entidad = await repo.get_by_id(vid)
    assert entidad is not None and entidad.patente == "AB123CD"

    await repo.soft_delete(entidad)

    assert await repo.get_by_id(vid) is None
    conservada = await repo.get_by_id_including_deleted(vid)
    assert conservada is not None and conservada.borrado_en is not None


async def test_la_vuelta_a_la_madre_tambien_requiere_precarga(conexion_migrada, sesion):
    # Gotcha de lazy="raise": selectinload(vehiculos) NO puebla vehiculo.cliente; hay que encadenar
    # joinedload(Vehiculo.cliente) (los repositorios de C-06 lo hacen).
    cid = await _cliente_con_dos_vehiculos(conexion_migrada)
    laura = (
        await sesion.execute(select(Cliente).where(Cliente.id == cid).options(selectinload(Cliente.vehiculos)))
    ).scalar_one()
    with pytest.raises(InvalidRequestError):
        laura.vehiculos[0].cliente  # noqa: B018
