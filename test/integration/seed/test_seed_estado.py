"""Estado conocido tras ``cargar_datos_iniciales`` (C-11, 3.1 a 3.4) sobre PostgreSQL real."""
from decimal import Decimal

import pytest

import seed
from app.core.security import crear_servicio_contrasenas

pytestmark = pytest.mark.integration

CONTEOS = {
    "estado_orden": 4,
    "usuario": 7,
    "asignacion_rol": 7,
    "cliente": 2,
    "vehiculo": 3,
    "repuesto": 4,
    "movimiento_stock": 4,
    "historial_precio_repuesto": 1,
    "orden_trabajo": 2,
    "item_orden": 4,
    "historial_estado_orden": 3,
    "evento_seguridad": 1,
    "intento_acceso": 0,
}


async def test_humo_el_nucleo_devuelve_el_resumen_con_los_siete_emails(seed_cargado):
    assert seed_cargado.emails == tuple(u.email for u in seed.USUARIOS)


# --- 3.2 conteos, ids y catalogo -----------------------------------------------------------


async def test_conteos_exactos_en_las_13_tablas(seed_cargado, db_auth):
    assert await db_auth.conteos(*CONTEOS) == CONTEOS


async def test_resumen_informa_los_mismos_conteos(seed_cargado):
    assert seed_cargado.conteos == CONTEOS


async def test_catalogo_de_estados(seed_cargado, db_auth):
    filas = await db_auth.filas("SELECT codigo, descripcion, posicion, es_final FROM estado_orden ORDER BY posicion")
    assert [(f["codigo"], f["posicion"], f["es_final"]) for f in filas] == [
        ("PENDIENTE", 1, False),
        ("EN_REPARACION", 2, False),
        ("TERMINADA", 3, True),
        ("CANCELADA", 4, True),
    ]
    assert all(f["descripcion"].strip() for f in filas)


@pytest.mark.parametrize(
    ("tabla", "ids"),
    [
        ("usuario", [1, 2, 3, 4, 5, 6, 7]),
        ("cliente", [1, 2]),
        ("vehiculo", [1, 2, 3]),
        ("repuesto", [1, 2, 3, 4]),
        ("orden_trabajo", [1, 2]),
    ],
)
async def test_ids_fijos(seed_cargado, db_auth, tabla, ids):
    assert tabla in CONTEOS
    filas = await db_auth.filas(f"SELECT id FROM {tabla} ORDER BY id")  # tabla fija de la parametrizacion
    assert [f["id"] for f in filas] == ids


async def test_usuarios_en_orden_con_su_rol_y_cambio_obligatorio(seed_cargado, db_auth):
    filas = await db_auth.filas(
        "SELECT u.id, u.email, u.activo, u.debe_cambiar_password, u.password_cambiada_en, a.rol "
        "FROM usuario u JOIN asignacion_rol a ON a.usuario_id = u.id ORDER BY u.id"
    )
    assert [(f["id"], f["email"], f["rol"], f["debe_cambiar_password"]) for f in filas] == [
        (i, u.email, u.rol.value, u.debe_cambiar_password) for i, u in enumerate(seed.USUARIOS, start=1)
    ]
    assert all(f["activo"] and f["password_cambiada_en"] is None for f in filas)


async def test_asignaciones_abiertas_sin_vencimiento_ni_otorgante(seed_cargado, db_auth):
    filas = await db_auth.filas("SELECT vence_en, revocada_en, otorgada_por FROM asignacion_rol")
    assert len(filas) == 7
    assert all(f["vence_en"] is None and f["revocada_en"] is None and f["otorgada_por"] is None for f in filas)


async def test_clientes_y_vehiculos(seed_cargado, db_auth):
    clientes = await db_auth.filas("SELECT id, usuario_id, nombre FROM cliente ORDER BY id")
    assert [(c["id"], c["usuario_id"], c["nombre"]) for c in clientes] == [(1, 6, "Laura"), (2, None, "Jorge")]
    vehiculos = await db_auth.filas("SELECT id, cliente_id, patente, borrado_en FROM vehiculo ORDER BY id")
    assert [(v["id"], v["cliente_id"]) for v in vehiculos] == [(1, 1), (2, 1), (3, 2)]
    assert all(v["borrado_en"] is None for v in vehiculos)
    assert [v["patente"] for v in vehiculos] == [v.patente for c in seed.CLIENTES for v in c.vehiculos]


async def test_repuestos_en_orden_con_codigo_precio_y_stock(seed_cargado, db_auth):
    filas = await db_auth.filas("SELECT id, codigo, precio, stock, borrado_en FROM repuesto ORDER BY id")
    assert [(f["id"], f["codigo"], f["precio"], f["stock"]) for f in filas] == [
        (1, "FIL-001", Decimal("8500.00"), 10),
        (2, "FRE-010", Decimal("25000.00"), 4),
        (3, "BUJ-001", Decimal("3000.00"), 2),
        (4, "ACE-530", Decimal("6000.00"), 20),
    ]
    assert all(f["borrado_en"] is None for f in filas)


async def test_una_sola_linea_de_seguridad_del_sistema_y_ningun_intento(seed_cargado, db_auth):
    eventos = await db_auth.filas("SELECT actor, accion FROM evento_seguridad")
    assert eventos == [{"actor": "SISTEMA", "accion": "Carga de los datos iniciales"}]
    assert await db_auth.contar("intento_acceso") == 0


