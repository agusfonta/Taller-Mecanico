"""Reposicion de stock por HTTP (C-08, 7.4, 7.6; spec stock-repuestos)."""
import asyncio

import pytest
from sqlalchemy.exc import DBAPIError

from app.modules.repuestos.repository import MovimientoStockRepository
from test.integration.repuestos.ayudantes import fila_de, movimientos_de, sembrar_repuesto

pytestmark = pytest.mark.integration


async def test_reponer_suma_y_registra_el_movimiento_del_admin(http, db_auth, admin, admin_id):
    rid = await sembrar_repuesto(db_auth, stock=2)
    r = await http.post(f"/repuestos/{rid}/reponer", json={"cantidad": 5}, headers=admin)
    assert r.status_code == 200
    assert r.json() == {"id": rid, "codigo": "FIL-001", "descripcion": "Filtro de aceite", "precio": "8000.00", "stock": 7}
    assert (await fila_de(db_auth, rid))["stock"] == 7
    movs = await movimientos_de(db_auth, rid)
    assert [(m["cantidad"], m["motivo"], m["usuario_id"], m["orden_id"]) for m in movs] == [
        (5, "Reposición", admin_id, None)
    ]


@pytest.mark.parametrize(
    "cuerpo",
    [{"cantidad": 0}, {"cantidad": -3}, {"cantidad": 1.5}, {"cantidad": "5"}, {"cantidad": True}, {"cantidad": 1000001}, {"cantidad": 5, "motivo": "x"}, {}],
)
async def test_cuerpo_invalido_es_422_sin_cambios(http, db_auth, admin, cuerpo):
    rid = await sembrar_repuesto(db_auth, stock=2)
    assert (await http.post(f"/repuestos/{rid}/reponer", json=cuerpo, headers=admin)).status_code == 422
    assert (await fila_de(db_auth, rid))["stock"] == 2
    assert await movimientos_de(db_auth, rid) == []


async def test_reponer_dado_de_baja_o_inexistente_es_404_sin_movimiento(http, db_auth, admin):
    baja = await sembrar_repuesto(db_auth, stock=2, borrado=True)
    assert (await http.post(f"/repuestos/{baja}/reponer", json={"cantidad": 1}, headers=admin)).status_code == 404
    assert (await http.post("/repuestos/999999/reponer", json={"cantidad": 1}, headers=admin)).status_code == 404
    assert await movimientos_de(db_auth, baja) == []
    assert (await fila_de(db_auth, baja))["stock"] == 2


async def test_recepcion_no_repone(http, db_auth, usuario_con_rol):
    rid = await sembrar_repuesto(db_auth, stock=2)
    _, cab = await usuario_con_rol("RECEPCION")
    assert (await http.post(f"/repuestos/{rid}/reponer", json={"cantidad": 1}, headers=cab)).status_code == 403
    assert (await fila_de(db_auth, rid))["stock"] == 2


async def test_desborde_del_stock_es_409_propio_sin_cambios(http, db_auth, admin):
    rid = await sembrar_repuesto(db_auth, stock=2147483000)
    r = await http.post(f"/repuestos/{rid}/reponer", json={"cantidad": 1000}, headers=admin)
    assert r.status_code == 409
    assert "integer" not in r.text.lower() and "out of range" not in r.text.lower()
    assert (await fila_de(db_auth, rid))["stock"] == 2147483000
    assert await movimientos_de(db_auth, rid) == []


async def test_falla_al_registrar_el_movimiento_deja_el_stock_intacto(http, db_auth, admin, monkeypatch):
    rid = await sembrar_repuesto(db_auth, stock=2)

    async def falla(self, entidad):
        raise RuntimeError("falla simulada del movimiento")

    monkeypatch.setattr(MovimientoStockRepository, "add", falla)
    with pytest.raises(RuntimeError):
        await http.post(f"/repuestos/{rid}/reponer", json={"cantidad": 5}, headers=admin)
    assert (await fila_de(db_auth, rid))["stock"] == 2
    assert await movimientos_de(db_auth, rid) == []


@pytest.mark.parametrize("repeticion", range(3))
async def test_dos_reposiciones_simultaneas_se_aplican_ambas(fabrica_http, db_auth, admin, repeticion):
    rid = await sembrar_repuesto(db_auth, stock=0)
    async with fabrica_http("203.0.113.10") as a, fabrica_http("203.0.113.11") as b:
        ra, rb = await asyncio.gather(
            a.post(f"/repuestos/{rid}/reponer", json={"cantidad": 5}, headers=admin),
            b.post(f"/repuestos/{rid}/reponer", json={"cantidad": 5}, headers=admin),
        )
    assert (ra.status_code, rb.status_code) == (200, 200)
    assert sorted([ra.json()["stock"], rb.json()["stock"]]) == [5, 10]
    assert (await fila_de(db_auth, rid))["stock"] == 10
    assert [m["cantidad"] for m in await movimientos_de(db_auth, rid)] == [5, 5]


async def test_invariante_stock_igual_a_la_suma_de_movimientos(http, db_auth, admin):
    alta = {"codigo": "INV", "descripcion": "Invariante", "precio": 100, "stock_inicial": 10}
    rid = (await http.post("/repuestos", json=alta, headers=admin)).json()["id"]
    for cantidad in (5, 3):
        assert (await http.post(f"/repuestos/{rid}/reponer", json={"cantidad": cantidad}, headers=admin)).status_code == 200
    movs = await movimientos_de(db_auth, rid)
    assert [m["cantidad"] for m in movs] == [10, 5, 3]
    assert (await fila_de(db_auth, rid))["stock"] == 18 == sum(m["cantidad"] for m in movs)


async def test_el_movimiento_creado_por_la_api_no_se_puede_modificar_ni_borrar(http, db_auth, admin):
    rid = await sembrar_repuesto(db_auth, stock=2)
    await http.post(f"/repuestos/{rid}/reponer", json={"cantidad": 5}, headers=admin)
    mov = (await movimientos_de(db_auth, rid))[0]
    with pytest.raises(DBAPIError):
        await db_auth.ejecutar("UPDATE movimiento_stock SET cantidad = 999 WHERE id = :i", i=mov["id"])
    with pytest.raises(DBAPIError):
        await db_auth.ejecutar("DELETE FROM movimiento_stock WHERE id = :i", i=mov["id"])
    assert (await movimientos_de(db_auth, rid))[0]["cantidad"] == 5
