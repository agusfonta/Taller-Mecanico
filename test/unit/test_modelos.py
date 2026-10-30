"""Modelos de tabla (C-03): tablas, columnas, tipos, restricciones y FK sobre la metadata (sin base)."""
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import CheckConstraint, DateTime, Numeric, Text, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

pytestmark = pytest.mark.unit

TABLAS = {
    "usuario": ["id", "email", "nombre", "password_hash", "activo", "debe_cambiar_password", "password_cambiada_en"],
    "asignacion_rol": ["id", "usuario_id", "rol", "desde", "vence_en", "revocada_en", "otorgada_por"],
    "intento_acceso": ["id", "cuando", "email", "ip", "exito"],
    "evento_seguridad": ["id", "cuando", "actor", "accion"],
    "cliente": ["id", "usuario_id", "nombre", "documento", "telefono"],
    "vehiculo": ["id", "cliente_id", "patente", "marca", "modelo", "anio", "borrado_en"],
    "repuesto": ["id", "codigo", "descripcion", "precio", "stock", "borrado_en"],
    "estado_orden": ["codigo", "descripcion", "posicion", "es_final"],
    "orden_trabajo": ["id", "vehiculo_id", "mecanico_id", "estado", "falla", "creada_en", "total"],
    "item_orden": ["id", "orden_id", "repuesto_id", "cantidad", "precio_unitario"],
    "historial_estado_orden": ["id", "orden_id", "desde_estado", "hasta_estado", "usuario_id", "cuando"],
    "movimiento_stock": ["id", "repuesto_id", "orden_id", "usuario_id", "cantidad", "motivo", "cuando"],
    "historial_precio_repuesto": ["id", "repuesto_id", "usuario_id", "precio_anterior", "precio_nuevo", "cuando"],
}


@pytest.fixture(scope="module")
def metadata():
    from app.modules.modelos import metadata as md

    return md


def _nombres_restricciones(tabla):
    return {c.name for c in tabla.constraints if c.name} | {i.name for i in tabla.indexes}


# --- 3.1 registro ---------------------------------------------------------


def test_metadata_contiene_exactamente_las_13_tablas(metadata):
    assert set(metadata.tables) == set(TABLAS)
    assert len(metadata.tables) == 13


def test_metadata_no_contiene_tablas_de_prueba(metadata):
    assert not [t for t in metadata.tables if t.startswith("c02_")]


def test_registro_exporta_las_13_clases():
    import app.modules.modelos as registro

    esperadas = {
        "Usuario", "AsignacionRol", "IntentoAcceso", "EventoSeguridad", "Cliente", "Vehiculo",
        "Repuesto", "MovimientoStock", "HistorialPrecioRepuesto", "EstadoOrden", "OrdenTrabajo",
        "ItemOrden", "HistorialEstadoOrden",
    }
    assert esperadas <= set(registro.__all__)


# --- 3.3 columnas ---------------------------------------------------------


@pytest.mark.parametrize("tabla", sorted(TABLAS))
def test_columnas_de_la_kb_presentes(metadata, tabla):
    reales = {c.name for c in metadata.tables[tabla].columns}
    assert set(TABLAS[tabla]) <= reales


def test_usuario_no_tiene_rol(metadata):
    assert "rol" not in metadata.tables["usuario"].columns


def test_estado_orden_tiene_pk_codigo_de_texto(metadata):
    pk = list(metadata.tables["estado_orden"].primary_key.columns)
    assert [c.name for c in pk] == ["codigo"]
    assert isinstance(pk[0].type, Text)


@pytest.mark.parametrize("tabla", sorted(set(TABLAS) - {"estado_orden"}))
def test_las_demas_tablas_tienen_pk_id_numerica_con_identidad(metadata, tabla):
    pk = list(metadata.tables[tabla].primary_key.columns)
    assert [c.name for c in pk] == ["id"]
    assert pk[0].type.python_type is int
    assert pk[0].identity is not None


