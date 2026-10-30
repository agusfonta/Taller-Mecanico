"""Salud: /health/live y /health/ready (spec salud, D1..D6)."""
import asyncio
import importlib
import logging
import socket
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

pytestmark = pytest.mark.unit


@pytest.fixture
def main_mod(secretos_validos):
    import main

    return importlib.reload(main)


@pytest.fixture
def router_mod(main_mod):
    return importlib.import_module("app.modules.health.router")


@pytest.fixture
def app_salud(main_mod, router_mod):
    return main_mod.crear_app(abiertos=[router_mod.router])


@pytest.fixture
def cliente(app_salud):
    return TestClient(app_salud)  # sin contexto: el lifespan no corre


def test_live_responde_200_con_cuerpo_propio(cliente):
    r = cliente.get("/health/live")
    assert r.status_code == 200
    assert r.json() == {"estado": "vivo"}


def test_live_no_toca_el_motor(app_salud, router_mod, cliente):
    llamadas = []

    def motor_contador():
        llamadas.append(1)

    app_salud.dependency_overrides[router_mod.get_motor] = motor_contador
    r = cliente.get("/health/live")
    assert r.status_code == 200
    assert llamadas == []


def test_live_responde_sin_lifespan_ni_motor_en_app_state(cliente):
    assert not hasattr(cliente.app.state, "engine")
    assert cliente.get("/health/live").status_code == 200


# --- ready -----------------------------------------------------------------


class ConexionFalsa:
    def __init__(self, sql, demora=0):
        self.sql = sql
        self.demora = demora

    async def execute(self, consulta):
        if self.demora:
            await asyncio.sleep(self.demora)
        self.sql.append(str(consulta))


class _Conectar:
    def __init__(self, motor):
        self.motor = motor

    async def __aenter__(self):
        if self.motor.error is not None:
            raise self.motor.error
        return ConexionFalsa(self.motor.sql, self.motor.demora)

    async def __aexit__(self, *exc):
        self.motor.cierres += 1
        return False


class MotorFalso:
    def __init__(self, error=None, demora=0):
        self.error = error
        self.demora = demora
        self.sql = []
        self.cierres = 0

    def connect(self):
        return _Conectar(self)


def con_motor(app, router_mod, motor):
    app.dependency_overrides[router_mod.get_motor] = lambda: motor


def test_ready_ok_ejecuta_select_1(app_salud, router_mod, cliente):
    motor = MotorFalso()
    con_motor(app_salud, router_mod, motor)
    r = cliente.get("/health/ready")
    assert r.status_code == 200
    assert r.json() == {"estado": "listo"}
    assert motor.sql == ["SELECT 1"]
    assert motor.cierres == 1


def _error_os():
    return OSError("could not connect to host-secreto:5433 as usuario-x")


def _error_operacional():
    return OperationalError("SELECT 1", {}, Exception("host-secreto:5433"))


CASOS_FALLO = ["os_error", "operational_error", "sin_motor"]


@pytest.fixture(params=CASOS_FALLO)
def app_con_fallo(request, app_salud, router_mod):
    if request.param == "os_error":
        con_motor(app_salud, router_mod, MotorFalso(error=_error_os()))
    elif request.param == "operational_error":
        con_motor(app_salud, router_mod, MotorFalso(error=_error_operacional()))
    # sin_motor: get_motor real, app.state sin engine
    return app_salud


def test_ready_fallo_responde_503_con_cuerpo_fijo(app_con_fallo):
    r = TestClient(app_con_fallo).get("/health/ready")
    assert r.status_code == 503
    assert r.json() == {"estado": "no_listo"}


def test_ready_503_no_filtra_detalles(app_salud, router_mod, cliente):
    con_motor(app_salud, router_mod, MotorFalso(error=_error_os()))
    texto = cliente.get("/health/ready").text
    for secreto in ("host-secreto", "5433", "usuario-x", "OSError"):
        assert secreto not in texto


def test_ready_tiempo_maximo_acota_la_respuesta(app_salud, router_mod, cliente, monkeypatch):
    monkeypatch.setattr(router_mod, "TIEMPO_MAXIMO_READY_SEGUNDOS", 0.1)
    con_motor(app_salud, router_mod, MotorFalso(demora=10))
    inicio = time.perf_counter()
    r = cliente.get("/health/ready")
    assert time.perf_counter() - inicio < 1
    assert r.status_code == 503
    assert r.json() == {"estado": "no_listo"}


def test_ready_log_sin_secretos(app_salud, router_mod, cliente, caplog):
    con_motor(app_salud, router_mod, MotorFalso(error=_error_os()))
    with caplog.at_level(logging.WARNING):
        cliente.get("/health/ready")
    avisos = [x for x in caplog.records if x.levelno == logging.WARNING]
    assert avisos
    texto = " ".join(x.getMessage() for x in avisos)
    assert "OSError" in texto
    assert "host-secreto" not in texto and "5433" not in texto


# --- grupo abierto y app real ----------------------------------------------


def test_salud_no_pasa_por_el_control_del_grupo_protegido(
    main_mod, router_mod
):
    from fastapi import APIRouter, HTTPException

    from app.core.dependencies import exigir_acceso

    control = APIRouter()

    @control.get("/control")
    async def ruta_control():
        return {"ok": True}

    app = main_mod.crear_app(abiertos=[router_mod.router], protegidos=[control])
    invocaciones = []

    async def rechaza_todo():
        invocaciones.append(1)
        raise HTTPException(status_code=401, detail="no")

    app.dependency_overrides[exigir_acceso] = rechaza_todo
    app.dependency_overrides[router_mod.get_motor] = lambda: MotorFalso()
    cliente = TestClient(app)

    assert cliente.get("/health/live").status_code == 200
    assert cliente.get("/health/ready").status_code == 200
    assert invocaciones == []
    assert cliente.get("/control").status_code == 401
    assert invocaciones == [1]


def test_app_real_expone_las_rutas_de_salud(main_mod):
    # Esta version de FastAPI anida los routers incluidos en app.routes;
    # el esquema OpenAPI lista las rutas efectivas de forma estable.
    rutas = main_mod.app.openapi()["paths"]
    assert {"/health/live", "/health/ready"} <= set(rutas)
    assert "security" not in rutas["/health/live"]["get"]
    assert "security" not in rutas["/health/ready"]["get"]


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_app_real_sin_postgresql_live_200_y_ready_503_a_tiempo(
    secretos_validos, entorno_limpio
):
    entorno_limpio.setenv("POSTGRES_HOST", "127.0.0.1")
    entorno_limpio.setenv("POSTGRES_PORT", str(_puerto_libre()))
    import main

    main = importlib.reload(main)
    with TestClient(main.app) as cliente:  # lifespan real
        assert cliente.get("/health/live").status_code == 200
        inicio = time.perf_counter()
        r = cliente.get("/health/ready")
        assert time.perf_counter() - inicio <= 3
    assert r.status_code == 503
    assert r.json() == {"estado": "no_listo"}
