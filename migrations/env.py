import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from app.core.config import get_settings
from app.modules.modelos import metadata

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging. Sin deshabilitar los loggers
# existentes: correr Alembic desde los tests no debe silenciar a la app/pytest.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Metadata completa de los modelos de tabla (C-03). Las tablas de prueba de
# test/integration viven en otra metadata y nunca llegan aca.
target_metadata = metadata


def obtener_url() -> str:
    """URL asincrona desde Settings (nunca de alembic.ini).

    No se pasa por config.set_main_option porque configparser interpreta '%'
    (contrasenas escapadas). Se calcula solo cuando hace falta: con una conexion
    inyectada (tests) no se lee la configuracion.
    """
    return get_settings().database_url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    context.configure(
        url=obtener_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    connectable = create_async_engine(obtener_url(), poolclass=pool.NullPool)

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
        await connection.commit()

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    Si el llamador inyecta una conexion sincrona en ``config.attributes["connection"]``
    (receta "sharing a connection" de Alembic; la usan los tests dentro de su propio
    bucle de eventos), se usa tal cual; si no, motor asincrono desde Settings.
    """
    conexion = config.attributes.get("connection")
    if conexion is not None:
        do_run_migrations(conexion)
    else:
        asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
