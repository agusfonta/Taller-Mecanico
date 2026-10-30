"""Tabla pura de transiciones de ordenes (C-10, D1, spec transiciones-orden)."""
import inspect

import pytest

from app.modules.ordenes import transiciones
from app.modules.ordenes.models import EstadoOrdenCodigo as E
from app.modules.ordenes.transiciones import TRANSICIONES, Accion, destino
from app.modules.ordenes.service import TransicionInvalidaError
from test.integration.ayudantes_clientes import CATALOGO

pytestmark = pytest.mark.unit

VALIDAS = [
    (Accion.INICIAR, E.PENDIENTE, E.EN_REPARACION),
    (Accion.TERMINAR, E.EN_REPARACION, E.TERMINADA),
    (Accion.CANCELAR, E.PENDIENTE, E.CANCELADA),
]
INVALIDAS = [(a, e) for a in Accion for e in E if (a, e) not in {(v[0], v[1]) for v in VALIDAS}]


@pytest.mark.parametrize(("accion", "actual", "esperado"), VALIDAS)
def test_las_tres_transiciones_validas_llevan_al_estado_esperado(accion, actual, esperado):
    assert destino(accion, actual.value) == esperado


@pytest.mark.parametrize(("accion", "actual"), INVALIDAS)
def test_las_nueve_combinaciones_restantes_son_transicion_invalida(accion, actual):
    with pytest.raises(TransicionInvalidaError):
        destino(accion, actual.value)


def test_la_matriz_completa_son_doce_casos_tres_validas_y_nueve_invalidas():
    assert len(list(Accion)) * len(list(E)) == 12
    assert len(VALIDAS) == 3 and len(INVALIDAS) == 9


@pytest.mark.parametrize("accion", list(Accion))
def test_un_estado_ajeno_al_enum_es_transicion_invalida(accion):
    with pytest.raises(TransicionInvalidaError):
        destino(accion, "ARCHIVADA")


def test_destino_es_una_funcion_pura_y_sincrona():
    assert not inspect.iscoroutinefunction(destino)
    assert destino(Accion.INICIAR, "PENDIENTE") == destino(Accion.INICIAR, "PENDIENTE")


def test_destino_acepta_el_enum_o_su_texto():
    assert destino(Accion.TERMINAR, E.EN_REPARACION) == destino(Accion.TERMINAR, "EN_REPARACION")


def test_el_mensaje_del_rechazo_nombra_estado_y_accion():
    with pytest.raises(TransicionInvalidaError) as info:
        destino(Accion.CANCELAR, "TERMINADA")
    assert "TERMINADA" in info.value.mensaje and "cancelar" in info.value.mensaje.lower()
    with pytest.raises(TransicionInvalidaError) as info:
        destino(Accion.INICIAR, "EN_REPARACION")
    assert "EN_REPARACION" in info.value.mensaje and "iniciar" in info.value.mensaje.lower()


def test_el_modulo_no_hace_entrada_salida():
    fuente = inspect.getsource(transiciones)
    assert "async " not in fuente and "await " not in fuente


# --- D1-a: coherencia con el catalogo canonico (RN-16) ---------------------------------


def test_los_estados_sin_salida_son_exactamente_los_finales_del_catalogo():
    finales_catalogo = {codigo for codigo, _, es_final in CATALOGO if es_final}
    con_salida = {estado for (_, estado) in TRANSICIONES}
    sin_salida = {e.value for e in E} - {e.value for e in con_salida}
    assert sin_salida == finales_catalogo == {"TERMINADA", "CANCELADA"}


def test_todo_estado_del_catalogo_esta_en_el_enum_y_viceversa():
    assert {codigo for codigo, _, _ in CATALOGO} == {e.value for e in E}
