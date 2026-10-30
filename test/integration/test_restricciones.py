"""Garantias delegadas a la base, sobre el esquema producido por Alembic (C-03, spec ``modelo-de-datos``).

Usa ``conexion_migrada`` (transaccion externa que se revierte). Cada violacion se prueba
en un SAVEPOINT para seguir usando la conexion y triangular (invalido / borde valido).
Inserciones con ``text()`` y parametros ligados.
"""
from decimal import Decimal

import pytest
from sqlalchemy import text

from test.integration.filas import (
    acepta,
    asignacion,
    cliente,
    estado,
    historial_estado,
    historial_precio,
    item,
    movimiento,
    orden,
    rechaza,
    repuesto,
    usuario,
    vehiculo,
)

pytestmark = pytest.mark.integration

# --- 8.1 / 8.2 unicidad -----------------------------------------------------------


async def test_email_repetido_es_rechazado(conexion_migrada):
    c = conexion_migrada
    await usuario(c, "a@example.com")
    await rechaza(c, usuario(c, "a@example.com"), restriccion="uq_usuario_email")
    assert await acepta(c, usuario(c, "b@example.com"))


async def test_documento_repetido_es_rechazado(conexion_migrada):
    c = conexion_migrada
    await cliente(c, "111")
    await rechaza(c, cliente(c, "111"), restriccion="uq_cliente_documento")
    assert await acepta(c, cliente(c, "222"))


async def test_un_cliente_por_usuario_y_varios_sin_usuario(conexion_migrada):
    c = conexion_migrada
    uid = await usuario(c)
    await cliente(c, "1", usuario_id=uid)
    await rechaza(c, cliente(c, "2", usuario_id=uid), restriccion="uq_cliente_usuario_id")
    assert await acepta(c, cliente(c, "3", usuario_id=None))
    assert await acepta(c, cliente(c, "4", usuario_id=None))


async def test_posicion_de_catalogo_repetida_es_rechazada(conexion_migrada):
    c = conexion_migrada
    await estado(c, "PENDIENTE", 1)
    await rechaza(c, estado(c, "OTRO", 1), restriccion="uq_estado_orden_posicion")
    assert await acepta(c, estado(c, "EN_REPARACION", 2))


async def test_repuesto_repetido_en_la_misma_orden_es_rechazado(conexion_migrada):
    c = conexion_migrada
    await estado(c)
    veh = await vehiculo(c, await cliente(c))
    o1, o2 = await orden(c, veh), await orden(c, veh)
    rep = await repuesto(c)
    await item(c, o1, rep)
    await rechaza(c, item(c, o1, rep), restriccion="uq_item_orden_orden_id_repuesto_id")
    assert await acepta(c, item(c, o2, rep))


# --- 8.3 unicidad entre vigentes ----------------------------------------------------


async def test_patente_vigente_repetida_es_rechazada(conexion_migrada):
    c = conexion_migrada
    cid = await cliente(c)
    await vehiculo(c, cid, "AB123CD")
    await rechaza(c, vehiculo(c, cid, "AB123CD"), restriccion="uq_vehiculo_patente_vigente")
    assert await acepta(c, vehiculo(c, cid, "ZZ999ZZ"))


async def test_patente_se_reutiliza_tras_la_baja(conexion_migrada):
    c = conexion_migrada
    cid = await cliente(c)
    await vehiculo(c, cid, "AB123CD", borrado=True)
    assert await acepta(c, vehiculo(c, cid, "AB123CD"))
    await rechaza(c, vehiculo(c, cid, "AB123CD"), restriccion="uq_vehiculo_patente_vigente")
    assert await acepta(c, vehiculo(c, cid, "AB123CD", borrado=True))


async def test_codigo_de_repuesto_entre_vigentes(conexion_migrada):
    c = conexion_migrada
    await repuesto(c, "FIL-001")
    await rechaza(c, repuesto(c, "FIL-001"), restriccion="uq_repuesto_codigo_vigente")
    await repuesto(c, "OLD-1", borrado=True)
    assert await acepta(c, repuesto(c, "OLD-1"))


