"""Importar ``seed`` no tiene efectos y su docstring documenta la puesta en marcha (C-11, 5.3)."""
import os
import subprocess
import sys
from pathlib import Path

import seed

RAIZ = Path(__file__).resolve().parents[2]
PROGRAMA = (
    "import bcrypt, sys\n"
    "def prohibido(*a, **k):\n"
    "    raise SystemExit('efecto al importar')\n"
    "bcrypt.hashpw = prohibido\n"
    "import seed\n"
    "assert 'seed' in sys.modules\n"
    "print('importado')\n"
)


def test_importar_seed_no_requiere_configuracion_ni_hashea_ni_conecta(tmp_path):
    entorno = {k: v for k, v in os.environ.items() if not k.startswith(("POSTGRES_", "JWT_", "BCRYPT_"))}
    entorno["PYTHONPATH"] = str(RAIZ)
    resultado = subprocess.run(
        [sys.executable, "-c", PROGRAMA], cwd=tmp_path, env=entorno, capture_output=True, text=True, timeout=60
    )
    assert resultado.returncode == 0, resultado.stderr
    assert resultado.stdout.strip() == "importado"


def test_el_docstring_documenta_proposito_orden_advertencia_bandera_y_dd15():
    doc = seed.__doc__ or ""
    assert "alembic upgrade head" in doc and "python seed.py" in doc and "uvicorn" in doc
    assert doc.index("alembic upgrade head") < doc.index("python seed.py") < doc.index("uvicorn")
    assert "BORRA" in doc
    assert "--permitir-remoto" in doc
    assert "DD-15" in doc


def test_el_docstring_no_incluye_ninguna_contrasena():
    doc = seed.__doc__ or ""
    assert not [c for c in seed.CONTRASENAS_SEED.values() if c in doc]
