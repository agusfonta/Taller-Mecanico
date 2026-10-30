"""Idempotencia del seed (C-11, 3.5): N corridas dejan el mismo estado, con ids incluidos."""
import pytest

import seed
from test.integration.seed.ayudantes import snapshot

pytestmark = pytest.mark.integration


async def _ensuciar(db) -> None:
    """Modifica la base como lo haria la API: filas nuevas en tablas de negocio y de solo agregado."""
    await db.ejecutar(
        "INSERT INTO cliente (usuario_id, nombre, documento, telefono) VALUES (NULL, 'Extra', '99000111', '555')"
    )
    await db.ejecutar(
        "INSERT INTO movimiento_stock (repuesto_id, usuario_id, cantidad, motivo) VALUES (1, 1, 5, 'Reposición')"
    )
    await db.ejecutar("UPDATE repuesto SET stock = stock + 5 WHERE id = 1")
    await db.ejecutar(
        "INSERT INTO historial_precio_repuesto (repuesto_id, usuario_id, precio_anterior, precio_nuevo) "
        "VALUES (3, 1, 3000.00, 3100.00)"
    )
    await db.ejecutar("UPDATE repuesto SET precio = 3100.00 WHERE id = 3")
    await db.ejecutar(
        "INSERT INTO intento_acceso (email, ip, exito) VALUES ('admin@example.com', '203.0.113.9', true)"
    )
    await db.ejecutar("UPDATE orden_trabajo SET estado = 'TERMINADA' WHERE id = 2")


async def test_ejecutar_dos_veces_con_datos_modificados_deja_el_mismo_estado(
    seed_cargado, db_auth, fabrica_seed, contrasenas_seed
):
    antes = await snapshot(db_auth)
    await _ensuciar(db_auth)
    assert await snapshot(db_auth) != antes  # la modificacion es visible: la comparacion no es trivial

    await seed.cargar_datos_iniciales(fabrica_seed, contrasenas_seed)

    assert await snapshot(db_auth) == antes


async def test_tres_corridas_seguidas_dejan_el_mismo_estado_y_los_mismos_ids(
    seed_cargado, db_auth, fabrica_seed, contrasenas_seed
):
    primera = await snapshot(db_auth)
    for _ in range(2):
        await _ensuciar(db_auth)
        await seed.cargar_datos_iniciales(fabrica_seed, contrasenas_seed)
        assert await snapshot(db_auth) == primera


async def test_el_reseed_vacia_las_tablas_de_solo_agregado_pese_al_disparador(
    seed_cargado, db_auth, fabrica_seed, contrasenas_seed
):
    await _ensuciar(db_auth)
    assert await db_auth.contar("movimiento_stock") == 5
    await seed.cargar_datos_iniciales(fabrica_seed, contrasenas_seed)
    assert await db_auth.contar("movimiento_stock") == 4
    assert await db_auth.contar("historial_precio_repuesto") == 1


async def test_los_hashes_se_recalculan_con_sal_nueva_y_siguen_verificando(
    seed_cargado, db_auth, fabrica_seed, contrasenas_seed
):
    antes = {f["email"]: f["password_hash"] for f in await db_auth.filas("SELECT email, password_hash FROM usuario")}
    await seed.cargar_datos_iniciales(fabrica_seed, contrasenas_seed)
    despues = {f["email"]: f["password_hash"] for f in await db_auth.filas("SELECT email, password_hash FROM usuario")}
    assert set(antes) == set(despues)
    for email in antes:
        assert antes[email] != despues[email]
        assert await contrasenas_seed.verificar(seed.CONTRASENAS_SEED[email], despues[email]) is True