async def test_asignacion_abierta_duplicada_es_rechazada(conexion_migrada):
    c = conexion_migrada
    uid = await usuario(c)
    await asignacion(c, uid, "MECANICO")
    await rechaza(c, asignacion(c, uid, "MECANICO"), restriccion="uq_asignacion_rol_abierta")
    assert await acepta(c, asignacion(c, uid, "ADMIN"))


async def test_asignacion_nueva_se_acepta_si_la_previa_esta_revocada(conexion_migrada):
    c = conexion_migrada
    uid = await usuario(c)
    await asignacion(c, uid, "MECANICO", revocada=True)
    assert await acepta(c, asignacion(c, uid, "MECANICO"))
    assert await acepta(c, asignacion(c, uid, "MECANICO", revocada=True))


# --- 8.4 CHECKs -----------------------------------------------------------------------


async def _caso_rol(c, valor):
    return await asignacion(c, await usuario(c), valor)


async def _caso_anio(c, valor):
    return await vehiculo(c, await cliente(c), anio=valor)


async def _caso_precio(c, valor):
    return await repuesto(c, precio=Decimal(valor))


async def _caso_stock(c, valor):
    rid = await repuesto(c, stock=3)
    await c.execute(text("UPDATE repuesto SET stock = :s WHERE id = :i"), {"s": valor, "i": rid})


async def _caso_total(c, valor):
    await estado(c)
    return await orden(c, await vehiculo(c, await cliente(c)), total=Decimal(valor))


async def _caso_cantidad_item(c, valor):
    await estado(c)
    veh = await vehiculo(c, await cliente(c))
    return await item(c, await orden(c, veh), await repuesto(c), cantidad=valor)


async def _caso_precio_unitario(c, valor):
    await estado(c)
    veh = await vehiculo(c, await cliente(c))
    return await item(c, await orden(c, veh), await repuesto(c), precio=Decimal(valor))


async def _caso_cantidad_movimiento(c, valor):
    return await movimiento(c, await repuesto(c), await usuario(c), cantidad=valor)


async def _caso_precio_nuevo(c, valor):
    return await historial_precio(c, await repuesto(c), await usuario(c), Decimal("5.00"), Decimal(valor))


async def _caso_precio_nuevo_distinto(c, valor):
    # valor = precio_nuevo; precio_anterior fijo en 5.00
    return await historial_precio(c, await repuesto(c), await usuario(c), Decimal("5.00"), Decimal(valor))


CASOS_CHECK = [
    ("ck_asignacion_rol_rol_valido", _caso_rol, ["SUPERUSUARIO", "admin"], ["CLIENTE", "ADMIN"]),
    ("ck_vehiculo_anio_rango", _caso_anio, [1949, 2101], [1950, 2100]),
    ("ck_repuesto_precio_positivo", _caso_precio, ["0", "-1.00"], ["0.01"]),
    ("ck_repuesto_stock_no_negativo", _caso_stock, [-1], [0, 7]),
    ("ck_orden_trabajo_total_no_negativo", _caso_total, ["-0.01"], ["0", "0.01"]),
    ("ck_item_orden_cantidad_positiva", _caso_cantidad_item, [0, -1], [1]),
    ("ck_item_orden_precio_unitario_positivo", _caso_precio_unitario, ["0"], ["0.01"]),
    ("ck_movimiento_stock_cantidad_distinta_de_cero", _caso_cantidad_movimiento, [0], [-3, 5]),
    ("ck_historial_precio_repuesto_precio_nuevo_positivo", _caso_precio_nuevo, ["0", "-1.00"], ["0.01"]),
    ("ck_historial_precio_repuesto_precio_nuevo_distinto", _caso_precio_nuevo_distinto, ["5.00"], ["5.01"]),
]


@pytest.mark.parametrize(("nombre", "caso", "malos", "buenos"), CASOS_CHECK, ids=[c[0] for c in CASOS_CHECK])
async def test_check_rechaza_invalidos_y_acepta_el_borde(conexion_migrada, nombre, caso, malos, buenos):
    c = conexion_migrada
    for valor in malos:
        async with c.begin_nested() as sp:  # aislar el estado previo de cada intento
            await rechaza(c, caso(c, valor), restriccion=nombre, sqlstate="23514")
            await sp.rollback()
    for valor in buenos:
        async with c.begin_nested() as sp:
            await acepta(c, caso(c, valor))
            await sp.rollback()


