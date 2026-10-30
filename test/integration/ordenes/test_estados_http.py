"""GET /estados-orden por HTTP contra PostgreSQL real (C-09, tarea 6.5, spec estados-orden)."""
import pytest

from test.integration.ordenes.ayudantes import sembrar_catalogo

pytestmark = pytest.mark.integration


async def test_cuatro_estados_por_posicion_con_es_final_para_un_cliente_caso_c17(http, db_auth, usuario_con_rol):
    await sembrar_catalogo(
        db_auth,
        (("CANCELADA", 4, True), ("PENDIENTE", 1, False), ("TERMINADA", 3, True), ("EN_REPARACION", 2, False)),
    )
    _, cab = await usuario_con_rol("CLIENTE")
    r = await http.get("/estados-orden", headers=cab)
    assert r.status_code == 200
    assert [(e["codigo"], e["posicion"], e["es_final"]) for e in r.json()] == [
        ("PENDIENTE", 1, False),
        ("EN_REPARACION", 2, False),
        ("TERMINADA", 3, True),
        ("CANCELADA", 4, True),
    ]
    assert set(r.json()[0]) == {"codigo", "descripcion", "posicion", "es_final"}


async def test_catalogo_vacio_responde_lista_vacia(http, usuario_con_rol):
    _, cab = await usuario_con_rol("MECANICO")
    r = await http.get("/estados-orden", headers=cab)
    assert r.status_code == 200 and r.json() == []


async def test_sin_sesion_es_401_y_cambio_pendiente_es_403(http, usuario_con_rol):
    assert (await http.get("/estados-orden")).status_code == 401
    _, cab = await usuario_con_rol("CLIENTE", debe_cambiar_password=True)
    assert (await http.get("/estados-orden", headers=cab)).status_code == 403


@pytest.mark.parametrize("metodo", ["post", "put", "patch", "delete"])
async def test_el_catalogo_no_se_edita_desde_la_api(http, db_auth, usuario_con_rol, metodo):
    await sembrar_catalogo(db_auth)
    _, cab = await usuario_con_rol("ADMIN")
    antes = await db_auth.filas("SELECT * FROM estado_orden ORDER BY codigo")
    r = await http.request(metodo.upper(), "/estados-orden", json={"codigo": "NUEVO"}, headers=cab)
    assert r.status_code == 405
    assert await db_auth.filas("SELECT * FROM estado_orden ORDER BY codigo") == antes