# --- 3.4 tipos y nulabilidad ----------------------------------------------

DINERO = [
    ("repuesto", "precio", (10, 2)),
    ("item_orden", "precio_unitario", (10, 2)),
    ("historial_precio_repuesto", "precio_anterior", (10, 2)),
    ("historial_precio_repuesto", "precio_nuevo", (10, 2)),
    ("orden_trabajo", "total", (12, 2)),
]
FECHAS = [
    ("usuario", "password_cambiada_en"), ("asignacion_rol", "desde"), ("asignacion_rol", "vence_en"),
    ("asignacion_rol", "revocada_en"), ("intento_acceso", "cuando"), ("evento_seguridad", "cuando"),
    ("vehiculo", "borrado_en"), ("repuesto", "borrado_en"), ("orden_trabajo", "creada_en"),
    ("historial_estado_orden", "cuando"), ("movimiento_stock", "cuando"),
    ("historial_precio_repuesto", "cuando"),
]
NULAS = [
    ("usuario", "password_cambiada_en"), ("asignacion_rol", "vence_en"), ("asignacion_rol", "revocada_en"),
    ("asignacion_rol", "otorgada_por"), ("cliente", "usuario_id"), ("vehiculo", "borrado_en"),
    ("repuesto", "borrado_en"), ("orden_trabajo", "mecanico_id"), ("historial_estado_orden", "desde_estado"),
    ("movimiento_stock", "orden_id"),
]
OBLIGATORIAS = [
    ("usuario", "email"), ("usuario", "password_hash"), ("usuario", "activo"), ("asignacion_rol", "usuario_id"),
    ("asignacion_rol", "rol"), ("asignacion_rol", "desde"), ("intento_acceso", "ip"), ("intento_acceso", "exito"),
    ("evento_seguridad", "actor"), ("cliente", "documento"), ("cliente", "telefono"), ("vehiculo", "patente"),
    ("vehiculo", "anio"), ("repuesto", "precio"), ("repuesto", "stock"), ("estado_orden", "es_final"),
    ("orden_trabajo", "estado"), ("orden_trabajo", "total"), ("item_orden", "cantidad"),
    ("historial_estado_orden", "hasta_estado"), ("historial_estado_orden", "usuario_id"),
    ("movimiento_stock", "usuario_id"), ("movimiento_stock", "motivo"),
    ("historial_precio_repuesto", "usuario_id"),
]


@pytest.mark.parametrize(("tabla", "columna", "pe"), DINERO)
def test_dinero_es_numeric_decimal(metadata, tabla, columna, pe):
    tipo = metadata.tables[tabla].c[columna].type
    assert isinstance(tipo, Numeric)
    assert (tipo.precision, tipo.scale) == pe
    assert tipo.python_type is Decimal


@pytest.mark.parametrize(("tabla", "columna"), FECHAS)
def test_fechas_con_zona_horaria(metadata, tabla, columna):
    tipo = metadata.tables[tabla].c[columna].type
    assert isinstance(tipo, DateTime) and tipo.timezone is True


def test_todas_las_columnas_de_fecha_estan_cubiertas(metadata):
    todas = {
        (t.name, c.name)
        for t in metadata.tables.values()
        for c in t.columns
        if isinstance(c.type, DateTime)
    }
    assert todas == set(FECHAS)


@pytest.mark.parametrize(("tabla", "columna"), NULAS)
def test_columnas_nulas_segun_la_kb(metadata, tabla, columna):
    assert metadata.tables[tabla].c[columna].nullable is True


def test_las_nulas_son_exactamente_las_de_la_kb(metadata):
    nulas = {
        (t.name, c.name)
        for t in metadata.tables.values()
        for c in t.columns
        if c.nullable and not c.primary_key
    }
    assert nulas == set(NULAS)


@pytest.mark.parametrize(("tabla", "columna"), OBLIGATORIAS)
def test_columnas_obligatorias(metadata, tabla, columna):
    assert metadata.tables[tabla].c[columna].nullable is False


