import secrets
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI

from app.core.config import get_settings
from app.core.database import crear_fabrica_sesiones, crear_motor
from app.core.dependencies import exigir_acceso
from app.core.logs import configurar_logging_app
from app.core.paginacion import PaginaFueraDeRangoError, manejar_pagina_fuera_de_rango
from app.core.security import crear_servicio_contrasenas
import app.modules.modelos  # noqa: F401  (mapeos completos al arrancar; no crea tablas)
from app.modules.clientes.router import router as router_clientes
from app.modules.health.router import router as router_health
from app.modules.ordenes.router import router_ordenes
from app.modules.repuestos.router import router_repuestos
from app.modules.usuarios.router import router_auth, router_eventos, router_usuarios

# Fail-fast: si falta un secreto, la importacion levanta ValidationError (D6 de C-01).
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Crea motor, sesiones y servicio de contraseñas al arrancar; libera el pool al apagar.

    El hash ficticio (RN-09) se calcula UNA vez aqui, con el costo configurado y un valor
    aleatorio que se descarta: calcularlo en el primer login de un correo inexistente
    dejaria ese login con el doble de latencia (un oraculo de existencia de cuentas).
    """
    ajustes = get_settings()
    motor = crear_motor(ajustes)
    app.state.engine = motor
    app.state.session_factory = crear_fabrica_sesiones(motor)
    app.state.contrasenas = crear_servicio_contrasenas(ajustes)
    app.state.hash_ficticio = await app.state.contrasenas.hashear(secrets.token_urlsafe(32))
    try:
        yield
    finally:
        await motor.dispose()


def crear_app(
    abiertos: Sequence[APIRouter] = (),
    protegidos: Sequence[APIRouter] = (),
) -> FastAPI:
    """Arma la app con dos grupos: abierto y protegido (control montado una vez, DD-07)."""
    configurar_logging_app()
    app = FastAPI(title="Taller Mecánico", lifespan=lifespan)
    grupo_abierto = APIRouter()
    grupo_protegido = APIRouter(dependencies=[Depends(exigir_acceso)])
    for router in abiertos:
        grupo_abierto.include_router(router)
    for router in protegidos:
        grupo_protegido.include_router(router)
    app.include_router(grupo_abierto)
    app.include_router(grupo_protegido)
    app.add_exception_handler(PaginaFueraDeRangoError, manejar_pagina_fuera_de_rango)
    return app


app = crear_app(
    abiertos=[router_health, router_auth],
    protegidos=[router_usuarios, router_eventos, router_clientes, router_repuestos, router_ordenes],
)
