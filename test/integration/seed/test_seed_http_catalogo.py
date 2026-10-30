"""Catalogos y consultas sobre el estado del seed, por HTTP (C-11, 4.3): puntos de partida de C-16/17/18."""
from decimal import Decimal

import pytest

pytestmark = pytest.mark.integration


async def test_estados_orden_los_cuatro_por_posicion_c17(seed_cargado, sesion_de):
    admin = await sesion_de("admin@example.com")
    respuesta = await admin.get("/estados-orden")
    assert respuesta.status_code == 200
    assert [(e["codigo"], e["posicion"], e["es_final"]) for e in respuesta.json()] == [
        ("PENDIENTE", 1, False),
        ("EN_REPARACION", 2, False),
        ("TERMINADA", 3, True),
        ("CANCELADA", 4, True),
    ]


async def test_busqueda_freno_con_size_1_da_total_1_y_una_pagina_c16(seed_cargado, sesion_de):
    admin = await sesion_de("admin@example.com")
    cuerpo = (await admin.get("/repuestos", params={"q": "freno", "size": 1})).json()
    assert (cuerpo["total"], cuerpo["pages"], cuerpo["size"]) == (1, 1, 1)
    assert [i["codigo"] for i in cuerpo["items"]] == ["FRE-010"]


async def test_busqueda_sin_filtro_lista_los_cuatro_repuestos(seed_cargado, sesion_de):
    admin = await sesion_de("admin@example.com")
    cuerpo = (await admin.get("/repuestos")).json()
    assert cuerpo["total"] == 4
    assert [i["codigo"] for i in cuerpo["items"]] == ["FIL-001", "FRE-010", "BUJ-001", "ACE-530"]


async def test_historial_de_precios_del_filtro_tiene_una_linea_c18(seed_cargado, sesion_de):
    admin = await sesion_de("admin@example.com")
    cuerpo = (await admin.get("/repuestos/1/precios")).json()
    assert cuerpo["total"] == 1
    linea = cuerpo["items"][0]
    assert (Decimal(str(linea["precio_anterior"])), Decimal(str(linea["precio_nuevo"]))) == (
        Decimal("8000.00"),
        Decimal("8500.00"),
    )


async def test_historial_de_precios_de_otro_repuesto_esta_vacio(seed_cargado, sesion_de):
    admin = await sesion_de("admin@example.com")
    assert (await admin.get("/repuestos/3/precios")).json()["total"] == 0


async def test_eventos_de_seguridad_muestra_la_unica_linea_del_sistema(seed_cargado, sesion_de):
    admin = await sesion_de("admin@example.com")
    cuerpo = (await admin.get("/eventos")).json()
    assert cuerpo["total"] == 1
    assert [(e["actor"], e["accion"]) for e in cuerpo["items"]] == [("SISTEMA", "Carga de los datos iniciales")]
