"""Base comun de modelos: convencion de nombres y helpers de columna (D2, D3)."""
from decimal import Decimal

import pytest
from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, Integer, MetaData, Numeric, Table, Text
from sqlalchemy.orm import registry
from sqlmodel import SQLModel

pytestmark = pytest.mark.unit

CONVENCION_ESPERADA = {
    "ix": "ix_%(column_0_N_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def test_convencion_de_nombres_en_sqlmodel_metadata():
    import app.core.models  # noqa: F401

    convencion = SQLModel.metadata.naming_convention
    for clave, patron in CONVENCION_ESPERADA.items():
        assert convencion[clave] == patron


def test_convencion_genera_nombres_deterministas_en_la_metadata_de_la_app():
    import app.core.models  # noqa: F401

    tabla = Table(
        "c03_tabla_convencion",
        SQLModel.metadata,
        Column("id", Integer, primary_key=True),
        Column("anio", Integer),
        CheckConstraint("anio > 0", name="anio_positivo"),
    )
    try:
        nombres = {c.name for c in tabla.constraints}
        assert "ck_c03_tabla_convencion_anio_positivo" in nombres
        assert "pk_c03_tabla_convencion" in nombres
    finally:
        SQLModel.metadata.remove(tabla)


def test_convencion_no_afecta_metadata_ajena():
    import app.core.models  # noqa: F401

    ajena = registry().metadata
    assert ajena is not SQLModel.metadata
    assert ajena.naming_convention != SQLModel.metadata.naming_convention
    tabla = Table("ajena", ajena, Column("n", Integer), CheckConstraint("n > 0", name="x"))
    assert "x" in {c.name for c in tabla.constraints}
    assert isinstance(ajena, MetaData)


def test_dinero_es_numeric_decimal():
    from app.core.models import dinero

    columna = dinero(10, 2).sa_column
    assert isinstance(columna.type, Numeric)
    assert (columna.type.precision, columna.type.scale) == (10, 2)
    assert columna.type.asdecimal is True
    assert columna.type.python_type is Decimal
    assert columna.nullable is False


def test_dinero_respeta_otra_precision():
    from app.core.models import dinero

    columna = dinero(12, 2).sa_column
    assert (columna.type.precision, columna.type.scale) == (12, 2)


def test_fecha_es_timestamptz():
    from app.core.models import fecha

    columna = fecha().sa_column
    assert isinstance(columna.type, DateTime)
    assert columna.type.timezone is True
    assert columna.nullable is False
    assert columna.server_default is None


def test_fecha_nula_y_con_default_de_servidor():
    from app.core.models import fecha

    assert fecha(nullable=True).sa_column.nullable is True
    con_default = fecha(server_default_now=True).sa_column
    assert con_default.server_default is not None
    assert "now()" in str(con_default.server_default.arg)


def test_texto_es_text_y_no_autostring():
    from sqlmodel import AutoString

    from app.core.models import texto

    columna = texto().sa_column
    assert isinstance(columna.type, Text)
    assert not isinstance(columna.type, AutoString)
    assert columna.nullable is False
    assert texto(nullable=True).sa_column.nullable is True


def test_pk_identidad_es_bigint_identity_by_default():
    from app.core.models import pk_identidad

    columna = pk_identidad().sa_column
    assert isinstance(columna.type, BigInteger)
    assert columna.primary_key is True
    assert columna.identity is not None and columna.identity.always is False


def test_fk_apunta_a_la_columna_y_admite_nulo():
    from app.core.models import fk

    obligatoria = fk("usuario.id").sa_column
    opcional = fk("usuario.id", nullable=True).sa_column
    assert isinstance(obligatoria.type, BigInteger)
    assert obligatoria.nullable is False
    assert opcional.nullable is True
    assert next(iter(obligatoria.foreign_keys)).target_fullname == "usuario.id"


def test_fk_a_codigo_de_catalogo_es_texto():
    from app.core.models import fk

    columna = fk("estado_orden.codigo", tipo=Text).sa_column
    assert isinstance(columna.type, Text)


def test_helpers_devuelven_columnas_nuevas_cada_vez():
    from app.core.models import dinero, fecha, pk_identidad, texto

    for helper in (pk_identidad, fecha, texto, lambda: dinero(10, 2)):
        assert helper().sa_column is not helper().sa_column


def test_fk_con_indice_propio_solo_si_se_pide():
    from app.core.models import fk

    assert not fk("usuario.id").sa_column.index
    assert fk("usuario.id", index=True).sa_column.index is True


def test_entero_y_booleano_son_obligatorios_con_defaults_de_servidor():
    from sqlalchemy import Boolean

    from app.core.models import booleano, entero

    stock = entero(server_default="0", default=0)
    assert isinstance(stock.sa_column.type, Integer)
    assert stock.sa_column.nullable is False
    assert str(stock.sa_column.server_default.arg) == "0"
    assert stock.default == 0

    activo = booleano(server_default="true", default=True)
    assert isinstance(activo.sa_column.type, Boolean)
    assert activo.default is True
    assert entero().sa_column.server_default is None


def test_dinero_con_cero_por_defecto():
    from app.core.models import dinero

    total = dinero(12, 2, cero_por_defecto=True)
    assert total.default == Decimal("0")
    assert str(total.sa_column.server_default.arg) == "0"