# --- 8.5 FK al catalogo y obligatoriedad ------------------------------------------------


async def test_catalogo_vacio_impide_ordenes(conexion_migrada):
    c = conexion_migrada
    veh = await vehiculo(c, await cliente(c))
    await rechaza(c, orden(c, veh, "PENDIENTE"), restriccion="fk_orden_trabajo_estado_estado_orden")


async def test_orden_con_estado_del_catalogo_se_acepta_y_el_inexistente_no(conexion_migrada):
    c = conexion_migrada
    veh = await vehiculo(c, await cliente(c))
    await estado(c, "PENDIENTE", 1)
    assert await acepta(c, orden(c, veh, "PENDIENTE"))
    await rechaza(c, orden(c, veh, "INEXISTENTE"), restriccion="fk_orden_trabajo_estado_estado_orden")


async def test_historial_de_estados_valida_hasta_y_admite_desde_nulo(conexion_migrada):
    c = conexion_migrada
    await estado(c, "PENDIENTE", 1)
    oid = await orden(c, await vehiculo(c, await cliente(c)))
    uid = await usuario(c)
    assert await acepta(c, historial_estado(c, oid, uid, desde=None, hasta="PENDIENTE"))
    await rechaza(
        c, historial_estado(c, oid, uid, hasta="INEXISTENTE"),
        restriccion="fk_historial_estado_orden_hasta_estado_estado_orden",
    )
    await rechaza(
        c, historial_estado(c, oid, uid, desde="INEXISTENTE", hasta="PENDIENTE"),
        restriccion="fk_historial_estado_orden_desde_estado_estado_orden",
    )


async def test_vehiculo_sin_patente_es_rechazado_por_not_null(conexion_migrada):
    c = conexion_migrada
    cid = await cliente(c)
    sin_patente = c.execute(
        text("INSERT INTO vehiculo (cliente_id, marca, modelo, anio) VALUES (:c, 'M', 'X', 2020)"), {"c": cid}
    )
    await rechaza(c, sin_patente, sqlstate="23502")
    assert await acepta(c, vehiculo(c, cid))


async def test_nulos_permitidos_orden_sin_mecanico_y_cliente_sin_usuario(conexion_migrada):
    c = conexion_migrada
    await estado(c)
    veh = await vehiculo(c, await cliente(c, usuario_id=None))
    assert await acepta(c, orden(c, veh, mecanico_id=None))
    assert await acepta(c, orden(c, veh, mecanico_id=await usuario(c)))


async def test_borrar_un_repuesto_con_movimientos_es_rechazado(conexion_migrada):
    c = conexion_migrada
    rid = await repuesto(c)
    await movimiento(c, rid, await usuario(c))
    await rechaza(c, c.execute(text("DELETE FROM repuesto WHERE id = :i"), {"i": rid}), sqlstate="23503")
    sin_movimientos = await repuesto(c, "OTRO-1")
    await acepta(c, c.execute(text("DELETE FROM repuesto WHERE id = :i"), {"i": sin_movimientos}))
    quedan = (await c.execute(text("SELECT count(*) FROM movimiento_stock WHERE repuesto_id = :i"), {"i": rid})).scalar_one()
    assert quedan == 1


# --- 8.6 tipos reales ---------------------------------------------------------------------


async def test_dinero_ida_y_vuelta_es_decimal_exacto(conexion_migrada):
    from sqlalchemy import select

    from app.core.database import crear_fabrica_sesiones
    from app.modules.repuestos.models import Repuesto

    c = conexion_migrada
    await repuesto(c, "FIL-002", Decimal("8500.10"))
    await repuesto(c, "FIL-003", Decimal("0.07"))
    fabrica = crear_fabrica_sesiones(c)  # misma fabrica de la app, sobre la conexion de prueba
    async with fabrica() as sesion:
        filas = {r.codigo: r.precio for r in (await sesion.execute(select(Repuesto))).scalars()}
    assert filas["FIL-002"] == Decimal("8500.10") and isinstance(filas["FIL-002"], Decimal)
    assert filas["FIL-003"] == Decimal("0.07")


