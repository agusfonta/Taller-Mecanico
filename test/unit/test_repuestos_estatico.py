"""Guardas del modulo repuestos que no necesitan base (C-08, D5/D6/D9, tareas 3.1 y 8.2)."""
import re
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.modules.modelos  # noqa: F401  (mapeos completos)
from app.modules.repuestos.models import HistorialPrecioRepuesto, MovimientoStock, Repuesto
from app.modules.repuestos.repository import (
    HistorialPrecioRepository,
    MovimientoStockRepository,
    RepuestoRepository,
    escapar_like,
)

pytestmark = pytest.mark.unit

RAIZ = Path(__file__).resolve().parents[2]
MODULO = RAIZ / "app" / "modules" / "repuestos"


def test_escapar_like_escapa_los_tres_caracteres():
    assert escapar_like("a%b_c\\") == r"a\%b\_c\\"


@pytest.mark.parametrize("texto", ["freno", "' OR '1'='1", ""])
def test_escapar_like_no_toca_texto_comun(texto):
    assert escapar_like(texto) == texto


@pytest.mark.parametrize("cambios", [{"stock": 5}, {"stock": 5, "descripcion": "x"}])
async def test_update_de_repuesto_rechaza_stock_antes_de_tocar_la_base(cambios):
    sesion = MagicMock()
    sesion.flush = AsyncMock()
    repo = RepuestoRepository(sesion)
    repuesto = Repuesto(codigo="A", descripcion="d", precio=Decimal("1.00"))
    with pytest.raises(ValueError, match="stock"):
        await repo.update(repuesto, cambios)
    sesion.flush.assert_not_awaited()
    assert repuesto.descripcion == "d"


@pytest.mark.parametrize(
    ("clase", "entidad"),
    [
        (MovimientoStockRepository, MovimientoStock),
        (HistorialPrecioRepository, HistorialPrecioRepuesto),
    ],
)
async def test_repositorios_de_solo_agregado_no_actualizan_ni_borran(clase, entidad):
    repo = clase(MagicMock())
    with pytest.raises(NotImplementedError):
        await repo.update(entidad(), {})
    with pytest.raises(NotImplementedError):
        await repo.delete(entidad())


@pytest.mark.parametrize("archivo", sorted(p.name for p in MODULO.glob("*.py")))
def test_ningun_archivo_del_modulo_confirma(archivo):
    fuente = (MODULO / archivo).read_text(encoding="utf-8")
    assert "commit(" not in fuente
    assert ".rollback(" not in fuente
    assert ".close(" not in fuente


@pytest.mark.parametrize("archivo", sorted(p.name for p in MODULO.glob("*.py")))
def test_ningun_archivo_del_modulo_usa_float(archivo):
    fuente = (MODULO / archivo).read_text(encoding="utf-8")
    assert not re.search(r"\bfloat\b", fuente)


def test_solo_sumar_stock_escribe_el_stock_en_app():
    """Busqueda estatica de escrituras de ``stock`` fuera de ``RepuestoRepository.sumar_stock``."""
    patron = re.compile(r"(\.stock\s*[-+]?=(?!=)|\bstock\s*=\s*(?!0\b)|\"stock\"\s*:)")
    hallazgos = []
    for ruta in (RAIZ / "app").rglob("*.py"):
        if "models.py" in ruta.name or ruta.name == "schemas.py" or "migrations" in str(ruta):
            continue  # definiciones de columna/contrato, no escrituras
        for n, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), 1):
            if linea.strip().startswith(("#", '"""')):
                continue
            if patron.search(linea) and "stock=Repuesto.stock + delta" not in linea:
                hallazgos.append(f"{ruta.relative_to(RAIZ)}:{n}: {linea.strip()}")
    assert hallazgos == [], hallazgos
