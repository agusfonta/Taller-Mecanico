"""Atomicidad del seed (C-11, 3.6): una falla despues del TRUNCATE revierte TODO, secuencias incluidas."""
import dataclasses
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

import seed
from test.integration.seed.ayudantes import snapshot

pytestmark = pytest.mark.integration

INSERTAR_CLIENTE = (
    "INSERT INTO cliente (usuario_id, nombre, documento, telefono) VALUES (NULL, 'Previo', :d, '555') RETURNING id"
)


async def _proximo_id_de_cliente(db, documento: str) -> int:
    async with db.motor.begin() as c:
        from sqlalchemy import text

        return (await c.execute(text(INSERTAR_CLIENTE), {"d": documento})).scalar_one()


async def test_una_falla_tras_el_truncate_deja_intactos_los_datos_previos(
    seed_cargado, db_auth, fabrica_seed, contrasenas_seed, monkeypatch
):
    await db_auth.ejecutar(
        "INSERT INTO intento_acceso (email, ip, exito) VALUES ('previo@example.com', '203.0.113.7', false)"
    )
    antes = await snapshot(db_auth)

    # Un precio 0 viola ck_repuesto_precio_positivo: el INSERT de repuestos falla DESPUES del TRUNCATE,
    # del catalogo y de los usuarios ya cargados.
    invalido = dataclasses.replace(seed.REPUESTOS[0], precio=Decimal("0.00"))
    monkeypatch.setattr(seed, "REPUESTOS", (invalido, *seed.REPUESTOS[1:]))

    with pytest.raises(IntegrityError):
        await seed.cargar_datos_iniciales(fabrica_seed, contrasenas_seed)

    assert await snapshot(db_auth) == antes


async def test_una_falla_tras_el_truncate_no_reinicia_las_secuencias(
    seed_cargado, db_auth, fabrica_seed, contrasenas_seed, monkeypatch
):
    extra = await _proximo_id_de_cliente(db_auth, "70000001")
    assert extra == 3  # tras el seed (clientes 1 y 2) el siguiente id es 3
    antes = await snapshot(db_auth)

    invalido = dataclasses.replace(seed.REPUESTOS[0], precio=Decimal("0.00"))
    monkeypatch.setattr(seed, "REPUESTOS", (invalido, *seed.REPUESTOS[1:]))
    with pytest.raises(IntegrityError):
        await seed.cargar_datos_iniciales(fabrica_seed, contrasenas_seed)

    # Sin rollback de la secuencia, RESTART IDENTITY la habria dejado en 1 y el proximo id seria 1 (o 3).
    assert await _proximo_id_de_cliente(db_auth, "70000002") == 4
    assert (await snapshot(db_auth))["cliente"][:3] == antes["cliente"]


async def test_tras_la_falla_un_nuevo_seed_valido_sigue_funcionando(
    seed_cargado, db_auth, fabrica_seed, contrasenas_seed, monkeypatch
):
    invalido = dataclasses.replace(seed.REPUESTOS[0], precio=Decimal("0.00"))
    with monkeypatch.context() as parche:
        parche.setattr(seed, "REPUESTOS", (invalido, *seed.REPUESTOS[1:]))
        with pytest.raises(IntegrityError):
            await seed.cargar_datos_iniciales(fabrica_seed, contrasenas_seed)
    resumen = await seed.cargar_datos_iniciales(fabrica_seed, contrasenas_seed)
    assert resumen.conteos["repuesto"] == 4
    assert await db_auth.contar("usuario") == 7