def test_ip_es_texto_no_inet(metadata):
    assert isinstance(metadata.tables["intento_acceso"].c.ip.type, Text)


def test_ningun_tipo_es_float_ni_varchar(metadata):
    for tabla in metadata.tables.values():
        ddl = str(CreateTable(tabla).compile(dialect=postgresql.dialect())).upper()
        assert "FLOAT" not in ddl and "VARCHAR" not in ddl, tabla.name


# --- 3.5 restricciones declaradas -----------------------------------------

NOMBRES_ESPERADOS = {
    "usuario": {"uq_usuario_email"},
    "cliente": {"uq_cliente_documento", "uq_cliente_usuario_id"},
    "estado_orden": {"uq_estado_orden_posicion"},
    "item_orden": {"uq_item_orden_orden_id_repuesto_id"},
    "vehiculo": {"uq_vehiculo_patente_vigente"},
    "repuesto": {"uq_repuesto_codigo_vigente"},
    "asignacion_rol": {"uq_asignacion_rol_abierta"},
}
CHECKS_TODOS = [
    ("asignacion_rol", "ck_asignacion_rol_rol_valido"),
    ("vehiculo", "ck_vehiculo_anio_rango"),
    ("repuesto", "ck_repuesto_precio_positivo"),
    ("repuesto", "ck_repuesto_stock_no_negativo"),
    ("orden_trabajo", "ck_orden_trabajo_total_no_negativo"),
    ("item_orden", "ck_item_orden_cantidad_positiva"),
    ("item_orden", "ck_item_orden_precio_unitario_positivo"),
    ("movimiento_stock", "ck_movimiento_stock_cantidad_distinta_de_cero"),
    ("historial_precio_repuesto", "ck_historial_precio_repuesto_precio_nuevo_positivo"),
    ("historial_precio_repuesto", "ck_historial_precio_repuesto_precio_nuevo_distinto"),
]


@pytest.mark.parametrize("tabla", sorted(NOMBRES_ESPERADOS))
def test_unicidades_con_nombre_esperado(metadata, tabla):
    assert NOMBRES_ESPERADOS[tabla] <= _nombres_restricciones(metadata.tables[tabla])


@pytest.mark.parametrize(("tabla", "nombre"), CHECKS_TODOS)
def test_checks_con_nombre_esperado(metadata, tabla, nombre):
    checks = {c.name for c in metadata.tables[tabla].constraints if isinstance(c, CheckConstraint)}
    assert nombre in checks


def test_hay_exactamente_10_checks(metadata):
    total = sum(
        1 for t in metadata.tables.values() for c in t.constraints if isinstance(c, CheckConstraint)
    )
    assert total == 10


@pytest.mark.parametrize(
    ("tabla", "indice", "columnas", "donde"),
    [
        ("vehiculo", "uq_vehiculo_patente_vigente", ["patente"], "borrado_en IS NULL"),
        ("repuesto", "uq_repuesto_codigo_vigente", ["codigo"], "borrado_en IS NULL"),
        ("asignacion_rol", "uq_asignacion_rol_abierta", ["usuario_id", "rol"], "revocada_en IS NULL"),
    ],
)
def test_indices_unicos_parciales(metadata, tabla, indice, columnas, donde):
    ix = next(i for i in metadata.tables[tabla].indexes if i.name == indice)
    assert ix.unique is True
    assert [c.name for c in ix.columns] == columnas
    assert str(ix.dialect_options["postgresql"]["where"]) == donde


def test_unicidad_de_columnas(metadata):
    def cols(tabla, nombre):
        u = next(
            c
            for c in metadata.tables[tabla].constraints
            if isinstance(c, UniqueConstraint) and c.name == nombre
        )
        return [c.name for c in u.columns]

    assert cols("item_orden", "uq_item_orden_orden_id_repuesto_id") == ["orden_id", "repuesto_id"]
    assert cols("cliente", "uq_cliente_usuario_id") == ["usuario_id"]
    assert cols("usuario", "uq_usuario_email") == ["email"]


