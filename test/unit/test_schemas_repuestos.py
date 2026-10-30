"""Contratos de repuestos (C-08, D2/D3): sin base de datos."""
import json
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import TypeAdapter, ValidationError

from app.modules.repuestos.schemas import (
    MovimientoRespuesta,
    Precio,
    PrecioHistorialRespuesta,
    Reposicion,
    RepuestoAlta,
    RepuestoEdicion,
    RepuestoRespuesta,
)

pytestmark = pytest.mark.unit

ADAPTADOR = TypeAdapter(Precio)


def alta(**cambios):
    datos = {"codigo": "FIL-001", "descripcion": "Filtro", "precio": 8000}
    return {**datos, **cambios}


# --- Precio (2.1) -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        (json.loads("8500.5"), Decimal("8500.50")),
        ("1200", Decimal("1200.00")),
        (1, Decimal("1.00")),
        ("99999999.99", Decimal("99999999.99")),
        ("0.01", Decimal("0.01")),
    ],
)
def test_precio_valido_queda_con_dos_decimales(entrada, esperado):
    resultado = ADAPTADOR.validate_python(entrada)
    assert resultado == esperado
    assert resultado.as_tuple().exponent == -2


def test_precio_desde_json_numerico_no_pasa_por_float_binario():
    resultado = ADAPTADOR.validate_json("8500.5")
    assert isinstance(resultado, Decimal)
    assert resultado == Decimal("8500.50")


@pytest.mark.parametrize(
    "entrada",
    [10.005, "10.005", 0, "0", -1, "-0.01", 100000000, "100000000", True, False, None, "abc", "NaN", "Infinity", "-Infinity", ""],
)
def test_precio_invalido_se_rechaza(entrada):
    with pytest.raises(ValidationError):
        ADAPTADOR.validate_python(entrada)


@pytest.mark.parametrize("texto", ["true", "null", "NaN", "10.005", "0", "-1", "100000000"])
def test_precio_invalido_en_json_se_rechaza(texto):
    with pytest.raises(ValidationError):
        ADAPTADOR.validate_json(texto)


def test_respuesta_serializa_el_precio_como_cadena_con_dos_decimales():
    r = RepuestoRespuesta(id=1, codigo="A", descripcion="d", precio=Decimal("8500.5"), stock=3)
    datos = json.loads(r.model_dump_json())
    assert datos["precio"] == "8500.50"
    assert isinstance(datos["precio"], str)
    assert json.loads(RepuestoRespuesta(id=1, codigo="A", descripcion="d", precio=Decimal("1E+3"), stock=0).model_dump_json())["precio"] == "1000.00"


def test_respuesta_no_expone_borrado_en():
    assert "borrado_en" not in RepuestoRespuesta.model_fields


# --- RepuestoAlta (2.3) -----------------------------------------------------------


def test_alta_normaliza_codigo_a_mayusculas_sin_espacios():
    assert RepuestoAlta(**alta(codigo=" fil-001 ")).codigo == "FIL-001"
    assert RepuestoAlta(**alta(codigo="  abc ")).codigo == "ABC"


def test_alta_recorta_descripcion_y_precio_decimal():
    r = RepuestoAlta(**alta(descripcion="  Filtro de aceite "))
    assert r.descripcion == "Filtro de aceite"
    assert r.precio == Decimal("8000.00")


@pytest.mark.parametrize("codigo", ["x" * 51, "", "   "])
def test_alta_rechaza_codigo_fuera_de_rango(codigo):
    with pytest.raises(ValidationError):
        RepuestoAlta(**alta(codigo=codigo))


def test_alta_acepta_codigo_de_50():
    assert len(RepuestoAlta(**alta(codigo="x" * 50)).codigo) == 50


@pytest.mark.parametrize("descripcion", ["   ", "", "d" * 201])
def test_alta_rechaza_descripcion_invalida(descripcion):
    with pytest.raises(ValidationError):
        RepuestoAlta(**alta(descripcion=descripcion))


@pytest.mark.parametrize("campo", ["stock", "id", "borrado_en"])
def test_alta_rechaza_campos_extra(campo):
    with pytest.raises(ValidationError):
        RepuestoAlta(**alta(**{campo: 5}))


