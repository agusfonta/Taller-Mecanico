"""POST /ordenes por HTTP contra PostgreSQL real (C-09, tarea 6.2, spec alta-ordenes)."""
from decimal import Decimal

import pytest

from test.integration.ordenes.ayudantes import (
    conteos_de_orden,
    fila_de_orden,
    historial_de_orden,
    items_de_orden,
    sembrar_catalogo,
    sembrar_cliente,
    sembrar_repuesto,
    sembrar_vehiculo,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def mundo(db_auth):
    await sembrar_catalogo(db_auth)
    cid = await sembrar_cliente(db_auth, "10")
    return {
        "vehiculo": await sembrar_vehiculo(db_auth, cid, "AAA111"),
        "cliente": cid,
        "r1": await sembrar_repuesto(db_auth, codigo="R1", precio="8500.00"),
        "r2": await sembrar_repuesto(db_auth, codigo="R2", precio="1200.50"),
    }


def cuerpo(mundo, **cambios):
    base = {
        "vehiculo_id": mundo["vehiculo"],
        "falla": "No arranca",
        "items": [{"repuesto_id": mundo["r1"], "cantidad": 2}, {"repuesto_id": mundo["r2"], "cantidad": 1}],
    }
    return {**base, **cambios}


def un_item(mundo, **campos):
    return {"items": [{"repuesto_id": mundo["r1"], "cantidad": 1, **campos}]}


# --- 201 (caso C-10) ----------------------------------------------------------------------


@pytest.mark.parametrize("rol", ["RECEPCION", "ADMIN"])
async def test_alta_con_dos_items_responde_201_con_detalle_completo(http, db_auth, usuario_con_rol, mundo, rol):
    uid, cab = await usuario_con_rol(rol)
    r = await http.post("/ordenes", json=cuerpo(mundo), headers=cab)
    assert r.status_code == 201, r.text
    datos = r.json()
    assert datos["estado"] == "PENDIENTE" and datos["mecanico_id"] is None
    assert datos["vehiculo_id"] == mundo["vehiculo"] and datos["falla"] == "No arranca"
    assert datos["total"] == "18200.50" and datos["creada_en"]
    assert [
        (i["repuesto_id"], i["codigo"], i["cantidad"], i["precio_unitario"], i["subtotal"])
        for i in datos["items"]
    ] == [
        (mundo["r1"], "R1", 2, "8500.00", "17000.00"),
        (mundo["r2"], "R2", 1, "1200.50", "1200.50"),
    ]
    assert [(h["desde_estado"], h["hasta_estado"], h["usuario_id"]) for h in datos["historial"]] == [
        (None, "PENDIENTE", uid)
    ]
    fila = await fila_de_orden(db_auth, datos["id"])
    assert fila["total"] == Decimal("18200.50")
    suma = sum(i["cantidad"] * i["precio_unitario"] for i in await items_de_orden(db_auth, datos["id"]))
    assert fila["total"] == suma
    assert len(await historial_de_orden(db_auth, datos["id"])) == 1


async def test_la_falla_se_recorta_y_el_cambio_de_precio_posterior_no_altera_la_orden(
    http, db_auth, usuario_con_rol, mundo, cookie_de
):
    _, cab = await usuario_con_rol("RECEPCION")
    creada = (await http.post("/ordenes", json=cuerpo(mundo, falla="  frenos  "), headers=cab)).json()
    assert creada["falla"] == "frenos"
    admin = await db_auth.crear_usuario("admin@example.com", "x" * 10, roles=("ADMIN",))
    r = await http.patch(f"/repuestos/{mundo['r1']}", json={"precio": "9999.99"}, headers=cookie_de(admin))
    assert r.status_code == 200
    detalle = (await http.get(f"/ordenes/{creada['id']}", headers=cab)).json()
    assert detalle["total"] == "18200.50"
    assert detalle["items"][0]["precio_unitario"] == "8500.00"
    assert (await fila_de_orden(db_auth, creada["id"]))["total"] == Decimal("18200.50")


# --- Acceso --------------------------------------------------------------------------------


async def test_sin_sesion_es_401_sin_filas(http, db_auth, mundo):
    assert (await http.post("/ordenes", json=cuerpo(mundo))).status_code == 401
    assert set((await conteos_de_orden(db_auth)).values()) == {0}


async def test_cambio_de_contrasena_pendiente_es_403(http, usuario_con_rol, mundo):
    _, cab = await usuario_con_rol("RECEPCION", debe_cambiar_password=True)
    assert (await http.post("/ordenes", json=cuerpo(mundo), headers=cab)).status_code == 403


@pytest.mark.parametrize("rol", ["MECANICO", "CLIENTE"])
async def test_mecanico_y_cliente_reciben_403_antes_de_validar_el_cuerpo(http, db_auth, usuario_con_rol, mundo, rol):
    _, cab = await usuario_con_rol(rol)
    assert (await http.post("/ordenes", json=cuerpo(mundo), headers=cab)).status_code == 403
    assert (await http.post("/ordenes", json={}, headers=cab)).status_code == 403  # 403 antes que 422
    assert set((await conteos_de_orden(db_auth)).values()) == {0}


# --- 422 de contrato ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "modificar",
    [
        lambda m: {"items": []},
        lambda m: {"items": [{"repuesto_id": m["r1"], "cantidad": 1}, {"repuesto_id": m["r1"], "cantidad": 2}]},
        lambda m: un_item(m, precio_unitario=1),
        lambda m: {"total": 1},
        lambda m: {"estado": "TERMINADA"},
        lambda m: {"mecanico_id": 1},
        lambda m: {"falla": "   "},
        lambda m: {"vehiculo_id": "1"},
        lambda m: {"vehiculo_id": 2**63},
        lambda m: un_item(m, cantidad=0),
        lambda m: un_item(m, cantidad="2"),
        lambda m: un_item(m, cantidad=1.5),
        lambda m: un_item(m, cantidad=True),
        lambda m: un_item(m, cantidad=-1),
    ],
)
async def test_contrato_invalido_es_422_sin_filas(http, db_auth, usuario_con_rol, mundo, modificar):
    _, cab = await usuario_con_rol("RECEPCION")
    r = await http.post("/ordenes", json=cuerpo(mundo, **modificar(mundo)), headers=cab)
    assert r.status_code == 422
    assert set((await conteos_de_orden(db_auth)).values()) == {0}


