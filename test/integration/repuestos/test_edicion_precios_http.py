"""PATCH de repuestos e historial de precios (C-08, 7.1-7.3, 7.6; specs catalogo/historial)."""
import asyncio
from decimal import Decimal

import pytest
from sqlalchemy.exc import DBAPIError

from app.modules.repuestos.repository import HistorialPrecioRepository, RepuestoRepository
from test.integration.repuestos.ayudantes import fila_de, historial_de, sembrar_repuesto

pytestmark = pytest.mark.integration


async def test_patch_de_stock_es_422_y_el_stock_no_cambia(http, db_auth, admin):
    rid = await sembrar_repuesto(db_auth, stock=3)
    r = await http.patch(f"/repuestos/{rid}", json={"stock": 999}, headers=admin)
    assert r.status_code == 422
    assert (await fila_de(db_auth, rid))["stock"] == 3


@pytest.mark.parametrize("cuerpo", [{"codigo": "X"}, {"id": 9}, {"precio": None}, {"descripcion": None}, {"precio": 0}, {"precio": 10.005}, {"descripcion": "  "}])
async def test_patch_invalido_es_422_sin_cambios(http, db_auth, admin, cuerpo):
    rid = await sembrar_repuesto(db_auth, stock=3)
    antes = await fila_de(db_auth, rid)
    assert (await http.patch(f"/repuestos/{rid}", json=cuerpo, headers=admin)).status_code == 422
    assert await fila_de(db_auth, rid) == antes
    assert await historial_de(db_auth, rid) == []


async def test_patch_solo_descripcion_conserva_precio_y_stock_y_no_deja_linea(http, db_auth, admin):
    rid = await sembrar_repuesto(db_auth, precio="8000.00", stock=4)
    r = await http.patch(f"/repuestos/{rid}", json={"descripcion": " Filtro nuevo "}, headers=admin)
    assert r.status_code == 200
    assert r.json() == {"id": rid, "codigo": "FIL-001", "descripcion": "Filtro nuevo", "precio": "8000.00", "stock": 4}
    fila = await fila_de(db_auth, rid)
    assert (fila["descripcion"], fila["precio"], fila["stock"]) == ("Filtro nuevo", Decimal("8000.00"), 4)
    assert await historial_de(db_auth, rid) == []


async def test_cambio_de_precio_deja_una_linea_con_el_usuario_admin(http, db_auth, admin, admin_id):
    rid = await sembrar_repuesto(db_auth, precio="8000.00")
    r = await http.patch(f"/repuestos/{rid}", json={"precio": 8500}, headers=admin)
    assert r.status_code == 200 and r.json()["precio"] == "8500.00"
    lineas = await historial_de(db_auth, rid)
    assert [(l["precio_anterior"], l["precio_nuevo"], l["usuario_id"]) for l in lineas] == [
        (Decimal("8000.00"), Decimal("8500.00"), admin_id)
    ]
    assert (await fila_de(db_auth, rid))["precio"] == Decimal("8500.00")


async def test_dos_cambios_sucesivos_dejan_dos_lineas_encadenadas(http, db_auth, admin):
    rid = await sembrar_repuesto(db_auth, precio="8000.00")
    await http.patch(f"/repuestos/{rid}", json={"precio": 8500}, headers=admin)
    await http.patch(f"/repuestos/{rid}", json={"precio": "9000"}, headers=admin)
    lineas = await historial_de(db_auth, rid)
    assert [(l["precio_anterior"], l["precio_nuevo"]) for l in lineas] == [
        (Decimal("8000.00"), Decimal("8500.00")),
        (Decimal("8500.00"), Decimal("9000.00")),
    ]


async def test_patch_posterior_solo_de_descripcion_no_agrega_linea(http, db_auth, admin):
    rid = await sembrar_repuesto(db_auth, precio="8000.00")
    await http.patch(f"/repuestos/{rid}", json={"precio": 8500}, headers=admin)
    await http.patch(f"/repuestos/{rid}", json={"descripcion": "otra"}, headers=admin)
    assert len(await historial_de(db_auth, rid)) == 1


@pytest.mark.parametrize("mismo", [8500, "8500.0", 8500.00, "8500", "8500.00"])
async def test_mismo_precio_con_otra_escritura_aplica_lo_demas_sin_linea(http, db_auth, admin, mismo):
    rid = await sembrar_repuesto(db_auth, precio="8500.00")
    r = await http.patch(f"/repuestos/{rid}", json={"precio": mismo, "descripcion": "x"}, headers=admin)
    assert r.status_code == 200
    assert (r.json()["descripcion"], r.json()["precio"]) == ("x", "8500.00")
    assert await historial_de(db_auth, rid) == []


