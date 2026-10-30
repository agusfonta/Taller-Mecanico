"""Numero fijo de consultas del detalle de orden (C-09, tarea 7.1, caso C-15, D7)."""
import pytest
from sqlalchemy import event

from test.integration.ordenes.ayudantes import (
    sembrar_catalogo,
    sembrar_cliente,
    sembrar_orden_completa,
    sembrar_repuesto,
    sembrar_vehiculo,
)

pytestmark = pytest.mark.integration

TABLAS = ("FROM orden_trabajo", "FROM item_orden", "FROM historial_estado_orden")


@pytest.fixture
def sentencias(motor_auth):
    capturadas: list[str] = []

    def capturar(conn, cursor, statement, parameters, context, executemany):
        capturadas.append(statement)

    event.listen(motor_auth.sync_engine, "before_cursor_execute", capturar)
    yield capturadas
    event.remove(motor_auth.sync_engine, "before_cursor_execute", capturar)


@pytest.fixture
async def ordenes(db_auth):
    """Una orden con 2 items y otra con 4, ambas con historial."""
    await sembrar_catalogo(db_auth)
    vid = await sembrar_vehiculo(db_auth, await sembrar_cliente(db_auth, "1"), "AAA111")
    repuestos = [await sembrar_repuesto(db_auth, codigo=f"R{n}") for n in range(4)]
    uid = await db_auth.crear_usuario("recepcion@example.com", "x" * 10, roles=("RECEPCION",))
    dos = await sembrar_orden_completa(db_auth, vid, items=tuple((r, 1, "10.00") for r in repuestos[:2]))
    cuatro = await sembrar_orden_completa(db_auth, vid, items=tuple((r, 2, "10.00") for r in repuestos))
    for oid in (dos, cuatro):
        for desde, hasta in ((None, "PENDIENTE"), ("PENDIENTE", "EN_REPARACION")):
            await db_auth.ejecutar(
                "INSERT INTO historial_estado_orden (orden_id, desde_estado, hasta_estado, usuario_id) "
                "VALUES (:o, :d, :h, :u)",
                o=oid, d=desde, h=hasta, u=uid,
            )
    cab = {"uid": uid}
    return {"dos": dos, "cuatro": cuatro, **cab}


async def detalle_y_sentencias(http, sentencias, cab, orden_id):
    sentencias.clear()
    r = await http.get(f"/ordenes/{orden_id}", headers=cab)
    assert r.status_code == 200, r.text
    return r.json(), list(sentencias)


async def test_el_detalle_ejecuta_la_misma_cantidad_de_sentencias_con_2_y_con_4_items(
    http, sentencias, ordenes, cookie_de
):
    cab = cookie_de(ordenes["uid"], ("RECEPCION",))
    d2, s2 = await detalle_y_sentencias(http, sentencias, cab, ordenes["dos"])
    d4, s4 = await detalle_y_sentencias(http, sentencias, cab, ordenes["cuatro"])
    assert len(d2["items"]) == 2 and len(d4["items"]) == 4
    assert len(d2["historial"]) == 2 and len(d4["historial"]) == 2
    assert len(s2) == len(s4)


async def test_solo_tres_sentencias_tocan_las_tablas_de_orden_y_ninguna_es_por_item(
    http, sentencias, ordenes, cookie_de
):
    cab = cookie_de(ordenes["uid"], ("RECEPCION",))
    for clave in ("dos", "cuatro"):
        _, ejecutadas = await detalle_y_sentencias(http, sentencias, cab, ordenes[clave])
        tocan = [s for s in ejecutadas if any(t in s for t in TABLAS)]
        assert len(tocan) == 3, tocan
        por_tabla = {t: [s for s in tocan if t in s] for t in TABLAS}
        assert all(len(v) == 1 for v in por_tabla.values())
        assert all("JOIN" not in s or "repuesto" in s or "vehiculo" in s for s in tocan)
        # ni una sentencia por item: el repuesto viaja en el JOIN de la sentencia de items
        assert not any(s.lstrip().startswith("SELECT") and "FROM repuesto" in s.split("JOIN")[0] for s in ejecutadas)
