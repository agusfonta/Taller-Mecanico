"""Estructura obligatoria del repositorio (KB 08) y dependencias declaradas (D8)."""
import importlib
import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
MODULOS = ["health", "usuarios", "clientes", "repuestos", "ordenes"]
ARCHIVOS_RAIZ = ["main.py", "requirements.txt", "alembic.ini", "env.example", "README.md", "seed.py"]
DIRECTORIOS_RAIZ = ["migrations", "test", "app/core"]
PAQUETES_D8 = [
    "fastapi[standard]",
    "sqlmodel",
    "sqlalchemy[asyncio]",
    "asyncpg",
    "alembic",
    "pydantic-settings",
    "bcrypt",
    "PyJWT",
]

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("nombre", ARCHIVOS_RAIZ)
def test_archivo_raiz_existe(nombre):
    assert (RAIZ / nombre).is_file()


@pytest.mark.parametrize("nombre", DIRECTORIOS_RAIZ)
def test_directorio_raiz_existe(nombre):
    assert (RAIZ / nombre).is_dir()


@pytest.mark.parametrize("modulo", MODULOS)
def test_modules_importable_sin_configuracion(modulo, monkeypatch):
    for var in ("JWT_SECRET_KEY", "POSTGRES_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    paquete = importlib.import_module(f"app.modules.{modulo}")
    assert paquete.__name__ == f"app.modules.{modulo}"


@pytest.mark.parametrize("paquete", PAQUETES_D8)
def test_requirements_declara_paquete_con_version_minima(paquete):
    lineas = (RAIZ / "requirements.txt").read_text(encoding="utf-8").splitlines()
    patron = re.compile(rf"^{re.escape(paquete)}>=\d+(\.\d+)*\s*$", re.IGNORECASE)
    assert any(patron.match(linea) for linea in lineas)


def test_requirements_no_incluye_dependencias_de_test():
    texto = (RAIZ / "requirements.txt").read_text(encoding="utf-8").lower()
    assert "pytest" not in texto


def test_test_contiene_al_menos_un_archivo_http():
    assert list((RAIZ / "test").glob("*.http"))


def test_test_contiene_solo_agregado_sql():
    assert (RAIZ / "test" / "solo_agregado.sql").is_file()


@pytest.mark.parametrize("patron", [".env", ".venv/", "__pycache__/", ".atl/", ".claude/"])
def test_gitignore_cubre_lo_que_no_se_versiona(patron):
    lineas = [linea.strip() for linea in (RAIZ / ".gitignore").read_text(encoding="utf-8").splitlines()]
    assert patron in lineas


def test_env_real_no_figura_como_archivo_versionable():
    lineas = (RAIZ / ".gitignore").read_text(encoding="utf-8").splitlines()
    negaciones = [linea for linea in lineas if linea.strip().startswith("!") and ".env" in linea]
    assert negaciones == []
