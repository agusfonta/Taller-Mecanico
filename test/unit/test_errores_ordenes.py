"""Errores de dominio de las transiciones y su traduccion HTTP (C-10, D8, tarea 2.3)."""
import pytest
from fastapi import HTTPException

from app.modules.ordenes import service
from app.modules.ordenes.router import _http_desde

pytestmark = pytest.mark.unit

ERRORES_403 = [service.SinPermisoSobreOrdenError]
ERRORES_409 = [
    service.TransicionInvalidaError,
    service.OrdenAsignadaAOtroError,
    service.StockInsuficienteOrdenError,
]


def test_sin_permiso_sobre_orden_es_orden_ajena():
    assert issubclass(service.SinPermisoSobreOrdenError, service.OrdenAjenaError)


@pytest.mark.parametrize("clase", ERRORES_409)
def test_los_errores_de_estado_y_stock_son_conflicto(clase):
    assert issubclass(clase, service.ConflictoError)


@pytest.mark.parametrize("clase", ERRORES_403 + ERRORES_409)
def test_cada_error_tiene_mensaje_propio_no_vacio(clase):
    assert clase.mensaje.strip()
    assert clase.mensaje not in {service.OrdenAjenaError.mensaje, service.ConflictoError.mensaje}


def test_los_mensajes_nuevos_son_distintos_entre_si():
    mensajes = [c.mensaje for c in ERRORES_403 + ERRORES_409]
    assert len(set(mensajes)) == len(mensajes)


@pytest.mark.parametrize(
    ("clase", "codigo"),
    [(service.SinPermisoSobreOrdenError, 403)]
    + [(c, 409) for c in ERRORES_409],
)
def test_http_desde_traduce_cada_error_sin_cambios(clase, codigo):
    error = clase()
    with pytest.raises(HTTPException) as info:
        _http_desde(error)
    assert info.value.status_code == codigo
    assert info.value.detail == error.mensaje


def test_transicion_invalida_nombra_estado_y_accion():
    error = service.TransicionInvalidaError("TERMINADA", "cancelar")
    assert "TERMINADA" in error.mensaje and "cancelar" in error.mensaje
    otro = service.TransicionInvalidaError("PENDIENTE", "terminar")
    assert "PENDIENTE" in otro.mensaje and "terminar" in otro.mensaje
    assert error.mensaje != otro.mensaje


def test_stock_insuficiente_nombra_el_codigo_del_repuesto():
    error = service.StockInsuficienteOrdenError("BUJ-001")
    assert "BUJ-001" in error.mensaje
    assert "FIL-002" in service.StockInsuficienteOrdenError("FIL-002").mensaje
