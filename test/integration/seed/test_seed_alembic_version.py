"""El seed no toca la tabla de version de migraciones (C-11, spec: "Migration-version table untouched").

Corre solo sobre el esquema efimero (``db_auth``), nunca sobre ``public``.
"""
import pytest

import seed

pytestmark = pytest.mark.integration

VERSION_CONOCIDA = "c11_version_sentinela"


async def test_el_seed_deja_intacta_alembic_version_y_reemplaza_las_tablas_de_negocio(
    db_auth, fabrica_seed, contrasenas_seed
):
    await db_auth.ejecutar(
        "CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
    )
    await db_auth.ejecutar("DELETE FROM alembic_version")
    await db_auth.ejecutar("INSERT INTO alembic_version (version_num) VALUES (:v)", v=VERSION_CONOCIDA)
    await db_auth.ejecutar(
        "INSERT INTO cliente (usuario_id, nombre, documento, telefono) VALUES (NULL, 'Extra', '99000111', '555')"
    )
    assert await db_auth.contar("cliente") == 1

    await seed.cargar_datos_iniciales(fabrica_seed, contrasenas_seed)

    filas = await db_auth.filas("SELECT version_num FROM alembic_version")
    assert [f["version_num"] for f in filas] == [VERSION_CONOCIDA]
    assert await db_auth.contar("cliente") == 2  # las filas de negocio se reemplazaron por las del seed
    assert await db_auth.contar("usuario") == 7
