"""Sondas de salud: ``/health/live`` y ``/health/ready`` (grupo abierto, sin sesion).

Por que sin servicio ni UoW (D1): no hay regla de negocio ni transaccion; ``ready``
es una sonda de infraestructura de solo lectura (``SELECT 1``) y un UoW agregaria un
COMMIT sin sentido. KB 08 fija ``health/`` con solo ``router.py``.

``live`` no declara dependencias: por construccion no puede tocar la base.
"""
import asyncio
import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

__all__ = [
    "router",
    "EstadoVida",
    "EstadoDisponibilidad",
    "TIEMPO_MAXIMO_READY_SEGUNDOS",
    "get_motor",
    "base_disponible",
    "live",
    "ready",
]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])

# Constante de modulo (D4): se lee en tiempo de llamada para poder bajarla en tests.
TIEMPO_MAXIMO_READY_SEGUNDOS: float = 2.0


class EstadoVida(BaseModel):
    estado: Literal["vivo"]


class EstadoDisponibilidad(BaseModel):
    estado: Literal["listo", "no_listo"]


def get_motor(request: Request) -> AsyncEngine | None:
    """Motor publicado por el lifespan; ``None`` si el lifespan no corrio."""
    return getattr(request.app.state, "engine", None)


async def base_disponible(motor: AsyncEngine | None) -> bool:
    """``SELECT 1`` con tiempo acotado (D2).

    Se captura ``Exception`` y NO ``BaseException``: cualquier fallo al alcanzar la
    base significa "no listo", pero ``CancelledError`` (cliente que corta) debe
    propagarse. El log registra solo el nombre de la clase: ``str(exc)`` de asyncpg
    incluye host, puerto y usuario.
    """
    if motor is None:
        return False
    try:
        async with asyncio.timeout(TIEMPO_MAXIMO_READY_SEGUNDOS):
            async with motor.connect() as conexion:
                await conexion.execute(text("SELECT 1"))
    except Exception as exc:
        logger.warning("Health ready: base no disponible (%s)", type(exc).__name__)
        return False
    return True


@router.get("/live", response_model=EstadoVida)
async def live() -> EstadoVida:
    return EstadoVida(estado="vivo")


@router.get(
    "/ready",
    response_model=EstadoDisponibilidad,
    responses={503: {"model": EstadoDisponibilidad}},
)
async def ready(
    motor: Annotated[AsyncEngine | None, Depends(get_motor)],
) -> EstadoDisponibilidad | JSONResponse:
    if await base_disponible(motor):
        return EstadoDisponibilidad(estado="listo")
    return JSONResponse(
        status_code=503,
        content=EstadoDisponibilidad(estado="no_listo").model_dump(),
    )