async def test_tipos_de_columna_en_information_schema(conexion_migrada, esquema_migrado):
    c = conexion_migrada
    filas = (
        await c.execute(
            text(
                "SELECT table_name, column_name, data_type, numeric_precision, numeric_scale "
                "FROM information_schema.columns WHERE table_schema = :e"
            ),
            {"e": esquema_migrado},
        )
    ).all()
    columnas = {(f[0], f[1]): f for f in filas}
    fechas = [
        ("usuario", "password_cambiada_en"), ("asignacion_rol", "desde"), ("asignacion_rol", "vence_en"),
        ("asignacion_rol", "revocada_en"), ("intento_acceso", "cuando"), ("evento_seguridad", "cuando"),
        ("vehiculo", "borrado_en"), ("repuesto", "borrado_en"), ("orden_trabajo", "creada_en"),
        ("historial_estado_orden", "cuando"), ("movimiento_stock", "cuando"),
        ("historial_precio_repuesto", "cuando"),
    ]
    for clave in fechas:
        assert columnas[clave][2] == "timestamp with time zone", clave
    dinero = {
        ("repuesto", "precio"): (10, 2), ("item_orden", "precio_unitario"): (10, 2),
        ("historial_precio_repuesto", "precio_anterior"): (10, 2),
        ("historial_precio_repuesto", "precio_nuevo"): (10, 2), ("orden_trabajo", "total"): (12, 2),
    }
    for clave, (p, e) in dinero.items():
        assert columnas[clave][2] == "numeric" and (columnas[clave][3], columnas[clave][4]) == (p, e), clave
    assert columnas[("intento_acceso", "ip")][2] == "text"
    assert columnas[("usuario", "id")][2] == "bigint"
    assert not [k for k in columnas if k[1] == "rol" and k[0] == "usuario"]


# --- 8.7 FK indexadas -------------------------------------------------------------------------

SQL_FK_SIN_INDICE = """
SELECT c.conrelid::regclass::text, a.attname
FROM pg_constraint c
JOIN pg_namespace n ON n.oid = c.connamespace
JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
WHERE c.contype = 'f' AND n.nspname = :e
  AND NOT EXISTS (
      SELECT 1 FROM pg_index i
      WHERE i.indrelid = c.conrelid AND i.indkey[0] = c.conkey[1] AND i.indpred IS NULL)
"""


async def test_toda_fk_tiene_indice(conexion_migrada, esquema_migrado):
    c = conexion_migrada
    total = (
        await c.execute(
            text(
                "SELECT count(*) FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace "
                "WHERE c.contype = 'f' AND n.nspname = :e"
            ),
            {"e": esquema_migrado},
        )
    ).scalar_one()
    sin_indice = (await c.execute(text(SQL_FK_SIN_INDICE), {"e": esquema_migrado})).all()
    assert total == 18
    assert sin_indice == []


async def test_las_fk_no_borran_en_cascada(conexion_migrada, esquema_migrado):
    c = conexion_migrada
    acciones = (
        await c.execute(
            text(
                "SELECT DISTINCT c.confdeltype::text, c.confupdtype::text FROM pg_constraint c "
                "JOIN pg_namespace n ON n.oid = c.connamespace WHERE c.contype = 'f' AND n.nspname = :e"
            ),
            {"e": esquema_migrado},
        )
    ).all()
    assert [tuple(a) for a in acciones] == [("a", "a")]  # NO ACTION


async def test_indice_de_intentos_de_acceso_email_ip_cuando(conexion_migrada, esquema_migrado):
    c = conexion_migrada
    columnas = (
        await c.execute(
            text(
                "SELECT a.attname FROM pg_index i JOIN pg_class ic ON ic.oid = i.indexrelid "
                "JOIN pg_namespace n ON n.oid = ic.relnamespace "
                "CROSS JOIN LATERAL unnest(i.indkey::int2[]) WITH ORDINALITY AS k(attnum, ord) "
                "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum "
                "WHERE n.nspname = :e AND ic.relname = 'ix_intento_acceso_email_ip_cuando' ORDER BY k.ord"
            ),
            {"e": esquema_migrado},
        )
    ).scalars().all()
    assert columnas == ["email", "ip", "cuando"]