# --- 3.3 stock, precios, ordenes e historiales ----------------------------------------------


async def test_stock_de_cada_repuesto_es_la_suma_de_sus_movimientos(seed_cargado, db_auth):
    filas = await db_auth.filas(
        "SELECT r.codigo, r.stock, COALESCE(SUM(m.cantidad), 0) AS suma "
        "FROM repuesto r LEFT JOIN movimiento_stock m ON m.repuesto_id = r.id GROUP BY r.id ORDER BY r.id"
    )
    assert len(filas) == 4
    assert all(f["stock"] == f["suma"] for f in filas)


async def test_cuatro_movimientos_stock_inicial_sin_orden_y_del_admin(seed_cargado, db_auth):
    filas = await db_auth.filas(
        "SELECT repuesto_id, orden_id, usuario_id, cantidad, motivo FROM movimiento_stock ORDER BY id"
    )
    assert filas == [
        {"repuesto_id": i, "orden_id": None, "usuario_id": 1, "cantidad": r.stock_inicial, "motivo": "Stock inicial"}
        for i, r in enumerate(seed.REPUESTOS, start=1)
    ]


async def test_historial_de_precio_unico_del_filtro(seed_cargado, db_auth):
    filas = await db_auth.filas("SELECT repuesto_id, usuario_id, precio_anterior, precio_nuevo FROM historial_precio_repuesto")
    assert filas == [
        {"repuesto_id": 1, "usuario_id": 1, "precio_anterior": Decimal("8000.00"), "precio_nuevo": Decimal("8500.00")}
    ]


async def test_ordenes_con_estado_vehiculo_mecanico_y_total_exacto(seed_cargado, db_auth):
    filas = await db_auth.filas("SELECT id, vehiculo_id, mecanico_id, estado, total FROM orden_trabajo ORDER BY id")
    assert filas == [
        {"id": 1, "vehiculo_id": 1, "mecanico_id": None, "estado": "PENDIENTE", "total": Decimal("32500.00")},
        {"id": 2, "vehiculo_id": 3, "mecanico_id": 4, "estado": "EN_REPARACION", "total": Decimal("20500.00")},
    ]


async def test_items_copian_el_precio_vigente_y_suman_el_total(seed_cargado, db_auth):
    items = await db_auth.filas(
        "SELECT i.orden_id, i.repuesto_id, i.cantidad, i.precio_unitario, r.precio "
        "FROM item_orden i JOIN repuesto r ON r.id = i.repuesto_id ORDER BY i.orden_id, i.repuesto_id"
    )
    assert [(i["orden_id"], i["repuesto_id"], i["cantidad"]) for i in items] == [
        (1, 1, 1),
        (1, 4, 4),
        (2, 1, 1),
        (2, 3, 4),
    ]
    assert all(i["precio_unitario"] == i["precio"] for i in items)
    totales = await db_auth.filas(
        "SELECT o.id, o.total, SUM(i.cantidad * i.precio_unitario) AS suma "
        "FROM orden_trabajo o JOIN item_orden i ON i.orden_id = o.id GROUP BY o.id ORDER BY o.id"
    )
    assert all(t["total"] == t["suma"] for t in totales)


async def test_historial_de_estados_con_sus_autores(seed_cargado, db_auth):
    filas = await db_auth.filas(
        "SELECT orden_id, desde_estado, hasta_estado, usuario_id FROM historial_estado_orden ORDER BY id"
    )
    assert filas == [
        {"orden_id": 1, "desde_estado": None, "hasta_estado": "PENDIENTE", "usuario_id": 3},
        {"orden_id": 2, "desde_estado": None, "hasta_estado": "PENDIENTE", "usuario_id": 3},
        {"orden_id": 2, "desde_estado": "PENDIENTE", "hasta_estado": "EN_REPARACION", "usuario_id": 4},
    ]


async def test_ninguna_orden_tiene_movimientos_de_stock(seed_cargado, db_auth):
    assert await db_auth.filas("SELECT 1 FROM movimiento_stock WHERE orden_id IS NOT NULL") == []


# --- 3.4 contraseñas -------------------------------------------------------------------------


async def test_cada_hash_verifica_con_su_contrasena_y_no_con_la_de_otro(seed_cargado, db_auth, settings_auth):
    servicio = crear_servicio_contrasenas(settings_auth)
    hashes = {f["email"]: f["password_hash"] for f in await db_auth.filas("SELECT email, password_hash FROM usuario")}
    assert set(hashes) == set(seed.CONTRASENAS_SEED)
    emails = list(hashes)
    for i, email in enumerate(emails):
        otro = emails[(i + 1) % len(emails)]
        assert await servicio.verificar(seed.CONTRASENAS_SEED[email], hashes[email]) is True
        assert await servicio.verificar(seed.CONTRASENAS_SEED[otro], hashes[email]) is False


async def test_los_hashes_usan_el_costo_configurado_y_son_distintos(seed_cargado, db_auth, settings_auth):
    hashes = [f["password_hash"] for f in await db_auth.filas("SELECT password_hash FROM usuario")]
    assert len(set(hashes)) == 7
    assert all(h.startswith(f"$2b${settings_auth.bcrypt_rounds:02d}$") for h in hashes)