# --- 409 ----------------------------------------------------------------------------------------


async def assert_409_sin_filas(http, db_auth, cab, datos, mensaje):
    antes = await conteos_de_orden(db_auth)
    r = await http.post("/ordenes", json=datos, headers=cab)
    assert r.status_code == 409, r.text
    assert r.json() == {"detail": mensaje}
    for ajeno in ("violates", "constraint", "fk_", "uq_", "asyncpg", "sqlalchemy", "INSERT"):
        assert ajeno not in r.text
    assert await conteos_de_orden(db_auth) == antes


async def test_repuesto_inexistente_o_dado_de_baja_es_409(http, db_auth, usuario_con_rol, mundo):
    _, cab = await usuario_con_rol("RECEPCION")
    baja = await sembrar_repuesto(db_auth, codigo="BAJA", borrado=True)
    mensaje = "Algún repuesto no existe o fue dado de baja"
    for faltante in (999999, baja):
        items = [{"repuesto_id": mundo["r1"], "cantidad": 1}, {"repuesto_id": faltante, "cantidad": 1}]
        await assert_409_sin_filas(http, db_auth, cab, cuerpo(mundo, items=items), mensaje)


async def test_vehiculo_inexistente_o_dado_de_baja_es_409(http, db_auth, usuario_con_rol, mundo):
    _, cab = await usuario_con_rol("RECEPCION")
    baja = await sembrar_vehiculo(db_auth, mundo["cliente"], "ZZZ999", baja=True)
    for vehiculo in (999999, baja):
        await assert_409_sin_filas(
            http, db_auth, cab, cuerpo(mundo, vehiculo_id=vehiculo), "El vehículo no existe o fue dado de baja"
        )


async def test_catalogo_vacio_es_409_con_su_mensaje(http, db_auth, usuario_con_rol, mundo):
    _, cab = await usuario_con_rol("RECEPCION")
    await db_auth.ejecutar("DELETE FROM estado_orden")
    await assert_409_sin_filas(http, db_auth, cab, cuerpo(mundo), "El catálogo de estados de orden no está cargado")


async def test_total_desbordado_es_409_y_no_500(http, db_auth, usuario_con_rol, mundo):
    _, cab = await usuario_con_rol("RECEPCION")
    grande = await sembrar_repuesto(db_auth, codigo="G", precio="99999999.99")
    items = [{"repuesto_id": grande, "cantidad": 1000}]
    await assert_409_sin_filas(
        http, db_auth, cab, cuerpo(mundo, items=items), "El total de la orden supera el máximo admitido"
    )