def test_check_de_rol_se_arma_desde_el_enum(metadata):
    from app.modules.usuarios.models import Rol

    assert {r.value for r in Rol} == {"ADMIN", "RECEPCION", "MECANICO", "CLIENTE"}
    check = next(
        c for c in metadata.tables["asignacion_rol"].constraints if isinstance(c, CheckConstraint)
    )
    texto = str(check.sqltext)
    for rol in Rol:
        assert f"'{rol.value}'" in texto


def test_indice_de_intentos_de_acceso_en_orden(metadata):
    ix = next(
        i for i in metadata.tables["intento_acceso"].indexes
        if i.name == "ix_intento_acceso_email_ip_cuando"
    )
    assert [c.name for c in ix.columns] == ["email", "ip", "cuando"]


# --- 3.6 claves foraneas --------------------------------------------------

FKS = [
    ("asignacion_rol", "usuario_id", "usuario"), ("asignacion_rol", "otorgada_por", "usuario"),
    ("cliente", "usuario_id", "usuario"), ("vehiculo", "cliente_id", "cliente"),
    ("orden_trabajo", "vehiculo_id", "vehiculo"), ("orden_trabajo", "mecanico_id", "usuario"),
    ("orden_trabajo", "estado", "estado_orden"), ("item_orden", "orden_id", "orden_trabajo"),
    ("item_orden", "repuesto_id", "repuesto"), ("historial_estado_orden", "orden_id", "orden_trabajo"),
    ("historial_estado_orden", "desde_estado", "estado_orden"),
    ("historial_estado_orden", "hasta_estado", "estado_orden"),
    ("historial_estado_orden", "usuario_id", "usuario"), ("movimiento_stock", "repuesto_id", "repuesto"),
    ("movimiento_stock", "orden_id", "orden_trabajo"), ("movimiento_stock", "usuario_id", "usuario"),
    ("historial_precio_repuesto", "repuesto_id", "repuesto"),
    ("historial_precio_repuesto", "usuario_id", "usuario"),
]


@pytest.mark.parametrize(("tabla", "columna", "destino"), FKS)
def test_fk_apunta_a_la_tabla_correcta(metadata, tabla, columna, destino):
    fks = list(metadata.tables[tabla].c[columna].foreign_keys)
    assert len(fks) == 1
    assert fks[0].column.table.name == destino
    assert fks[0].column.name == ("codigo" if destino == "estado_orden" else "id")
    assert fks[0].ondelete is None and fks[0].onupdate is None


def test_no_hay_otras_fk(metadata):
    reales = {
        (t.name, f.parent.name)
        for t in metadata.tables.values()
        for c in t.columns
        for f in c.foreign_keys
    }
    assert reales == {(t, c) for t, c, _ in FKS}


def test_estado_en_orden_e_historial_son_texto(metadata):
    for tabla, col in (
        ("orden_trabajo", "estado"),
        ("historial_estado_orden", "desde_estado"),
        ("historial_estado_orden", "hasta_estado"),
    ):
        assert isinstance(metadata.tables[tabla].c[col].type, Text)


# --- 3.7 guarda estatica --------------------------------------------------


def test_ningun_archivo_de_la_app_usa_create_all():
    raiz = Path(__file__).resolve().parents[2]
    archivos = [*(raiz / "app").rglob("*.py"), raiz / "main.py"]
    assert len(archivos) > 5
    ofensores = [
        str(a.relative_to(raiz)) for a in archivos if "create_all" in a.read_text(encoding="utf-8")
    ]
    assert ofensores == []


# --- 4. relaciones (lazy="raise", ambos extremos) -------------------------