def test_alta_stock_inicial_ausente_es_cero():
    assert RepuestoAlta(**alta()).stock_inicial == 0


@pytest.mark.parametrize("valor", [0, 7, 1_000_000])
def test_alta_acepta_stock_inicial_valido(valor):
    assert RepuestoAlta(**alta(stock_inicial=valor)).stock_inicial == valor


@pytest.mark.parametrize("valor", [-1, 1_000_001, "5", True, 1.5, None])
def test_alta_rechaza_stock_inicial_invalido(valor):
    with pytest.raises(ValidationError):
        RepuestoAlta(**alta(stock_inicial=valor))


# --- RepuestoEdicion y Reposicion (2.4) -------------------------------------------


@pytest.mark.parametrize("cuerpo", [{"stock": 1}, {"codigo": "X"}, {"id": 1}])
def test_edicion_rechaza_campos_ajenos(cuerpo):
    with pytest.raises(ValidationError):
        RepuestoEdicion(**cuerpo)


def test_edicion_vacia_es_valida_y_no_trae_cambios():
    assert RepuestoEdicion().model_dump(exclude_unset=True) == {}


def test_edicion_parcial_solo_trae_lo_enviado():
    e = RepuestoEdicion(descripcion=" Nueva ")
    assert e.model_dump(exclude_unset=True) == {"descripcion": "Nueva"}
    p = RepuestoEdicion(precio="8500.0")
    assert p.model_dump(exclude_unset=True) == {"precio": Decimal("8500.00")}


@pytest.mark.parametrize("cuerpo", [{"precio": None}, {"descripcion": None}])
def test_edicion_rechaza_nulo_explicito(cuerpo):
    with pytest.raises(ValidationError):
        RepuestoEdicion(**cuerpo)


@pytest.mark.parametrize("cuerpo", [{"precio": 0}, {"precio": True}, {"descripcion": "  "}])
def test_edicion_aplica_las_reglas_del_alta(cuerpo):
    with pytest.raises(ValidationError):
        RepuestoEdicion(**cuerpo)


@pytest.mark.parametrize("valor", [1, 5, 1_000_000])
def test_reposicion_acepta_cantidades_validas(valor):
    assert Reposicion(cantidad=valor).cantidad == valor


@pytest.mark.parametrize("valor", [0, -3, 1.5, "5", True, 1_000_001, None])
def test_reposicion_rechaza_cantidades_invalidas(valor):
    with pytest.raises(ValidationError):
        Reposicion(cantidad=valor)


def test_reposicion_rechaza_campo_extra_y_cuerpo_sin_cantidad():
    with pytest.raises(ValidationError):
        Reposicion(cantidad=5, motivo="x")
    with pytest.raises(ValidationError):
        Reposicion()


# --- Respuestas desde entidades (2.5) ---------------------------------------------


def test_movimiento_respuesta_desde_entidad():
    cuando = datetime(2026, 1, 2, tzinfo=UTC)
    entidad = SimpleNamespace(id=1, repuesto_id=2, orden_id=None, usuario_id=3, cantidad=10, motivo="Stock inicial", cuando=cuando, borrado_en=None)
    r = MovimientoRespuesta.model_validate(entidad, from_attributes=True)
    datos = json.loads(r.model_dump_json())
    assert datos["cantidad"] == 10 and datos["orden_id"] is None and datos["motivo"] == "Stock inicial"
    assert "borrado_en" not in datos


def test_precio_historial_respuesta_serializa_cadenas():
    entidad = SimpleNamespace(id=1, repuesto_id=2, usuario_id=3, precio_anterior=Decimal("8000.00"), precio_nuevo=Decimal("8500"), cuando=datetime(2026, 1, 2, tzinfo=UTC))
    datos = json.loads(PrecioHistorialRespuesta.model_validate(entidad, from_attributes=True).model_dump_json())
    assert datos["precio_anterior"] == "8000.00"
    assert datos["precio_nuevo"] == "8500.00"
    assert "borrado_en" not in datos
