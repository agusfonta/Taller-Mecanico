"""Catalogo de repuestos por HTTP contra PostgreSQL real (C-08, 6.1-6.4, spec catalogo-repuestos)."""
import pytest

from test.integration.repuestos.ayudantes import (
    fila_de,
    movimientos_de,
    sembrar_repuesto,
)

pytestmark = pytest.mark.integration

ALTA = {"codigo": " fil-001 ", "descripcion": "Filtro de aceite", "precio": 8000, "stock_inicial": 10}


# --- 6.1 Permisos -------------------------------------------------------------------------


@pytest.mark.parametrize("rol", ["ADMIN", "RECEPCION", "MECANICO"])
async def test_el_personal_consulta_el_catalogo(http, db_auth, usuario_con_rol, rol):
    rid = await sembrar_repuesto(db_auth)
    _, cab = await usuario_con_rol(rol)
    assert (await http.get("/repuestos", headers=cab)).status_code == 200
    assert (await http.get(f"/repuestos/{rid}", headers=cab)).status_code == 200


async def test_cliente_no_consulta_el_catalogo(http, db_auth, usuario_con_rol):
    rid = await sembrar_repuesto(db_auth)
    _, cab = await usuario_con_rol("CLIENTE")
    assert (await http.get("/repuestos", headers=cab)).status_code == 403
    assert (await http.get(f"/repuestos/{rid}", headers=cab)).status_code == 403


async def test_sin_sesion_es_401(http):
    assert (await http.get("/repuestos")).status_code == 401
    assert (await http.get("/repuestos/1")).status_code == 401
    assert (await http.post("/repuestos", json=ALTA)).status_code == 401


async def test_mecanico_no_da_de_alta_y_no_quedan_filas(http, db_auth, usuario_con_rol):
    _, cab = await usuario_con_rol("MECANICO")
    r = await http.post("/repuestos", json={**ALTA, "codigo": "NUEVO"}, headers=cab)
    assert r.status_code == 403
    assert await db_auth.contar("repuesto") == 0
    assert await db_auth.contar("movimiento_stock") == 0


async def test_recepcion_en_patch_inexistente_es_403_antes_que_404(http, usuario_con_rol):
    _, cab = await usuario_con_rol("RECEPCION")
    r = await http.patch("/repuestos/999999", json={"descripcion": "x"}, headers=cab)
    assert r.status_code == 403


async def test_mecanico_patch_de_stock_es_403_antes_que_422(http, db_auth, usuario_con_rol):
    rid = await sembrar_repuesto(db_auth, stock=3)
    _, cab = await usuario_con_rol("MECANICO")
    r = await http.patch(f"/repuestos/{rid}", json={"stock": 999}, headers=cab)
    assert r.status_code == 403
    assert (await fila_de(db_auth, rid))["stock"] == 3


@pytest.mark.parametrize(
    ("metodo", "ruta", "cuerpo"),
    [
        ("POST", "/repuestos", ALTA),
        ("PATCH", "/repuestos/1", {"descripcion": "x"}),
        ("DELETE", "/repuestos/1", None),
        ("POST", "/repuestos/1/reponer", {"cantidad": 1}),
        ("GET", "/repuestos/1/movimientos", None),
        ("GET", "/repuestos/1/precios", None),
    ],
)
@pytest.mark.parametrize("rol", ["RECEPCION", "MECANICO", "CLIENTE"])
async def test_las_rutas_de_administracion_son_solo_admin(
    http, usuario_con_rol, metodo, ruta, cuerpo, rol
):
    _, cab = await usuario_con_rol(rol)
    r = await http.request(metodo, ruta, json=cuerpo, headers=cab)
    assert r.status_code == 403


async def test_cambio_de_password_pendiente_es_403_en_todo(http, db_auth, cookie_de):
    uid = await db_auth.crear_usuario(
        "pend@example.com", "x" * 10, roles=("ADMIN",), debe_cambiar_password=True
    )
    r = await http.get("/repuestos", headers=cookie_de(uid, ("ADMIN",)))
    assert r.status_code == 403
    r = await http.post("/repuestos", json=ALTA, headers=cookie_de(uid, ("ADMIN",)))
    assert r.status_code == 403


# --- 6.2 Alta -----------------------------------------------------------------------------