PARES = [
    ("Cliente", "vehiculos", "Vehiculo", "cliente"),
    ("Vehiculo", "ordenes", "OrdenTrabajo", "vehiculo"),
    ("OrdenTrabajo", "items", "ItemOrden", "orden"),
    ("ItemOrden", "repuesto", "Repuesto", "items_orden"),
    ("OrdenTrabajo", "historial", "HistorialEstadoOrden", "orden"),
    ("OrdenTrabajo", "estado_orden", "EstadoOrden", "ordenes"),
    ("OrdenTrabajo", "mecanico", "Usuario", "ordenes_asignadas"),
    ("Usuario", "asignaciones", "AsignacionRol", "usuario"),
    ("Usuario", "cliente", "Cliente", "usuario"),
    ("Repuesto", "movimientos", "MovimientoStock", "repuesto"),
    ("Repuesto", "historial_precios", "HistorialPrecioRepuesto", "repuesto"),
]


def _clases():
    import app.modules.modelos as registro

    return registro


@pytest.fixture(scope="module")
def mapeadores():
    from sqlalchemy.orm import configure_mappers

    _clases()
    configure_mappers()


@pytest.mark.parametrize(("izq", "rel_izq", "der", "rel_der"), PARES)
def test_relacion_en_ambos_extremos_con_lazy_raise(mapeadores, izq, rel_izq, der, rel_der):
    registro = _clases()
    clase_izq, clase_der = getattr(registro, izq), getattr(registro, der)
    a = getattr(clase_izq, rel_izq).property
    b = getattr(clase_der, rel_der).property
    assert a.mapper.class_ is clase_der and b.mapper.class_ is clase_izq
    assert a.back_populates == rel_der and b.back_populates == rel_izq
    assert a.lazy == "raise" and b.lazy == "raise"


def test_son_exactamente_11_pares_y_22_relaciones(mapeadores):
    registro = _clases()
    clases = [getattr(registro, n) for n in registro.__all__ if n not in ("metadata", "Rol")]
    total = sum(len(c.__mapper__.relationships) for c in clases)
    assert total == 22


def test_usuario_cliente_es_un_objeto_no_una_lista(mapeadores):
    registro = _clases()
    assert registro.Usuario.cliente.property.uselist is False
    assert registro.Cliente.vehiculos.property.uselist is True


def test_asignacion_rol_usuario_usa_usuario_id_y_no_otorgada_por(mapeadores):
    registro = _clases()
    prop = registro.AsignacionRol.usuario.property
    assert [c.name for c in prop.local_columns] == ["usuario_id"]
    inversa = registro.Usuario.asignaciones.property
    assert [c.name for c in inversa.remote_side] == ["usuario_id"]


def test_orden_mecanico_usa_mecanico_id(mapeadores):
    registro = _clases()
    assert [c.name for c in registro.OrdenTrabajo.mecanico.property.local_columns] == ["mecanico_id"]
    assert [c.name for c in registro.OrdenTrabajo.estado_orden.property.local_columns] == ["estado"]


def test_orden_transitoria_enlaza_items_en_memoria(mapeadores):
    registro = _clases()
    from decimal import Decimal

    items = [
        registro.ItemOrden(repuesto_id=1, cantidad=1, precio_unitario=Decimal("10.00")),
        registro.ItemOrden(repuesto_id=2, cantidad=3, precio_unitario=Decimal("5.50")),
    ]
    orden = registro.OrdenTrabajo(vehiculo_id=1, estado="PENDIENTE", falla="ruido", items=items)
    assert [i.orden for i in orden.items] == [orden, orden]
    assert len(orden.items) == 2


def test_back_populates_en_memoria_desde_el_lado_hijo(mapeadores):
    registro = _clases()
    cliente = registro.Cliente(nombre="Laura", documento="1", telefono="2")
    vehiculo = registro.Vehiculo(patente="AB123CD", marca="m", modelo="x", anio=2000, cliente=cliente)
    assert vehiculo in cliente.vehiculos
    assert cliente.vehiculos[0].cliente is cliente
