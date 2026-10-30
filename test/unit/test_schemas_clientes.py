"""Contratos de clientes y vehiculos (C-07, D3/D5): sin base de datos."""
import pytest
from pydantic import ValidationError

import app.modules.modelos  # noqa: F401  (mapeos completos)
from app.modules.clientes.models import Cliente, Vehiculo
from app.modules.clientes.schemas import (
    ClienteDetalleRespuesta,
    ClienteEntrada,
    ClienteRespuesta,
    VehiculoEntrada,
    VehiculoRespuesta,
    VehiculoResumen,
)

pytestmark = pytest.mark.unit


def cliente(**cambios):
    datos = {"nombre": "Ana Perez", "documento": "30111222", "telefono": "555-1234"}
    return {**datos, **cambios}


def vehiculo_json(**cambios) -> str:
    import json

    datos = {"patente": "AB123CD", "marca": "Fiat", "modelo": "Uno", "anio": 2020}
    return json.dumps({**datos, **cambios})


# --- ClienteEntrada (2.1) ---------------------------------------------------


def test_cliente_rechaza_campo_extra():
    with pytest.raises(ValidationError):
        ClienteEntrada(**cliente(usuario_id=1))


def test_cliente_rechaza_id_extra():
    with pytest.raises(ValidationError):
        ClienteEntrada(**cliente(id=5))


@pytest.mark.parametrize("campo", ["nombre", "documento", "telefono"])
def test_cliente_rechaza_texto_solo_espacios(campo):
    with pytest.raises(ValidationError):
        ClienteEntrada(**cliente(**{campo: "   "}))


def test_cliente_recorta_espacios_de_los_extremos():
    assert ClienteEntrada(**cliente(documento="  30111222 ")).documento == "30111222"


def test_cliente_no_quita_puntos_del_documento():
    assert ClienteEntrada(**cliente(documento=" 30.111.222 ")).documento == "30.111.222"


@pytest.mark.parametrize(
    ("campo", "maximo"), [("nombre", 120), ("documento", 20), ("telefono", 30)]
)
def test_cliente_longitud_maxima(campo, maximo):
    assert getattr(ClienteEntrada(**cliente(**{campo: "x" * maximo})), campo) == "x" * maximo
    with pytest.raises(ValidationError):
        ClienteEntrada(**cliente(**{campo: "x" * (maximo + 1)}))


def test_cliente_nombre_de_121_caracteres_falla():
    with pytest.raises(ValidationError):
        ClienteEntrada(**cliente(nombre="n" * 121))


# --- VehiculoEntrada (2.3) --------------------------------------------------


@pytest.mark.parametrize("anio", [1949, 2101])
def test_anio_fuera_de_rango_falla(anio):
    with pytest.raises(ValidationError):
        VehiculoEntrada.model_validate_json(vehiculo_json(anio=anio))


@pytest.mark.parametrize("anio", [1950, 2100])
def test_anio_en_el_borde_es_valido(anio):
    assert VehiculoEntrada.model_validate_json(vehiculo_json(anio=anio)).anio == anio


@pytest.mark.parametrize("crudo", ['"2020"', "2020.5", "true", "null"])
def test_anio_de_otro_tipo_falla(crudo):
    cuerpo = '{"patente":"AB123CD","marca":"Fiat","modelo":"Uno","anio":' + crudo + "}"
    with pytest.raises(ValidationError):
        VehiculoEntrada.model_validate_json(cuerpo)


def test_vehiculo_rechaza_campo_extra():
    with pytest.raises(ValidationError):
        VehiculoEntrada.model_validate_json(vehiculo_json(cliente_id=1))


def test_vehiculo_rechaza_borrado_en_extra():
    with pytest.raises(ValidationError):
        VehiculoEntrada.model_validate_json(vehiculo_json(borrado_en="2020-01-01T00:00:00Z"))


@pytest.mark.parametrize("campo", ["marca", "modelo"])
def test_marca_y_modelo_vacios_fallan(campo):
    with pytest.raises(ValidationError):
        VehiculoEntrada.model_validate_json(vehiculo_json(**{campo: "  "}))
    with pytest.raises(ValidationError):
        VehiculoEntrada.model_validate_json(vehiculo_json(**{campo: ""}))


@pytest.mark.parametrize("campo", ["marca", "modelo"])
def test_marca_y_modelo_longitud_maxima(campo):
    assert getattr(VehiculoEntrada.model_validate_json(vehiculo_json(**{campo: "m" * 60})), campo)
    with pytest.raises(ValidationError):
        VehiculoEntrada.model_validate_json(vehiculo_json(**{campo: "m" * 61}))


# --- Patente (2.4) -----------------------------------------------------------


@pytest.mark.parametrize(
    ("crudo", "esperada"),
    [
        (" ab-123 cd ", "AB123CD"),
        ("aa000bb", "AA000BB"),
        ("A-B 1-2 3", "AB123"),
        ("a" * 10, "A" * 10),
    ],
)
def test_patente_se_normaliza(crudo, esperada):
    assert VehiculoEntrada.model_validate_json(vehiculo_json(patente=crudo)).patente == esperada


@pytest.mark.parametrize("crudo", ["AB*123", "  - ", "", "a" * 11, "AB_123", "ÁB123"])
def test_patente_invalida_falla(crudo):
    with pytest.raises(ValidationError):
        VehiculoEntrada.model_validate_json(vehiculo_json(patente=crudo))


@pytest.mark.parametrize("crudo", [123, None, 1.5, ["AB123"]])
def test_patente_que_no_es_texto_falla_con_validation_error(crudo):
    with pytest.raises(ValidationError):
        VehiculoEntrada(patente=crudo, marca="Fiat", modelo="Uno", anio=2020)


# --- Respuestas (2.5) ---------------------------------------------------------


def test_cliente_respuesta_desde_entidad_sin_sesion():
    entidad = Cliente(id=3, usuario_id=None, nombre="Ana", documento="1", telefono="2")
    r = ClienteRespuesta.model_validate(entidad, from_attributes=True)
    assert r.model_dump() == {
        "id": 3, "nombre": "Ana", "documento": "1", "telefono": "2", "usuario_id": None,
    }


def test_vehiculo_respuesta_no_expone_borrado_en():
    entidad = Vehiculo(id=7, cliente_id=3, patente="AB1", marca="F", modelo="U", anio=2000)
    r = VehiculoRespuesta.model_validate(entidad, from_attributes=True)
    assert r.model_dump() == {
        "id": 7, "cliente_id": 3, "patente": "AB1", "marca": "F", "modelo": "U", "anio": 2000,
    }
    assert "borrado_en" not in VehiculoRespuesta.model_fields


def test_resumen_no_tiene_cliente_id_ni_borrado_en():
    assert set(VehiculoResumen.model_fields) == {"id", "patente", "marca", "modelo", "anio"}


def test_detalle_incluye_vehiculos_resumidos():
    detalle = ClienteDetalleRespuesta(
        id=1, nombre="A", documento="1", telefono="2", usuario_id=None,
        vehiculos=[VehiculoResumen(id=2, patente="X1", marca="F", modelo="U", anio=2001)],
    )
    assert detalle.model_dump()["vehiculos"][0]["patente"] == "X1"
    assert "borrado_en" not in ClienteDetalleRespuesta.model_fields
