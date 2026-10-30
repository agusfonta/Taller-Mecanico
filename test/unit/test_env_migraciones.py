"""migrations/env.py usa la metadata real y respeta D8 (lectura estatica del archivo)."""
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

RAIZ = Path(__file__).resolve().parents[2]
ENV = (RAIZ / "migrations" / "env.py").read_text(encoding="utf-8")
ALEMBIC_INI = (RAIZ / "alembic.ini").read_text(encoding="utf-8")


def test_importa_la_metadata_del_registro():
    assert "app.modules.modelos" in ENV
    assert "target_metadata = metadata" in ENV


def test_ya_no_deja_target_metadata_en_none():
    assert "target_metadata = None" not in ENV


def test_compara_tipos_y_defaults_de_servidor_en_ambos_modos():
    assert ENV.count("compare_type=True") >= 2
    assert ENV.count("compare_server_default=True") >= 2


def test_admite_conexion_inyectada():
    assert 'config.attributes.get("connection")' in ENV


def test_no_silencia_los_loggers_existentes():
    assert "disable_existing_loggers=False" in ENV


def test_main_importa_el_registro_de_modelos():
    main = (RAIZ / "main.py").read_text(encoding="utf-8")
    assert "import app.modules.modelos" in main
    assert "create_all" not in main


def test_la_url_sale_de_settings_y_no_de_alembic_ini():
    assert "get_settings().database_url" in ENV
    assert "sqlalchemy.url" not in ALEMBIC_INI
    assert "postgresql" not in ALEMBIC_INI


def test_la_url_no_se_calcula_al_importar_con_conexion_inyectada():
    # La URL se resuelve dentro de una funcion, no a nivel de modulo.
    assert "\ndatabase_url = get_settings()" not in ENV
