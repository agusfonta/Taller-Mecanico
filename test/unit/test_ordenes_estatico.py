"""Guardas estaticas del modulo ordenes que no necesitan base (C-09, D3/D13, tarea 3.1)."""
import inspect
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.modules.modelos  # noqa: F401  (mapeos completos)
from app.modules.ordenes.models import HistorialEstadoOrden
from app.modules.ordenes.repository import (
    EstadoOrdenRepository,
    HistorialEstadoOrdenRepository,
    ItemOrdenRepository,
    OrdenRepository,
)

pytestmark = pytest.mark.unit

RAIZ = Path(__file__).resolve().parents[2]
MODULO = RAIZ / "app" / "modules" / "ordenes"

REPOSITORIOS = [
    EstadoOrdenRepository,
    OrdenRepository,
    ItemOrdenRepository,
    HistorialEstadoOrdenRepository,
]


@pytest.mark.parametrize("metodo", ["add", "update", "delete"])
def test_repositorio_del_catalogo_no_expone_escritura(metodo):
    assert not hasattr(EstadoOrdenRepository, metodo)


def test_repositorio_del_catalogo_expone_solo_lectura():
    publicos = {n for n, _ in inspect.getmembers(EstadoOrdenRepository) if not n.startswith("_")}
    assert publicos == {"listar_por_posicion", "get_por_codigo"}


@pytest.mark.parametrize("argumentos", [("update", {}), ("delete",)])
async def test_historial_de_estados_es_de_solo_agregado(argumentos):
    operacion, *resto = argumentos
    repo = HistorialEstadoOrdenRepository(MagicMock())
    with pytest.raises(NotImplementedError):
        await getattr(repo, operacion)(HistorialEstadoOrden(), *resto)


async def test_historial_de_estados_si_agrega():
    sesion = MagicMock()
    sesion.flush = AsyncMock()
    entrada = HistorialEstadoOrden(orden_id=1, hasta_estado="PENDIENTE", usuario_id=1)
    assert await HistorialEstadoOrdenRepository(sesion).add(entrada) is entrada
    sesion.add.assert_called_once_with(entrada)
    sesion.flush.assert_awaited_once()


@pytest.mark.parametrize("archivo", sorted(p.name for p in MODULO.glob("*.py")))
def test_ningun_archivo_del_modulo_confirma(archivo):
    fuente = (MODULO / archivo).read_text(encoding="utf-8")
    assert "commit(" not in fuente
    assert ".rollback(" not in fuente
    assert ".close(" not in fuente


@pytest.mark.parametrize("clase", REPOSITORIOS)
def test_todo_metodo_publico_de_repositorio_es_asincrono(clase):
    propios = [
        (n, f)
        for n, f in inspect.getmembers(clase, inspect.isfunction)
        if not n.startswith("_")
    ]
    assert propios
    assert [n for n, f in propios if not inspect.iscoroutinefunction(f)] == []


@pytest.mark.parametrize("nombre", ["service", "router"])
def test_todo_publico_de_servicio_y_router_es_asincrono(nombre):
    import importlib

    modulo = importlib.import_module(f"app.modules.ordenes.{nombre}")
    funciones = [
        (n, f)
        for n, f in inspect.getmembers(modulo, inspect.isfunction)
        if not n.startswith("_") and f.__module__ == modulo.__name__
    ]
    assert funciones
    assert [n for n, f in funciones if not inspect.iscoroutinefunction(f)] == []


def test_bloquear_es_asincrono_y_pide_for_update_sin_relaciones():
    assert inspect.iscoroutinefunction(OrdenRepository.bloquear)
    fuente = inspect.getsource(OrdenRepository.bloquear)
    assert "with_for_update()" in fuente and "populate_existing" in fuente
    assert "joinedload" not in fuente and "selectinload" not in fuente


def test_get_detalle_documenta_el_plan_de_tres_sentencias_y_la_evidencia():
    doc = OrdenRepository.get_detalle.__doc__
    assert doc
    for ausente in ("joinedload", "selectinload", "populate_existing", "SQL_ECHO=true", "3 sentencias"):
        assert ausente in doc, ausente


def test_el_router_agenda_el_aviso_solo_despues_de_que_el_servicio_retorna():
    from app.modules.ordenes import router

    fuente = inspect.getsource(router.terminar_orden)
    assert fuente.index("service.terminar_orden(") < fuente.index("background_tasks.add_task(")
    assert fuente.count("add_task(") == 1
    for otra in (router.iniciar_orden, router.cancelar_orden):
        assert "add_task" not in inspect.getsource(otra)
