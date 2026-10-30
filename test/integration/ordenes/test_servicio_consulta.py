"""Servicios de consulta de ordenes con UoW real sobre PostgreSQL (C-09, tareas 5.1 a 5.3)."""
import pytest

from app.core.dependencies import UsuarioActual
from app.core.paginacion import PaginaFueraDeRangoError, ParametrosPaginacion
from app.modules.ordenes import service
from app.modules.ordenes.models import EstadoOrdenCodigo
from app.modules.ordenes.unit_of_work import OrdenesUoW
from app.modules.usuarios.models import Rol
from test.integration.ordenes.ayudantes import (
    sembrar_catalogo,
    sembrar_cliente,
    sembrar_orden_completa,
    sembrar_repuesto,
    sembrar_vehiculo,
)

pytestmark = pytest.mark.integration


def actual(uid: int, *roles: Rol) -> UsuarioActual:
    return UsuarioActual(
        id=uid,
        email=f"u{uid}@example.com",
        nombre="U",
        debe_cambiar_password=False,
        roles_vigentes=frozenset(roles),
        roles_token=tuple(r.value for r in roles),
    )


@pytest.fixture
async def mundo(db_auth):
    """Dos clientes con ficha de usuario, dos mecanicos y ordenes variadas."""
    await sembrar_catalogo(db_auth)
    ids = {}
    for nombre in ("m1", "m2", "dueno", "otro", "admin", "recep"):
        ids[nombre] = await db_auth.crear_usuario(f"{nombre}@example.com", "x" * 10)
    c1 = await sembrar_cliente(db_auth, "1", usuario_id=ids["dueno"])
    c2 = await sembrar_cliente(db_auth, "2", usuario_id=ids["otro"])
    v1 = await sembrar_vehiculo(db_auth, c1, "AAA111")
    v1b = await sembrar_vehiculo(db_auth, c1, "AAA222", baja=True)
    v2 = await sembrar_vehiculo(db_auth, c2, "BBB111")
    r_b = await sembrar_repuesto(db_auth, codigo="B")
    r_a = await sembrar_repuesto(db_auth, codigo="A")
    ids.update(
        v1=v1,
        o_sin=await sembrar_orden_completa(db_auth, v1, "PENDIENTE", items=((r_b, 1, "10.00"), (r_a, 2, "5.00"))),
        o_m1=await sembrar_orden_completa(db_auth, v1b, "EN_REPARACION", mecanico_id=ids["m1"]),
        o_m2=await sembrar_orden_completa(db_auth, v2, "EN_REPARACION", mecanico_id=ids["m2"]),
        o_fin=await sembrar_orden_completa(db_auth, v2, "TERMINADA", mecanico_id=ids["m1"]),
        r_a=r_a,
        r_b=r_b,
    )
    # historial sembrado fuera de orden de insercion logica para comprobar el orden por id
    for desde, hasta in ((None, "PENDIENTE"), ("PENDIENTE", "EN_REPARACION")):
        await db_auth.ejecutar(
            "INSERT INTO historial_estado_orden (orden_id, desde_estado, hasta_estado, usuario_id) "
            "VALUES (:o, :d, :h, :u)",
            o=ids["o_sin"], d=desde, h=hasta, u=ids["recep"],
        )
    return ids


PAGINA = ParametrosPaginacion(page=1, size=20)


async def ejecutar(fabrica, funcion, *args):
    async with fabrica() as sesion:
        return await funcion(OrdenesUoW(sesion), *args)


# --- obtener_orden (5.1) -----------------------------------------------------------


@pytest.mark.parametrize("rol", [Rol.ADMIN, Rol.RECEPCION, Rol.MECANICO])
async def test_el_personal_ve_cualquier_orden_incluso_un_mecanico_no_asignado(fabrica, mundo, rol):
    # m2 no esta asignado a o_m1 ni a o_sin
    usuario = actual(mundo["m2"] if rol is Rol.MECANICO else mundo["admin"], rol)
    for clave in ("o_m1", "o_sin", "o_fin"):
        detalle = await ejecutar(fabrica, service.obtener_orden, mundo[clave], usuario)
        assert detalle.id == mundo[clave]


async def test_el_dueno_ve_su_orden_aunque_el_vehiculo_este_dado_de_baja(fabrica, mundo):
    dueno = actual(mundo["dueno"], Rol.CLIENTE)
    assert (await ejecutar(fabrica, service.obtener_orden, mundo["o_sin"], dueno)).id == mundo["o_sin"]
    assert (await ejecutar(fabrica, service.obtener_orden, mundo["o_m1"], dueno)).id == mundo["o_m1"]


async def test_otro_cliente_recibe_orden_ajena(fabrica, mundo):
    ajeno = actual(mundo["otro"], Rol.CLIENTE)
    with pytest.raises(service.OrdenAjenaError):
        await ejecutar(fabrica, service.obtener_orden, mundo["o_sin"], ajeno)
    # y un usuario sin ficha ni rol de personal tambien
    with pytest.raises(service.OrdenAjenaError):
        await ejecutar(fabrica, service.obtener_orden, mundo["o_sin"], actual(mundo["admin"], Rol.CLIENTE))