async def test_alta_con_stock_inicial_deja_un_movimiento_del_admin(http, db_auth, admin, admin_id):
    r = await http.post("/repuestos", json=ALTA, headers=admin)
    assert r.status_code == 201
    cuerpo = r.json()
    assert cuerpo["codigo"] == "FIL-001"
    assert cuerpo["descripcion"] == "Filtro de aceite"
    assert cuerpo["precio"] == "8000.00"
    assert cuerpo["stock"] == 10
    assert set(cuerpo) == {"id", "codigo", "descripcion", "precio", "stock"}
    movs = await movimientos_de(db_auth, cuerpo["id"])
    assert [(m["cantidad"], m["motivo"], m["usuario_id"], m["orden_id"]) for m in movs] == [
        (10, "Stock inicial", admin_id, None)
    ]


async def test_alta_acepta_precio_numerico_o_cadena(http, admin):
    a = await http.post("/repuestos", json={**ALTA, "codigo": "A", "precio": 8500.5}, headers=admin)
    b = await http.post("/repuestos", json={**ALTA, "codigo": "B", "precio": "1200"}, headers=admin)
    assert (a.status_code, a.json()["precio"]) == (201, "8500.50")
    assert (b.status_code, b.json()["precio"]) == (201, "1200.00")


@pytest.mark.parametrize("precio", [10.005, 0, -1, 100000000, True, None, "abc", "NaN"])
async def test_alta_con_precio_invalido_es_422_sin_filas(http, db_auth, admin, precio):
    r = await http.post("/repuestos", json={**ALTA, "precio": precio}, headers=admin)
    assert r.status_code == 422
    assert await db_auth.contar("repuesto") == 0


async def test_alta_con_codigo_vigente_repetido_es_409_propio_sin_filas_nuevas(http, db_auth, admin):
    assert (await http.post("/repuestos", json=ALTA, headers=admin)).status_code == 201
    r = await http.post("/repuestos", json={**ALTA, "codigo": "fil-001", "stock_inicial": 4}, headers=admin)
    assert r.status_code == 409
    texto = r.text.lower()
    for ajeno in ("uq_repuesto", "duplicate", "violates", "constraint", "insert"):
        assert ajeno not in texto
    assert await db_auth.contar("repuesto") == 1
    assert await db_auth.contar("movimiento_stock") == 1


async def test_alta_con_el_codigo_de_un_repuesto_dado_de_baja_es_201(http, db_auth, admin):
    await sembrar_repuesto(db_auth, codigo="FIL-001", borrado=True)
    r = await http.post("/repuestos", json=ALTA, headers=admin)
    assert r.status_code == 201


@pytest.mark.parametrize("stock_inicial", [None, 0])
async def test_alta_sin_stock_inicial_o_en_cero_no_deja_movimientos(http, db_auth, admin, stock_inicial):
    cuerpo = {k: v for k, v in ALTA.items() if k != "stock_inicial"}
    if stock_inicial is not None:
        cuerpo["stock_inicial"] = stock_inicial
    r = await http.post("/repuestos", json=cuerpo, headers=admin)
    assert r.status_code == 201 and r.json()["stock"] == 0
    assert await db_auth.contar("movimiento_stock") == 0


@pytest.mark.parametrize(
    "cambio",
    [
        {"stock": 5},
        {"id": 3},
        {"descripcion": "   "},
        {"stock_inicial": -1},
        {"stock_inicial": "5"},
        {"stock_inicial": 1.5},
        {"codigo": "x" * 51},
    ],
)
async def test_alta_invalida_es_422_sin_filas(http, db_auth, admin, cambio):
    r = await http.post("/repuestos", json={**ALTA, **cambio}, headers=admin)
    assert r.status_code == 422
    assert await db_auth.contar("repuesto") == 0


# --- 6.3 Consulta y busqueda ----------------------------------------------------------------


async def test_detalle_200_y_404_para_inexistente_y_dado_de_baja(http, db_auth, admin):
    vigente = await sembrar_repuesto(db_auth, codigo="A", precio="8500.5")
    baja = await sembrar_repuesto(db_auth, codigo="B", borrado=True)
    r = await http.get(f"/repuestos/{vigente}", headers=admin)
    assert r.status_code == 200
    assert r.json() == {
        "id": vigente,
        "codigo": "A",
        "descripcion": "Filtro de aceite",
        "precio": "8500.50",
        "stock": 0,
    }
    assert (await http.get(f"/repuestos/{baja}", headers=admin)).status_code == 404
    assert (await http.get("/repuestos/999999", headers=admin)).status_code == 404


async def test_busqueda_con_intento_de_inyeccion_no_encuentra_nada(http, db_auth, admin):
    await sembrar_repuesto(db_auth)
    r = await http.get("/repuestos", params={"q": "' OR '1'='1"}, headers=admin)
    assert r.status_code == 200
    assert (r.json()["items"], r.json()["total"]) == ([], 0)


