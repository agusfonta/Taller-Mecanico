"""Contratos de ordenes (C-09, D2/D4/D10): sin base de datos."""
import json
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.modules.ordenes.models import EstadoOrdenCodigo
from app.modules.ordenes.schemas import (
    EstadoOrdenRespuesta,
    HistorialRespuesta,
    ItemAlta,
    ItemRespuesta,
    OrdenAlta,
    OrdenDetalle,
    OrdenResumen,
)

pytestmark = pytest.mark.unit

MAX_BIGINT = 2**63 - 1


def alta(**cambios):
    datos = {
        "vehiculo_id": 1,
        "falla": "Ruido en el motor",
        "items": [{"repuesto_id": 10, "cantidad": 2}],
    }
    return {**datos, **cambios}


# --- Enum de estados (2.1) --------------------------------------------------------


def test_estado_orden_codigo_tiene_exactamente_los_cuatro_estados():
    assert [e.value for e in EstadoOrdenCodigo] == [
        "PENDIENTE",
        "EN_REPARACION",
        "TERMINADA",
        "CANCELADA",
    ]


def test_estado_orden_codigo_es_cadena_comparable_con_el_catalogo():
    assert EstadoOrdenCodigo.PENDIENTE == "PENDIENTE"
    assert EstadoOrdenCodigo("CANCELADA") is EstadoOrdenCodigo.CANCELADA
    with pytest.raises(ValueError):
        EstadoOrdenCodigo("ARCHIVADA")


# --- OrdenAlta / ItemAlta (2.2) -----------------------------------------------------


def test_alta_valida_con_un_item():
    orden = OrdenAlta.model_validate(alta())
    assert orden.vehiculo_id == 1
    assert orden.items == [ItemAlta(repuesto_id=10, cantidad=2)]


def test_alta_valida_con_dos_items():
    orden = OrdenAlta.model_validate(
        alta(items=[{"repuesto_id": 10, "cantidad": 2}, {"repuesto_id": 11, "cantidad": 1}])
    )
    assert [i.repuesto_id for i in orden.items] == [10, 11]


def test_falla_se_recorta():
    assert OrdenAlta.model_validate(alta(falla="  frenos  ")).falla == "frenos"


@pytest.mark.parametrize("falla", ["", "   ", "x" * 501, 5, None])
def test_falla_invalida_se_rechaza(falla):
    with pytest.raises(ValidationError):
        OrdenAlta.model_validate(alta(falla=falla))


def test_falla_de_500_caracteres_se_admite():
    assert len(OrdenAlta.model_validate(alta(falla="x" * 500)).falla) == 500


def test_items_vacio_se_rechaza():
    with pytest.raises(ValidationError):
        OrdenAlta.model_validate(alta(items=[]))


def test_cincuenta_items_se_admiten_y_cincuenta_y_uno_no():
    def lista(n):
        return [{"repuesto_id": i + 1, "cantidad": 1} for i in range(n)]

    assert len(OrdenAlta.model_validate(alta(items=lista(50))).items) == 50
    with pytest.raises(ValidationError):
        OrdenAlta.model_validate(alta(items=lista(51)))


def test_repuesto_repetido_se_rechaza():
    with pytest.raises(ValidationError, match="repet"):
        OrdenAlta.model_validate(
            alta(items=[{"repuesto_id": 10, "cantidad": 1}, {"repuesto_id": 10, "cantidad": 3}])
        )


@pytest.mark.parametrize("cantidad", [0, -1, 1001, "2", 1.5, True, None])
def test_cantidad_invalida_se_rechaza(cantidad):
    with pytest.raises(ValidationError):
        ItemAlta.model_validate({"repuesto_id": 1, "cantidad": cantidad})


@pytest.mark.parametrize("cantidad", [1, 1000])
def test_cantidad_en_los_limites_se_admite(cantidad):
    assert ItemAlta.model_validate({"repuesto_id": 1, "cantidad": cantidad}).cantidad == cantidad


@pytest.mark.parametrize("vehiculo_id", ["1", 0, -3, 2**63, 1.0, True, None])
def test_vehiculo_id_invalido_se_rechaza(vehiculo_id):
    with pytest.raises(ValidationError):
        OrdenAlta.model_validate(alta(vehiculo_id=vehiculo_id))


def test_ids_en_el_maximo_de_bigint_se_admiten():
    orden = OrdenAlta.model_validate(
        alta(vehiculo_id=MAX_BIGINT, items=[{"repuesto_id": MAX_BIGINT, "cantidad": 1}])
    )
    assert orden.vehiculo_id == MAX_BIGINT


