"""Paginacion comun de los listados (D6, KB 05 "Reglas de contrato").

Uso previsto en un servicio, todo dentro del mismo ``async with uow``::

    total = await repo.count()
    pages = verificar_pagina(params, total)          # 422 si page > pages
    items = await repo.list(offset=params.offset, limit=params.size)
    return Pagina.crear(items, total, params)
"""
from dataclasses import dataclass
from math import ceil
from typing import Annotated, Self

from fastapi import Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

__all__ = [
    "PAGINA_TAMANIO_DEFECTO",
    "PAGINA_TAMANIO_MAXIMO",
    "PaginaFueraDeRangoError",
    "ParametrosPaginacion",
    "PaginacionDep",
    "Pagina",
    "calcular_paginas",
    "verificar_pagina",
    "parametros_paginacion",
    "manejar_pagina_fuera_de_rango",
]

PAGINA_TAMANIO_DEFECTO = 20
PAGINA_TAMANIO_MAXIMO = 100


class PaginaFueraDeRangoError(Exception):
    """Se pidio una pagina mayor que la ultima (se traduce a 422)."""


@dataclass(frozen=True)
class ParametrosPaginacion:
    page: int = 1
    size: int = PAGINA_TAMANIO_DEFECTO

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size


def calcular_paginas(total: int, size: int) -> int:
    """Techo de ``total / size`` con minimo 1 (cero resultados: una pagina vacia)."""
    return max(1, ceil(total / size))


def verificar_pagina(params: ParametrosPaginacion, total: int) -> int:
    """Devuelve ``pages`` o lanza ``PaginaFueraDeRangoError`` si ``page > pages``.

    Llamar despues de contar y antes de listar.
    """
    pages = calcular_paginas(total, params.size)
    if params.page > pages:
        raise PaginaFueraDeRangoError
    return pages


class Pagina[T](BaseModel):
    items: list[T]
    total: int
    page: int
    size: int
    pages: int

    @classmethod
    def crear(cls, items: list[T], total: int, params: ParametrosPaginacion) -> Self:
        return cls(
            items=items,
            total=total,
            page=params.page,
            size=params.size,
            pages=calcular_paginas(total, params.size),
        )


def parametros_paginacion(
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=PAGINA_TAMANIO_MAXIMO)] = PAGINA_TAMANIO_DEFECTO,
) -> ParametrosPaginacion:
    return ParametrosPaginacion(page=page, size=size)


PaginacionDep = Annotated[ParametrosPaginacion, Depends(parametros_paginacion)]


async def manejar_pagina_fuera_de_rango(
    request: Request, exc: PaginaFueraDeRangoError
) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": "La página solicitada no existe"})