async def test_orden_inexistente_es_404_antes_que_el_permiso(fabrica, mundo):
    for usuario in (actual(mundo["otro"], Rol.CLIENTE), actual(mundo["admin"], Rol.ADMIN)):
        with pytest.raises(service.OrdenNoEncontradaError) as info:
            await ejecutar(fabrica, service.obtener_orden, 999999, usuario)
        assert info.value.mensaje == "Orden no encontrada"


async def test_items_ordenados_por_repuesto_id_e_historial_por_id(fabrica, mundo):
    detalle = await ejecutar(fabrica, service.obtener_orden, mundo["o_sin"], actual(mundo["admin"], Rol.ADMIN))
    assert [i.repuesto_id for i in detalle.items] == sorted([mundo["r_a"], mundo["r_b"]])
    assert [h.hasta_estado for h in detalle.historial] == ["PENDIENTE", "EN_REPARACION"]
    assert [h.id for h in detalle.historial] == sorted(h.id for h in detalle.historial)


# --- listar_ordenes (5.2) ------------------------------------------------------------


async def listar(fabrica, usuario, estado=None, params=PAGINA):
    items, total = await ejecutar(fabrica, service.listar_ordenes, estado, usuario, params)
    return [o.id for o in items], total


@pytest.mark.parametrize("rol", [Rol.ADMIN, Rol.RECEPCION])
async def test_admin_y_recepcion_ven_todas(fabrica, mundo, rol):
    ids, total = await listar(fabrica, actual(mundo["admin"], rol))
    assert ids == [mundo[k] for k in ("o_sin", "o_m1", "o_m2", "o_fin")] and total == 4


async def test_solo_mecanico_ve_suyas_y_sin_asignar(fabrica, mundo):
    assert await listar(fabrica, actual(mundo["m1"], Rol.MECANICO)) == (
        [mundo["o_sin"], mundo["o_m1"], mundo["o_fin"]], 3,
    )
    assert await listar(fabrica, actual(mundo["m2"], Rol.MECANICO)) == ([mundo["o_sin"], mundo["o_m2"]], 2)


async def test_mecanico_y_admin_a_la_vez_ve_todas(fabrica, mundo):
    ids, total = await listar(fabrica, actual(mundo["m2"], Rol.MECANICO, Rol.ADMIN))
    assert total == 4 and len(ids) == 4


async def test_filtro_por_estado_y_total_filtrado(fabrica, mundo):
    admin = actual(mundo["admin"], Rol.ADMIN)
    assert await listar(fabrica, admin, EstadoOrdenCodigo.EN_REPARACION) == ([mundo["o_m1"], mundo["o_m2"]], 2)
    assert await listar(fabrica, actual(mundo["m1"], Rol.MECANICO), EstadoOrdenCodigo.EN_REPARACION) == (
        [mundo["o_m1"]], 1,
    )
    assert await listar(fabrica, admin, EstadoOrdenCodigo.CANCELADA) == ([], 0)


async def test_pagina_fuera_de_rango_usa_el_total_filtrado(fabrica, mundo):
    admin = actual(mundo["admin"], Rol.ADMIN)
    # 4 ordenes en total (2 paginas de 2), pero con el filtro solo hay 2 (1 pagina)
    assert await listar(fabrica, admin, None, ParametrosPaginacion(page=2, size=2)) == (
        [mundo["o_m2"], mundo["o_fin"]], 4,
    )
    with pytest.raises(PaginaFueraDeRangoError):
        await listar(fabrica, admin, EstadoOrdenCodigo.EN_REPARACION, ParametrosPaginacion(page=2, size=2))
    with pytest.raises(PaginaFueraDeRangoError):
        await listar(fabrica, admin, None, ParametrosPaginacion(page=3, size=2))


# --- listar_mis_ordenes y listar_estados (5.3) -------------------------------------------


async def test_mis_ordenes_incluye_vehiculos_dados_de_baja_y_solo_las_propias(fabrica, mundo):
    items, total = await ejecutar(fabrica, service.listar_mis_ordenes, mundo["dueno"], PAGINA)
    assert [o.id for o in items] == [mundo["o_sin"], mundo["o_m1"]] and total == 2
    items, total = await ejecutar(fabrica, service.listar_mis_ordenes, mundo["otro"], PAGINA)
    assert [o.id for o in items] == [mundo["o_m2"], mundo["o_fin"]] and total == 2


async def test_mis_ordenes_sin_ficha_es_pagina_vacia_y_fuera_de_rango_falla(fabrica, mundo):
    assert await ejecutar(fabrica, service.listar_mis_ordenes, mundo["admin"], PAGINA) == ([], 0)
    with pytest.raises(PaginaFueraDeRangoError):
        await ejecutar(fabrica, service.listar_mis_ordenes, mundo["dueno"], ParametrosPaginacion(page=2, size=2))


async def test_listar_estados_va_por_posicion_y_vacio_si_no_hay_catalogo(fabrica, db_auth, mundo):
    estados = await ejecutar(fabrica, service.listar_estados)
    assert [e.codigo for e in estados] == ["PENDIENTE", "EN_REPARACION", "TERMINADA", "CANCELADA"]
    await db_auth.ejecutar("TRUNCATE orden_trabajo, item_orden, historial_estado_orden CASCADE")
    await db_auth.ejecutar("DELETE FROM estado_orden")
    assert list(await ejecutar(fabrica, service.listar_estados)) == []
