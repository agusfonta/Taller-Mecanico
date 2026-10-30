"""Las contraseñas del seed viven SOLO en ``seed.py`` (C-11, 2.4; DD-15).

Recorre los archivos de texto del repositorio (salvo ``seed.py``, el entorno virtual, el control de
versiones y todo ``.env``, que nunca se lee) y falla si alguno contiene literalmente una contraseña.
"""
from pathlib import Path

import pytest

import seed

RAIZ = Path(__file__).resolve().parents[2]
EXCLUIDOS = {".venv", ".git", "__pycache__", "node_modules", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
SUFIJOS = {".py", ".md", ".txt", ".yaml", ".yml", ".ini", ".sql", ".http", ".json", ".toml", ".cfg", ".example"}


def _archivos_de_texto():
    for ruta in RAIZ.rglob("*"):
        partes = set(ruta.relative_to(RAIZ).parts)
        if partes & EXCLUIDOS or not ruta.is_file():
            continue
        if ruta.name == ".env" or ruta.name.startswith(".env."):
            continue  # nunca se leen los secretos reales del desarrollador
        if ruta == RAIZ / "seed.py":
            continue
        if ruta.suffix in SUFIJOS:
            yield ruta


def _contiene(archivos, literales):
    encontrados = []
    for ruta in archivos:
        try:
            texto = ruta.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        encontrados.extend((ruta.name, i) for i, lit in enumerate(literales) if lit in texto)
    return encontrados


def test_el_recorrido_incluye_los_directorios_que_importan():
    nombres = {str(r.relative_to(RAIZ)).replace("\\", "/") for r in _archivos_de_texto()}
    assert "env.example" in nombres
    assert any(n.startswith("knowledge-base/") for n in nombres)
    assert any(n.startswith("openspec/") for n in nombres)
    assert any(n.startswith("app/") for n in nombres)
    assert "seed.py" not in nombres


def test_ningun_archivo_distinto_de_seed_contiene_una_contrasena_del_seed():
    literales = list(seed.CONTRASENAS_SEED.values())
    assert len(literales) == 7
    assert _contiene(_archivos_de_texto(), literales) == []


def test_el_detector_encuentra_un_literal_presente(tmp_path):
    archivo = tmp_path / "x.md"
    archivo.write_text("clave: " + "valor-secreto-123", encoding="utf-8")
    assert _contiene([archivo], ["valor-secreto-123", "otro"]) == [("x.md", 0)]
    assert _contiene([archivo], ["ausente"]) == []


def test_seed_py_es_el_unico_que_define_las_contrasenas():
    fuente = (RAIZ / "seed.py").read_text(encoding="utf-8")
    for contrasena in seed.CONTRASENAS_SEED.values():
        assert contrasena in fuente


@pytest.mark.parametrize("archivo", ["env.example"])
def test_env_example_no_define_variables_seed(archivo):
    assert "SEED_" not in (RAIZ / archivo).read_text(encoding="utf-8")
