"""Paginacion: calculo de paginas, verificacion de rango y envoltorio (D6)."""
import pytest

from app.core.paginacion import (
    PAGINA_TAMANIO_DEFECTO,
    PAGINA_TAMANIO_MAXIMO,
    Pagina,
    PaginaFueraDeRangoError,
    ParametrosPaginacion,
    calcular_paginas,
    verificar_pagina,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("total", "size", "esperado"),
    [(45, 20, 3), (40, 20, 2), (0, 20, 1), (1, 1, 1), (101, 100, 2)],
)
def test_calcular_paginas_techo_con_minimo_uno(total, size, esperado):
    assert calcular_paginas(total, size) == esperado


def test_constantes_de_paginacion():
    assert PAGINA_TAMANIO_DEFECTO == 20
    assert PAGINA_TAMANIO_MAXIMO == 100


@pytest.mark.parametrize(
    ("page", "total", "size", "pages"),
    [(1, 0, 20, 1), (3, 45, 20, 3), (2, 40, 20, 2)],
)
def test_verificar_pagina_en_rango_devuelve_pages(page, total, size, pages):
    assert verificar_pagina(ParametrosPaginacion(page=page, size=size), total) == pages


@pytest.mark.parametrize(
    ("page", "total", "size"),
    [(2, 0, 20), (2, 1, 1), (4, 45, 20)],
)
def test_verificar_pagina_fuera_de_rango_lanza(page, total, size):
    with pytest.raises(PaginaFueraDeRangoError):
        verificar_pagina(ParametrosPaginacion(page=page, size=size), total)


@pytest.mark.parametrize(("page", "size", "offset"), [(3, 20, 40), (1, 20, 0), (2, 5, 5)])
def test_offset(page, size, offset):
    assert ParametrosPaginacion(page=page, size=size).offset == offset


def test_pagina_crear_serializa_exactamente_los_cinco_campos():
    params = ParametrosPaginacion(page=3, size=20)
    pagina = Pagina[str].crear(["a", "b"], 42, params)
    datos = pagina.model_dump()
    assert set(datos) == {"items", "total", "page", "size", "pages"}
    assert datos == {"items": ["a", "b"], "total": 42, "page": 3, "size": 20, "pages": 3}


@pytest.mark.parametrize("total", [0, 20, 21, 100])
def test_pagina_pages_coincide_con_calcular_paginas(total):
    params = ParametrosPaginacion(page=1, size=20)
    assert Pagina[int].crear([], total, params).pages == calcular_paginas(total, 20)