async def test_patch_vacio_es_200_sin_cambios(http, db_auth, admin):
    rid = await sembrar_repuesto(db_auth, precio="8000.00", stock=2)
    r = await http.patch(f"/repuestos/{rid}", json={}, headers=admin)
    assert r.status_code == 200
    assert r.json()["precio"] == "8000.00" and r.json()["stock"] == 2
    assert await historial_de(db_auth, rid) == []


async def test_patch_de_dado_de_baja_o_inexistente_es_404(http, db_auth, admin):
    baja = await sembrar_repuesto(db_auth, borrado=True)
    assert (await http.patch(f"/repuestos/{baja}", json={"precio": 5}, headers=admin)).status_code == 404
    assert (await http.patch("/repuestos/999999", json={"precio": 5}, headers=admin)).status_code == 404
    assert await historial_de(db_auth, baja) == []


# --- 7.3 Atomicidad y encadenado ---------------------------------------------------------------


async def test_falla_al_registrar_la_linea_deja_el_precio_intacto(http, db_auth, admin, monkeypatch):
    rid = await sembrar_repuesto(db_auth, precio="8000.00")

    async def falla(self, entidad):
        raise RuntimeError("falla simulada del historial")

    monkeypatch.setattr(HistorialPrecioRepository, "add", falla)
    with pytest.raises(RuntimeError):
        await http.patch(f"/repuestos/{rid}", json={"precio": 8500}, headers=admin)
    assert (await fila_de(db_auth, rid))["precio"] == Decimal("8000.00")
    assert await historial_de(db_auth, rid) == []


async def test_falla_al_actualizar_el_precio_revierte_tambien_la_linea(http, db_auth, admin, monkeypatch):
    rid = await sembrar_repuesto(db_auth, precio="8000.00")

    async def falla(self, entidad, cambios):
        raise RuntimeError("falla simulada de la actualizacion")

    monkeypatch.setattr(RepuestoRepository, "update", falla)
    with pytest.raises(RuntimeError):
        await http.patch(f"/repuestos/{rid}", json={"precio": 8500}, headers=admin)
    assert (await fila_de(db_auth, rid))["precio"] == Decimal("8000.00")
    assert await historial_de(db_auth, rid) == []


@pytest.mark.parametrize("repeticion", range(3))
async def test_dos_cambios_de_precio_concurrentes_quedan_encadenados(
    fabrica_http, db_auth, admin, repeticion
):
    rid = await sembrar_repuesto(db_auth, precio="8000.00")
    async with fabrica_http("203.0.113.10") as a, fabrica_http("203.0.113.11") as b:
        ra, rb = await asyncio.gather(
            a.patch(f"/repuestos/{rid}", json={"precio": 8500}, headers=admin),
            b.patch(f"/repuestos/{rid}", json={"precio": 9000}, headers=admin),
        )
    assert (ra.status_code, rb.status_code) == (200, 200)
    lineas = await historial_de(db_auth, rid)
    assert len(lineas) == 2
    assert lineas[0]["precio_anterior"] == Decimal("8000.00")
    assert lineas[1]["precio_anterior"] == lineas[0]["precio_nuevo"]
    assert {l["precio_nuevo"] for l in lineas} == {Decimal("8500.00"), Decimal("9000.00")}
    assert (await fila_de(db_auth, rid))["precio"] == lineas[1]["precio_nuevo"]


# --- 7.6 Solo agregado sobre filas creadas por la API -----------------------------------------------


async def test_la_linea_de_historial_creada_por_la_api_no_se_puede_borrar(http, db_auth, admin):
    rid = await sembrar_repuesto(db_auth, precio="8000.00")
    await http.patch(f"/repuestos/{rid}", json={"precio": 8500}, headers=admin)
    linea = (await historial_de(db_auth, rid))[0]
    with pytest.raises(DBAPIError):
        await db_auth.ejecutar("DELETE FROM historial_precio_repuesto WHERE id = :i", i=linea["id"])
    with pytest.raises(DBAPIError):
        await db_auth.ejecutar(
            "UPDATE historial_precio_repuesto SET precio_nuevo = 1 WHERE id = :i", i=linea["id"]
        )
    assert await historial_de(db_auth, rid) == [linea]
