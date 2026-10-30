"""Repositorios de repuestos contra PostgreSQL real (C-08, 3.3, D5/D8)."""
import pytest
from sqlalchemy.exc import IntegrityError

from app.core.database import crear_fabrica_sesiones
from app.core.errores import restriccion_violada
from app.modules.repuestos.models import Repuesto
from app.modules.repuestos.repository import RepuestoRepository
from test.integration.repuestos.ayudantes import sembrar_repuesto

pytestmark = pytest.mark.integration


@pytest.fixture
def fabrica(motor_auth):
    return crear_fabrica_sesiones(motor_auth)


async def test_sumar_stock_devuelve_el_nuevo_y_la_entidad_cargada_lo_ve(fabrica, db_auth):
    rid = await sembrar_repuesto(db_auth, stock=2)
    async with fabrica() as sesion:
        repo = RepuestoRepository(sesion)
        entidad = await repo.get_by_id(rid)
        assert entidad.stock == 2
        assert await repo.sumar_stock(rid, 5) == 7
        assert entidad.stock == 7
        await sesion.commit()
    assert (await db_auth.filas("SELECT stock FROM repuesto WHERE id = :i", i=rid))[0]["stock"] == 7


async def test_sumar_stock_negativo_valido_resta(fabrica, db_auth):
    rid = await sembrar_repuesto(db_auth, stock=5)
    async with fabrica() as sesion:
        assert await RepuestoRepository(sesion).sumar_stock(rid, -2) == 3
        await sesion.commit()


async def test_sumar_stock_de_id_inexistente_devuelve_none(fabrica):
    async with fabrica() as sesion:
        assert await RepuestoRepository(sesion).sumar_stock(999999, 5) is None


async def test_sumar_stock_que_desborda_devuelve_none_sin_data_error(fabrica, db_auth):
    rid = await sembrar_repuesto(db_auth, stock=2147483000)
    async with fabrica() as sesion:
        assert await RepuestoRepository(sesion).sumar_stock(rid, 1000) is None
        await sesion.rollback()
    assert (await db_auth.filas("SELECT stock FROM repuesto WHERE id = :i", i=rid))[0]["stock"] == 2147483000


async def test_sumar_stock_hasta_el_maximo_exacto_se_admite(fabrica, db_auth):
    rid = await sembrar_repuesto(db_auth, stock=2147483000)
    async with fabrica() as sesion:
        assert await RepuestoRepository(sesion).sumar_stock(rid, 647) == 2147483647
        await sesion.commit()


async def test_sumar_stock_que_deja_negativo_viola_el_check(fabrica, db_auth):
    rid = await sembrar_repuesto(db_auth, stock=2)
    async with fabrica() as sesion:
        with pytest.raises(IntegrityError) as info:
            await RepuestoRepository(sesion).sumar_stock(rid, -4)
        assert restriccion_violada(info.value) == "ck_repuesto_stock_no_negativo"
        await sesion.rollback()


async def test_buscar_sin_distinguir_mayusculas(fabrica, db_auth):
    await sembrar_repuesto(db_auth, codigo="A", descripcion="Pastilla de FRENO")
    await sembrar_repuesto(db_auth, codigo="B", descripcion="Filtro")
    async with fabrica() as sesion:
        repo = RepuestoRepository(sesion)
        encontrados = await repo.buscar("freno", offset=0, limit=10)
        assert [r.codigo for r in encontrados] == ["A"]
        assert await repo.contar("freno") == 1
        assert await repo.contar(None) == 2


@pytest.mark.parametrize("q", ["%", "_", "\\", "' OR '1'='1"])
async def test_buscar_trata_q_como_literal(fabrica, db_auth, q):
    await sembrar_repuesto(db_auth, codigo="A", descripcion="Pastilla de freno")
    async with fabrica() as sesion:
        repo = RepuestoRepository(sesion)
        assert list(await repo.buscar(q, offset=0, limit=10)) == []
        assert await repo.contar(q) == 0


async def test_buscar_encuentra_el_comodin_cuando_es_literal(fabrica, db_auth):
    await sembrar_repuesto(db_auth, codigo="A", descripcion="Aceite 100% sintetico")
    await sembrar_repuesto(db_auth, codigo="B", descripcion="Aceite mineral")
    async with fabrica() as sesion:
        encontrados = await RepuestoRepository(sesion).buscar("100%", offset=0, limit=10)
        assert [r.codigo for r in encontrados] == ["A"]


async def test_buscar_y_contar_excluyen_dados_de_baja_y_ordenan_por_id(fabrica, db_auth):
    await sembrar_repuesto(db_auth, codigo="A", descripcion="freno uno")
    await sembrar_repuesto(db_auth, codigo="B", descripcion="freno dos", borrado=True)
    await sembrar_repuesto(db_auth, codigo="C", descripcion="freno tres")
    async with fabrica() as sesion:
        repo = RepuestoRepository(sesion)
        assert [r.codigo for r in await repo.buscar("freno", offset=0, limit=10)] == ["A", "C"]
        assert await repo.contar("freno") == 2
        assert [r.codigo for r in await repo.buscar("freno", offset=1, limit=1)] == ["C"]


async def test_get_by_id_para_actualizar_relee_y_filtra_borrados(fabrica, db_auth):
    rid = await sembrar_repuesto(db_auth, stock=1)
    baja = await sembrar_repuesto(db_auth, codigo="Z", borrado=True)
    async with fabrica() as sesion:
        repo = RepuestoRepository(sesion)
        assert isinstance(await repo.get_by_id_para_actualizar(rid), Repuesto)
        assert await repo.get_by_id_para_actualizar(baja) is None
        await sesion.rollback()