async def test_busqueda_con_filtro_y_paginacion(http, db_auth, admin):
    await sembrar_repuesto(db_auth, codigo="A", descripcion="Pastilla de freno")
    await sembrar_repuesto(db_auth, codigo="B", descripcion="Filtro")
    r = await http.get("/repuestos", params={"q": "FRENO", "size": 1}, headers=admin)
    assert r.status_code == 200
    cuerpo = r.json()
    assert (cuerpo["total"], cuerpo["pages"], cuerpo["page"], cuerpo["size"]) == (1, 1, 1, 1)
    assert [i["codigo"] for i in cuerpo["items"]] == ["A"]
    r = await http.get("/repuestos", params={"q": "freno", "size": 1, "page": 2}, headers=admin)
    assert r.status_code == 422


async def test_comodin_literal_no_encuentra_nada(http, db_auth, admin):
    await sembrar_repuesto(db_auth)
    r = await http.get("/repuestos", params={"q": "%"}, headers=admin)
    assert (r.status_code, r.json()["total"]) == (200, 0)
    r = await http.get("/repuestos", params={"q": "_"}, headers=admin)
    assert (r.status_code, r.json()["total"]) == (200, 0)


@pytest.mark.parametrize("params", [{"size": 500}, {"size": 0}, {"page": 0}, {"q": "   "}, {"q": ""}, {"q": "x" * 101}])
async def test_parametros_invalidos_son_422(http, admin, params):
    assert (await http.get("/repuestos", params=params, headers=admin)).status_code == 422


async def test_q_se_recorta_antes_de_buscar(http, db_auth, admin):
    await sembrar_repuesto(db_auth, descripcion="Pastilla de freno")
    r = await http.get("/repuestos", params={"q": "  freno  "}, headers=admin)
    assert r.json()["total"] == 1


async def test_listado_excluye_dados_de_baja_ordena_por_id_y_pagina(http, db_auth, admin):
    ids = [
        await sembrar_repuesto(db_auth, codigo="A"),
        await sembrar_repuesto(db_auth, codigo="B", borrado=True),
        await sembrar_repuesto(db_auth, codigo="C"),
        await sembrar_repuesto(db_auth, codigo="D"),
    ]
    r = await http.get("/repuestos", headers=admin)
    cuerpo = r.json()
    assert [i["id"] for i in cuerpo["items"]] == [ids[0], ids[2], ids[3]]
    assert cuerpo["total"] == 3
    r = await http.get("/repuestos", params={"size": 2, "page": 2}, headers=admin)
    assert [i["id"] for i in r.json()["items"]] == [ids[3]]
    assert r.json()["pages"] == 2


async def test_listado_vacio_tiene_una_pagina(http, admin):
    cuerpo = (await http.get("/repuestos", headers=admin)).json()
    assert (cuerpo["items"], cuerpo["total"], cuerpo["pages"]) == ([], 0, 1)


# --- 6.4 Baja -------------------------------------------------------------------------------


async def test_baja_es_204_sin_cuerpo_y_conserva_filas_y_movimientos(http, db_auth, admin):
    rid = (await http.post("/repuestos", json=ALTA, headers=admin)).json()["id"]
    r = await http.delete(f"/repuestos/{rid}", headers=admin)
    assert r.status_code == 204 and r.content == b""
    fila = await fila_de(db_auth, rid)
    assert fila["borrado_en"] is not None
    assert len(await movimientos_de(db_auth, rid)) == 1
    assert (await http.get(f"/repuestos/{rid}", headers=admin)).status_code == 404


async def test_baja_repetida_o_de_inexistente_es_404(http, db_auth, admin):
    rid = await sembrar_repuesto(db_auth)
    assert (await http.delete(f"/repuestos/{rid}", headers=admin)).status_code == 204
    assert (await http.delete(f"/repuestos/{rid}", headers=admin)).status_code == 404
    assert (await http.delete("/repuestos/999999", headers=admin)).status_code == 404


async def test_tras_la_baja_el_codigo_queda_disponible(http, db_auth, admin):
    rid = (await http.post("/repuestos", json=ALTA, headers=admin)).json()["id"]
    await http.delete(f"/repuestos/{rid}", headers=admin)
    assert (await http.post("/repuestos", json=ALTA, headers=admin)).status_code == 201


async def test_baja_con_stock_positivo_se_permite(http, db_auth, admin):
    rid = await sembrar_repuesto(db_auth, stock=5)
    assert (await http.delete(f"/repuestos/{rid}", headers=admin)).status_code == 204
