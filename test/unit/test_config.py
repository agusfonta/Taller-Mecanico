"""Configuracion tipada (spec: configuracion)."""
import pytest
from pydantic import ValidationError

from app.core.config import Settings

pytestmark = pytest.mark.unit


def _campos_con_error(exc: ValidationError) -> set[str]:
    return {str(e["loc"][0]).lower() for e in exc.errors()}


def test_settings_sin_jwt_secret_key_falla(entorno_limpio):
    entorno_limpio.setenv("POSTGRES_PASSWORD", "secreto")
    with pytest.raises(ValidationError) as info:
        Settings(_env_file=None)
    assert "jwt_secret_key" in _campos_con_error(info.value)


def test_settings_sin_postgres_password_falla(entorno_limpio):
    entorno_limpio.setenv("JWT_SECRET_KEY", "k" * 32)
    with pytest.raises(ValidationError) as info:
        Settings(_env_file=None)
    assert "postgres_password" in _campos_con_error(info.value)


@pytest.mark.parametrize("variable", ["JWT_SECRET_KEY", "POSTGRES_PASSWORD"])
def test_secreto_vacio_falla(secretos_validos, entorno_limpio, variable):
    entorno_limpio.setenv(variable, "")
    with pytest.raises(ValidationError) as info:
        Settings(_env_file=None)
    assert variable.lower() in _campos_con_error(info.value)


def test_jwt_secret_key_de_31_caracteres_falla(secretos_validos, entorno_limpio):
    entorno_limpio.setenv("JWT_SECRET_KEY", "k" * 31)
    with pytest.raises(ValidationError) as info:
        Settings(_env_file=None)
    assert "jwt_secret_key" in _campos_con_error(info.value)


def test_jwt_secret_key_de_32_caracteres_carga(secretos_validos, entorno_limpio):
    entorno_limpio.setenv("JWT_SECRET_KEY", "k" * 32)
    settings = Settings(_env_file=None)
    assert settings.jwt_secret_key.get_secret_value() == "k" * 32


def test_settings_defaults_dd17(secretos_validos):
    settings = Settings(_env_file=None)
    assert settings.jwt_expire_minutes == 30
    assert settings.bcrypt_rounds == 12
    assert settings.bcrypt_max_concurrency == 4
    assert settings.db_pool_size == 5
    assert settings.db_max_overflow == 10
    assert settings.sql_echo is False
    assert settings.cookie_secure is False
    assert settings.postgres_host == "localhost"
    assert settings.postgres_port == 5432
    assert settings.postgres_user == "taller"
    assert settings.postgres_db == "taller_db"


def test_settings_toma_valores_del_entorno(secretos_validos, entorno_limpio):
    entorno_limpio.setenv("POSTGRES_HOST", "db")
    entorno_limpio.setenv("POSTGRES_PORT", "6543")
    entorno_limpio.setenv("JWT_EXPIRE_MINUTES", "15")
    entorno_limpio.setenv("BCRYPT_ROUNDS", "4")
    settings = Settings(_env_file=None)
    assert settings.postgres_host == "db"
    assert settings.postgres_port == 6543
    assert settings.jwt_expire_minutes == 15
    assert settings.bcrypt_rounds == 4


def test_settings_ignora_variables_ajenas(secretos_validos, entorno_limpio):
    entorno_limpio.setenv("OTRA_COSA", "1")
    settings = Settings(_env_file=None)
    assert settings.postgres_user == "taller"


@pytest.mark.parametrize(
    ("variable", "valor"),
    [
        ("BCRYPT_ROUNDS", "3"),
        ("BCRYPT_ROUNDS", "32"),
        ("DB_POOL_SIZE", "0"),
        ("DB_MAX_OVERFLOW", "-1"),
        ("BCRYPT_MAX_CONCURRENCY", "0"),
        ("JWT_EXPIRE_MINUTES", "0"),
        ("POSTGRES_PORT", "0"),
        ("POSTGRES_PORT", "65536"),
        ("POSTGRES_PORT", "abc"),
    ],
)
def test_valores_fuera_de_rango_fallan(secretos_validos, entorno_limpio, variable, valor):
    entorno_limpio.setenv(variable, valor)
    with pytest.raises(ValidationError) as info:
        Settings(_env_file=None)
    assert variable.lower() in _campos_con_error(info.value)


