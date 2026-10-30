"""``restriccion_violada`` lee el nombre de la restriccion sin depender del texto del error (C-05)."""
import pytest
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.unit


class _Origen(Exception):
    def __init__(self, nombre=None):
        super().__init__("texto con tablas y valores que NO debe usarse")
        if nombre is not None:
            self.constraint_name = nombre


def _error(origen):
    return IntegrityError("INSERT ...", {}, origen)


def test_lee_el_nombre_del_origen_directo():
    from app.core.errores import restriccion_violada

    assert restriccion_violada(_error(_Origen("uq_usuario_email"))) == "uq_usuario_email"


def test_lee_el_nombre_de_la_causa_del_adaptador():
    from app.core.errores import restriccion_violada

    adaptador = _Origen()
    adaptador.__cause__ = _Origen("uq_cliente_documento")
    assert restriccion_violada(_error(adaptador)) == "uq_cliente_documento"


@pytest.mark.parametrize("origen", [None, _Origen(), _Origen("")])
def test_sin_nombre_devuelve_none(origen):
    from app.core.errores import restriccion_violada

    assert restriccion_violada(_error(origen)) is None
