"""Humo de la infraestructura de auth: esquema migrado, limpieza entre tests y ayudantes (C-05, 4.1)."""
from datetime import UTC, datetime, timedelta

import pytest

from test.integration.conftest import tablas_de_negocio

pytestmark = pytest.mark.integration


async def test_esquema_auth_tiene_las_13_tablas_vacias(db_auth):
    tablas = tablas_de_negocio()
    assert len(tablas) == 13
    assert {t: await db_auth.contar(t) for t in tablas} == dict.fromkeys(tablas, 0)


async def test_esquema_auth_esta_migrado_a_head(db_auth):
    filas = await db_auth.filas("SELECT version_num FROM alembic_version")
    assert len(filas) == 1


async def test_settings_auth_usa_4_rondas_y_conserva_el_resto(settings_auth, settings_db):
    assert settings_auth.bcrypt_rounds == 4
    assert settings_auth.jwt_secret_key == settings_db.jwt_secret_key


async def test_ayudantes_siembran_usuario_roles_e_intento(db_auth):
    uid = await db_auth.crear_usuario("a@example.com", "clave-de-prueba-1", roles=["CLIENTE", "ADMIN"])
    await db_auth.insertar_intento("a@example.com", "1.2.3.4", False, datetime.now(UTC) - timedelta(seconds=5))
    assert await db_auth.contar("usuario") == 1
    assert await db_auth.contar("asignacion_rol") == 2
    assert await db_auth.contar("intento_acceso") == 1
    fila = (await db_auth.filas("SELECT * FROM usuario WHERE id = :i", i=uid))[0]
    assert fila["password_hash"].startswith("$2b$04$")
    assert fila["activo"] is True and fila["debe_cambiar_password"] is False


async def test_ayudantes_respetan_flags_de_usuario(db_auth):
    await db_auth.crear_usuario("i@example.com", "clave-de-prueba-1", activo=False, debe_cambiar_password=True)
    fila = (await db_auth.filas("SELECT activo, debe_cambiar_password FROM usuario"))[0]
    assert fila == {"activo": False, "debe_cambiar_password": True}


# Los dos siguientes prueban la limpieza: el primero ensucia, el segundo exige limpio.


async def test_limpieza_paso_1_ensucia_intento_acceso(db_auth):
    await db_auth.insertar_intento("x@example.com", "9.9.9.9", False, datetime.now(UTC))
    assert await db_auth.contar("intento_acceso") == 1


async def test_limpieza_paso_2_encuentra_intento_acceso_vacio_y_ids_reiniciados(db_auth):
    assert await db_auth.contar("intento_acceso") == 0
    uid = await db_auth.crear_usuario("y@example.com", "clave-de-prueba-1")
    assert uid == 1  # RESTART IDENTITY