@pytest.mark.parametrize("repuesto_id", ["1", 0, 2**63, False])
def test_repuesto_id_invalido_se_rechaza(repuesto_id):
    with pytest.raises(ValidationError):
        ItemAlta.model_validate({"repuesto_id": repuesto_id, "cantidad": 1})


@pytest.mark.parametrize(
    "extra", ["precio_unitario", "total", "estado", "creada_en", "mecanico_id", "id"]
)
def test_campo_extra_en_la_orden_se_rechaza(extra):
    with pytest.raises(ValidationError, match="extra"):
        OrdenAlta.model_validate(alta(**{extra: 1}))


@pytest.mark.parametrize(
    "extra", ["precio_unitario", "total", "estado", "creada_en", "mecanico_id", "id"]
)
def test_campo_extra_en_el_item_se_rechaza(extra):
    with pytest.raises(ValidationError, match="extra"):
        OrdenAlta.model_validate(alta(items=[{"repuesto_id": 1, "cantidad": 1, extra: 5}]))


@pytest.mark.parametrize("faltante", ["vehiculo_id", "falla", "items"])
def test_campo_obligatorio_faltante_se_rechaza(faltante):
    datos = alta()
    del datos[faltante]
    with pytest.raises(ValidationError):
        OrdenAlta.model_validate(datos)


# --- Respuestas (2.3) -------------------------------------------------------------


def item(cantidad, precio, **repuesto):
    return SimpleNamespace(
        id=1,
        repuesto_id=10,
        cantidad=cantidad,
        precio_unitario=Decimal(precio),
        repuesto=SimpleNamespace(
            **{"codigo": "FIL-001", "descripcion": "Filtro de aceite", **repuesto}
        ),
    )


@pytest.mark.parametrize(
    ("cantidad", "precio", "subtotal"),
    [(2, "8500.00", "17000.00"), (3, "0.10", "0.30"), (1, "12.50", "12.50")],
)
def test_subtotal_es_cantidad_por_precio_exacto(cantidad, precio, subtotal):
    r = ItemRespuesta.model_validate(item(cantidad, precio))
    assert r.subtotal == Decimal(subtotal)
    assert json.loads(r.model_dump_json())["subtotal"] == subtotal


def test_item_respuesta_toma_codigo_y_descripcion_del_repuesto_y_serializa_dinero_como_cadena():
    datos = json.loads(ItemRespuesta.model_validate(item(2, "8500.5")).model_dump_json())
    assert datos == {
        "id": 1,
        "repuesto_id": 10,
        "codigo": "FIL-001",
        "descripcion": "Filtro de aceite",
        "cantidad": 2,
        "precio_unitario": "8500.50",
        "subtotal": "17001.00",
    }


def orden_orm(**cambios):
    datos = dict(
        id=7,
        vehiculo_id=3,
        mecanico_id=None,
        estado="PENDIENTE",
        falla="ruido",
        creada_en=datetime(2026, 1, 1, tzinfo=UTC),
        total=Decimal("17001"),
        items=[item(2, "8500.50")],
        historial=[
            SimpleNamespace(
                id=1,
                desde_estado=None,
                hasta_estado="PENDIENTE",
                usuario_id=5,
                cuando=datetime(2026, 1, 1, tzinfo=UTC),
            )
        ],
    )
    return SimpleNamespace(**{**datos, **cambios})


def test_orden_resumen_serializa_el_total_con_dos_decimales_y_sin_items():
    datos = json.loads(OrdenResumen.model_validate(orden_orm()).model_dump_json())
    assert datos["total"] == "17001.00"
    assert datos["mecanico_id"] is None
    assert "items" not in datos and "historial" not in datos


def test_orden_detalle_incluye_items_e_historial():
    datos = json.loads(OrdenDetalle.model_validate(orden_orm()).model_dump_json())
    assert datos["items"][0]["subtotal"] == "17001.00"
    assert datos["historial"] == [
        {
            "id": 1,
            "desde_estado": None,
            "hasta_estado": "PENDIENTE",
            "usuario_id": 5,
            "cuando": "2026-01-01T00:00:00Z",
        }
    ]
    assert HistorialRespuesta.model_validate(orden_orm().historial[0]).desde_estado is None


def test_orden_detalle_sin_items_ni_historial_son_listas_vacias():
    r = OrdenDetalle.model_validate(orden_orm(items=[], historial=[]))
    assert r.items == [] and r.historial == []


def test_estado_orden_respuesta_desde_atributos():
    fila = SimpleNamespace(codigo="TERMINADA", descripcion="Terminada", posicion=3, es_final=True)
    assert EstadoOrdenRespuesta.model_validate(fila).model_dump() == {
        "codigo": "TERMINADA",
        "descripcion": "Terminada",
        "posicion": 3,
        "es_final": True,
    }
