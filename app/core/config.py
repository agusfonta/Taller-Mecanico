"""Configuracion tipada de la aplicacion, leida del entorno (o de un `.env`).

Los secretos (`JWT_SECRET_KEY`, `POSTGRES_PASSWORD`) no tienen valor por defecto:
si faltan, `Settings()` levanta `ValidationError` y la aplicacion no arranca.

Advertencia: no registrar `model_dump()` en logs; incluye `database_url`, que
contiene la contrasena de la base. `repr()`/`str()` si son seguros.
"""
from functools import lru_cache

from pydantic import Field, SecretStr, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

__all__ = ["Settings", "get_settings"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # Evita que ValidationError imprima el input (con el otro secreto).
        hide_input_in_errors=True,
    )

    # --- Base de datos ---
    postgres_user: str = "taller"
    postgres_password: SecretStr = Field(min_length=1)
    postgres_db: str = "taller_db"
    postgres_host: str = "localhost"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    sql_echo: bool = False

    # --- Pool de conexiones ---
    db_pool_size: int = Field(default=5, ge=1)
    db_max_overflow: int = Field(default=10, ge=0)

    # --- JWT ---
    jwt_secret_key: SecretStr = Field(min_length=32)
    jwt_expire_minutes: int = Field(default=30, ge=1)

    # --- bcrypt ---
    bcrypt_rounds: int = Field(default=12, ge=4, le=31)
    bcrypt_max_concurrency: int = Field(default=4, ge=1)

    # --- Cookie ---
    cookie_secure: bool = False

    @computed_field
    @property
    def jwt_expire_seconds(self) -> int:
        """Duracion del token en segundos (exp, Max-Age y `expira_en_segundos`)."""
        return self.jwt_expire_minutes * 60

    @computed_field(repr=False)
    @property
    def database_url(self) -> str:
        """URL asincrona de PostgreSQL, con usuario y contrasena escapados."""
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        ).render_as_string(hide_password=False)


@lru_cache
def get_settings() -> Settings:
    """Instancia unica de `Settings` (usable como dependencia de FastAPI)."""
    return Settings()