@pytest.mark.parametrize(
    ("variable", "valor"),
    [("BCRYPT_ROUNDS", "4"), ("BCRYPT_ROUNDS", "31"), ("DB_MAX_OVERFLOW", "0"), ("POSTGRES_PORT", "65535")],
)
def test_limites_validos_cargan(secretos_validos, entorno_limpio, variable, valor):
    entorno_limpio.setenv(variable, valor)
    Settings(_env_file=None)


@pytest.mark.parametrize(("minutos", "segundos"), [(None, 1800), ("15", 900)])
def test_jwt_expire_seconds(secretos_validos, entorno_limpio, minutos, segundos):
    if minutos is not None:
        entorno_limpio.setenv("JWT_EXPIRE_MINUTES", minutos)
    assert Settings(_env_file=None).jwt_expire_seconds == segundos


def test_database_url_valores_simples(entorno_limpio):
    entorno_limpio.setenv("JWT_SECRET_KEY", "k" * 32)
    entorno_limpio.setenv("POSTGRES_PASSWORD", "secreto")
    assert (
        Settings(_env_file=None).database_url
        == "postgresql+asyncpg://taller:secreto@localhost:5432/taller_db"
    )


def test_database_url_escapa_caracteres_especiales(entorno_limpio):
    entorno_limpio.setenv("JWT_SECRET_KEY", "k" * 32)
    entorno_limpio.setenv("POSTGRES_PASSWORD", "p@ss:w/rd")
    url = Settings(_env_file=None).database_url
    assert "p%40ss%3Aw%2Frd" in url
    assert url.endswith("@localhost:5432/taller_db")


def test_repr_y_str_no_exponen_secretos(secretos_validos):
    settings = Settings(_env_file=None)
    for texto in (repr(settings), str(settings)):
        assert secretos_validos["JWT_SECRET_KEY"] not in texto
        assert secretos_validos["POSTGRES_PASSWORD"] not in texto


def test_get_settings_devuelve_misma_instancia(secretos_validos):
    from app.core.config import get_settings

    assert get_settings() is get_settings()


def test_get_settings_cache_clear_relee_el_entorno(secretos_validos, entorno_limpio):
    from app.core.config import get_settings

    antes = get_settings()
    entorno_limpio.setenv("JWT_EXPIRE_MINUTES", "7")
    assert get_settings().jwt_expire_minutes == antes.jwt_expire_minutes
    get_settings.cache_clear()
    assert get_settings().jwt_expire_minutes == 7


def _leer_env_example() -> dict[str, str]:
    from pathlib import Path

    ruta = Path(__file__).resolve().parents[2] / "env.example"
    entradas = {}
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#"):
            continue
        clave, _, valor = linea.partition("=")
        entradas[clave.strip()] = valor.strip()
    return entradas


def test_env_example_completo_y_sin_secretos():
    entradas = _leer_env_example()
    esperadas = {nombre.upper() for nombre in Settings.model_fields}
    assert set(entradas) == esperadas
    assert entradas["JWT_SECRET_KEY"] == ""
    assert entradas["POSTGRES_PASSWORD"] == ""
    assert not [clave for clave in entradas if clave.startswith("SEED_")]


def test_gitignore_excluye_env():
    from pathlib import Path

    gitignore = Path(__file__).resolve().parents[2] / ".gitignore"
    assert ".env" in gitignore.read_text(encoding="utf-8").splitlines()


def test_alembic_ini_sin_url():
    import configparser
    from pathlib import Path

    ruta = Path(__file__).resolve().parents[2] / "alembic.ini"
    parser = configparser.RawConfigParser()
    parser.read(ruta, encoding="utf-8")
    assert parser.get("alembic", "script_location") == "migrations"
    assert parser.get("alembic", "sqlalchemy.url", fallback="").strip() == ""
