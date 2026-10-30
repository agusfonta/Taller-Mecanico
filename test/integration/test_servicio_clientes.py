"""Servicio de clientes y vehiculos con UoW real sobre PostgreSQL (C-07, tareas 4.x)."""
import pytest

from app.core.database import crear_fabrica_sesiones
from app.modules.clientes import service
from app.modules.clientes.schemas import ClienteEntrada, VehiculoEntrada
from app.modules.clientes.unit_of_work import ClientesUoW
from test.integration.ayudantes_clientes import (
    sembrar_catalogo,
    sembrar_cliente,
    sembrar_orden,
    sembrar_vehiculo,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def fabrica(motor_auth):
    return crear_fabrica_sesiones(motor_auth)


def uow_de(fabrica):
    """Un UoW sobre una sesion nueva (el test la cierra al terminar el uso)."""
    return fabrica()


def cliente_entrada(documento="30111222"):
    return ClienteEntrada(nombre="Ana", documento=documento, telefono="555")


def vehiculo_entrada(patente="AB123CD"):
    return VehiculoEntrada(patente=patente, marca="Fiat", modelo="Uno", anio=2020)


async def ejecutar(fabrica, funcion, *args):
    async with fabrica() as sesion:
        return await funcion(ClientesUoW(sesion), *args)


# --- crear_cliente (4.1 / 4.2) -----------------------------------------------------


async def test_crear_cliente_deja_ficha_sin_usuario(fabrica, db_auth):
    cliente = await ejecutar(fabrica, service.crear_cliente, cliente_entrada())
    assert cliente.id is not None and cliente.usuario_id is None
    filas = await db_auth.filas("SELECT usuario_id, documento FROM cliente")
    assert filas == [{"usuario_id": None, "documento": "30111222"}]
    assert await db_auth.contar("usuario") == 0


async def test_documento_repetido_lanza_error_propio_sin_filas(fabrica, db_auth):
    await sembrar_cliente(db_auth, "30111222")
    with pytest.raises(service.DocumentoRepetidoError) as info:
        await ejecutar(fabrica, service.crear_cliente, cliente_entrada())
    assert await db_auth.contar("cliente") == 1
    texto = str(info.value.mensaje)
    assert texto == "El documento ya pertenece a un cliente del taller"
    for ajeno in ("uq_", "violates", "unique"):
        assert ajeno not in texto.lower()
    assert info.value.__cause__ is None and info.value.__suppress_context__


async def test_obtener_cliente_ordena_vehiculos_y_excluye_bajas(fabrica, db_auth):
    cid = await sembrar_cliente(db_auth, "1")
    a = await sembrar_vehiculo(db_auth, cid, "AAA111")
    await sembrar_vehiculo(db_auth, cid, "BBB222", baja=True)
    b = await sembrar_vehiculo(db_auth, cid, "CCC333")
    cliente = await ejecutar(fabrica, service.obtener_cliente, cid)
    assert [v.id for v in cliente.vehiculos] == [a, b]


async def test_obtener_cliente_inexistente(fabrica):
    with pytest.raises(service.ClienteNoEncontradoError) as info:
        await ejecutar(fabrica, service.obtener_cliente, 999999)
    assert info.value.mensaje == "Cliente no encontrado"


# --- crear_vehiculo (4.3) -----------------------------------------------------------


async def test_crear_vehiculo_para_cliente_existente(fabrica, db_auth):
    cid = await sembrar_cliente(db_auth, "1")
    v = await ejecutar(fabrica, service.crear_vehiculo, cid, vehiculo_entrada())
    assert v.cliente_id == cid and v.patente == "AB123CD"
    assert (await db_auth.filas("SELECT borrado_en FROM vehiculo")) == [{"borrado_en": None}]


async def test_crear_vehiculo_cliente_inexistente_no_deja_filas(fabrica, db_auth):
    with pytest.raises(service.ClienteNoEncontradoError):
        await ejecutar(fabrica, service.crear_vehiculo, 999999, vehiculo_entrada())
    assert await db_auth.contar("vehiculo") == 0


@pytest.mark.parametrize("mismo_cliente", [True, False])
async def test_patente_vigente_repetida_lanza_409_de_dominio(fabrica, db_auth, mismo_cliente):
    c1 = await sembrar_cliente(db_auth, "1")
    c2 = await sembrar_cliente(db_auth, "2")
    await sembrar_vehiculo(db_auth, c1, "AB123CD")
    with pytest.raises(service.PatenteVigenteRepetidaError) as info:
        await ejecutar(fabrica, service.crear_vehiculo, c1 if mismo_cliente else c2, vehiculo_entrada())
    assert info.value.mensaje == "Ya hay un vehículo vigente con esa patente"
    assert await db_auth.contar("vehiculo") == 1


async def test_patente_de_vehiculo_dado_de_baja_se_puede_registrar(fabrica, db_auth):
    c1 = await sembrar_cliente(db_auth, "1")
    await sembrar_vehiculo(db_auth, c1, "AB123CD", baja=True)
    v = await ejecutar(fabrica, service.crear_vehiculo, c1, vehiculo_entrada())
    assert v.id is not None
    assert await db_auth.contar("vehiculo") == 2


# --- dar_de_baja_vehiculo (4.4) --------------------------------------------------------


async def test_baja_de_vehiculo_sin_ordenes_conserva_la_fila(fabrica, db_auth):
    await sembrar_catalogo(db_auth)
    vid = await sembrar_vehiculo(db_auth, await sembrar_cliente(db_auth, "1"), "AAA111")
    await ejecutar(fabrica, service.dar_de_baja_vehiculo, vid)
    filas = await db_auth.filas("SELECT borrado_en FROM vehiculo WHERE id = :i", i=vid)
    assert len(filas) == 1 and filas[0]["borrado_en"] is not None


@pytest.mark.parametrize("modo", ["inexistente", "ya_baja"])
async def test_baja_de_vehiculo_no_vigente_lanza_no_encontrado(fabrica, db_auth, modo):
    if modo == "inexistente":
        vid = 999999
    else:
        vid = await sembrar_vehiculo(db_auth, await sembrar_cliente(db_auth, "1"), "AAA111", baja=True)
    with pytest.raises(service.VehiculoNoEncontradoError) as info:
        await ejecutar(fabrica, service.dar_de_baja_vehiculo, vid)
    assert info.value.mensaje == "Vehículo no encontrado"


@pytest.mark.parametrize("estado", ["PENDIENTE", "EN_REPARACION"])
async def test_baja_con_orden_abierta_lanza_conflicto_y_no_modifica(fabrica, db_auth, estado):
    await sembrar_catalogo(db_auth)
    vid = await sembrar_vehiculo(db_auth, await sembrar_cliente(db_auth, "1"), "AAA111")
    await sembrar_orden(db_auth, vid, estado)
    with pytest.raises(service.VehiculoConOrdenesAbiertasError) as info:
        await ejecutar(fabrica, service.dar_de_baja_vehiculo, vid)
    assert info.value.mensaje == "El vehículo tiene órdenes abiertas"
    assert (await db_auth.filas("SELECT borrado_en FROM vehiculo"))[0]["borrado_en"] is None


async def test_baja_con_solo_ordenes_finales_procede(fabrica, db_auth):
    await sembrar_catalogo(db_auth)
    vid = await sembrar_vehiculo(db_auth, await sembrar_cliente(db_auth, "1"), "AAA111")
    await sembrar_orden(db_auth, vid, "TERMINADA")
    await sembrar_orden(db_auth, vid, "CANCELADA")
    await ejecutar(fabrica, service.dar_de_baja_vehiculo, vid)
    assert (await db_auth.filas("SELECT borrado_en FROM vehiculo"))[0]["borrado_en"] is not None
    assert await db_auth.contar("orden_trabajo") == 2


# --- listar_mis_vehiculos (4.5) -----------------------------------------------------------


async def test_listar_mis_vehiculos_devuelve_solo_los_del_usuario(fabrica, db_auth):
    u1 = await db_auth.crear_usuario("a@example.com", "x" * 10)
    u2 = await db_auth.crear_usuario("b@example.com", "x" * 10)
    c1 = await sembrar_cliente(db_auth, "1", u1)
    c2 = await sembrar_cliente(db_auth, "2", u2)
    v1 = await sembrar_vehiculo(db_auth, c1, "AAA111")
    await sembrar_vehiculo(db_auth, c1, "AAA222", baja=True)
    await sembrar_vehiculo(db_auth, c2, "BBB111")
    mios = await ejecutar(fabrica, service.listar_mis_vehiculos, u1)
    assert [v.id for v in mios] == [v1]


async def test_listar_mis_vehiculos_sin_ficha_es_vacio(fabrica, db_auth):
    uid = await db_auth.crear_usuario("c@example.com", "x" * 10, roles=("ADMIN",))
    assert list(await ejecutar(fabrica, service.listar_mis_vehiculos, uid)) == []
