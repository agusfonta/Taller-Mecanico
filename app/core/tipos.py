"""Tipos compartidos de entrada (C-12, D12).

``IdRuta``: id numerico de un parametro de ruta, acotado al rango de ``BIGINT``. Un entero fuera de ese
rango llegaria a asyncpg como argumento invalido (``DataError``) y terminaria en 500; acotado, FastAPI
responde 422 antes de consultar. Los extremos ``0`` y negativos siguen dentro del rango y dan 404 como antes.
"""
from typing import Annotated

from fastapi import Path

__all__ = ["IdRuta", "MAX_ID", "MIN_ID"]

MIN_ID = -(2**63)
MAX_ID = 2**63 - 1

IdRuta = Annotated[int, Path(ge=MIN_ID, le=MAX_ID)]
