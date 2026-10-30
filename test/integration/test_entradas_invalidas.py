"""Ninguna entrada invalida termina en 500 (C-12, spec entrega): barrido sobre la tabla de endpoints de la KB 06."""
import pytest

from test.integration.app_completa import app_auth, contrasenas_seed, fabrica_seed, seed_cargado, sesion_de  # noqa: F401

pytestmark = pytest.mark.integration

MAX_BIGINT = 2**63 - 1
MIN_BIGINT = -(2**63)
FUERA_DE_RANGO = [MAX_BIGINT + 1, MIN_BIGINT - 1, 10**25]
PROHIBIDO_EN_CUERPO = ("IntegrityError", "asyncpg", "Traceback", "SQL", "DBAPIError", "DataError")

VEHICULO = {"patente": "ZZZ999", "marca": "Fiat", "modelo": "Uno", "anio": 2010}
ORDEN = {"vehiculo_id": 1, "falla": "ruido", "items": [{"repuesto_id": 1, "cantidad": 1}]}
CLAVE_NUEVA = "Clave-larga-123"

# (metodo, plantilla con {id}, cuerpo valido o None): todas las rutas con un id numerico en el camino.
RUTAS_CON_ID = [
    ("GET", "/clientes/{id}", None),
    ("POST", "/clientes/{id}/vehiculos", VEHICULO),
    ("DELETE", "/vehiculos/{id}", None),
    ("GET", "/repuestos/{id}", None),
    ("PATCH", "/repuestos/{id}", {"descripcion": "nueva"}),
    ("DELETE", "/repuestos/{id}", None),
    ("POST", "/repuestos/{id}/reponer", {"cantidad": 1}),
    ("GET", "/repuestos/{id}/movimientos", None),
    ("GET", "/repuestos/{id}/precios", None),
    ("GET", "/ordenes/{id}", None),
    ("POST", "/ordenes/{id}/iniciar", None),
    ("POST", "/ordenes/{id}/terminar", None),
    ("POST", "/ordenes/{id}/cancelar", None),
    ("GET", "/usuarios/{id}/roles", None),
    ("POST", "/usuarios/{id}/roles", {"rol": "MECANICO"}),
    ("DELETE", "/usuarios/{id}/roles/MECANICO", None),
]

# (metodo, ruta, cuerpo valido): todos los endpoints con cuerpo JSON.
RUTAS_CON_CUERPO = [
    (
        "POST",
        "/auth/registro",
        {"email": "nuevo.x@example.com", "password": CLAVE_NUEVA, "nombre": "N", "documento": "1", "telefono": "1"},
    ),
    ("POST", "/auth/login", {"email": "admin@example.com", "password": "x"}),
    ("POST", "/auth/cambiar-password", {"password_actual": "x", "password_nueva": CLAVE_NUEVA}),
    ("POST", "/usuarios", {"email": "pers.x@example.com", "nombre": "P", "password": CLAVE_NUEVA, "rol": "MECANICO"}),
    ("POST", "/usuarios/1/roles", {"rol": "MECANICO"}),
    ("POST", "/clientes", {"nombre": "C", "documento": "99", "telefono": "1"}),
    ("POST", "/clientes/1/vehiculos", VEHICULO),
    ("POST", "/repuestos", {"codigo": "ZZ-1", "descripcion": "d", "precio": "10.00", "stock_inicial": 1}),
    ("PATCH", "/repuestos/1", {"descripcion": "nueva"}),
    ("POST", "/repuestos/1/reponer", {"cantidad": 1}),
    ("POST", "/ordenes", ORDEN),
]

CONTENIDOS_INVALIDOS = [b'{"a":', b"[]", b"", b"\xff\xfe"]


def _id_en_ruta(plantilla: str, valor: int) -> str:
    return plantilla.replace("{id}", str(valor))


def _verificar_sin_fuga(respuesta) -> None:
    texto = respuesta.text
    for prohibido in PROHIBIDO_EN_CUERPO:
        assert prohibido not in texto, (respuesta.status_code, prohibido)


async def _enviar(cliente, metodo: str, ruta: str, cuerpo=None, contenido: bytes | None = None):
    if contenido is not None:
        return await cliente.request(metodo, ruta, content=contenido, headers={"content-type": "application/json"})
    if cuerpo is None:
        return await cliente.request(metodo, ruta)
    return await cliente.request(metodo, ruta, json=cuerpo)


@pytest.mark.parametrize(
    ("metodo", "ruta"),
    [
        ("GET", "/ordenes/99999999999999999999"),
        ("GET", f"/clientes/{MAX_BIGINT + 1}"),
        ("DELETE", f"/vehiculos/{MIN_BIGINT - 1}"),
        ("GET", f"/repuestos/{MAX_BIGINT + 1}"),
        ("GET", f"/usuarios/{MAX_BIGINT + 1}/roles"),
    ],
)
async def test_id_fuera_de_rango_bigint_en_la_ruta_da_422_y_no_500(seed_cargado, sesion_de, metodo, ruta):
    admin = await sesion_de("admin@example.com")

    respuesta = await admin.request(metodo, ruta)

    assert respuesta.status_code == 422
    _verificar_sin_fuga(respuesta)


@pytest.mark.parametrize("valor", [MAX_BIGINT, MIN_BIGINT, 0, -1])
async def test_los_extremos_validos_del_bigint_siguen_dando_404(seed_cargado, sesion_de, valor):
    admin = await sesion_de("admin@example.com")

    for ruta in (f"/ordenes/{valor}", f"/clientes/{valor}", f"/repuestos/{valor}", f"/usuarios/{valor}/roles"):
        respuesta = await admin.get(ruta)
        assert respuesta.status_code == 404, ruta


@pytest.mark.parametrize("valor", FUERA_DE_RANGO)
@pytest.mark.parametrize(("metodo", "plantilla", "cuerpo"), RUTAS_CON_ID)
async def test_barrido_ids_de_ruta_fuera_de_rango_dan_422(seed_cargado, sesion_de, metodo, plantilla, cuerpo, valor):
    # iniciar es solo del MECANICO: con otro rol el 403 del control de acceso precede a la validacion del id
    correo = "mecanico@example.com" if plantilla.endswith("/iniciar") else "admin@example.com"
    sesion = await sesion_de(correo)

    respuesta = await _enviar(sesion, metodo, _id_en_ruta(plantilla, valor), cuerpo)

    assert respuesta.status_code == 422, (metodo, plantilla, valor)
    _verificar_sin_fuga(respuesta)


@pytest.mark.parametrize(("metodo", "ruta", "cuerpo"), RUTAS_CON_CUERPO)
async def test_barrido_campo_extra_da_422(seed_cargado, sesion_de, metodo, ruta, cuerpo):
    admin = await sesion_de("admin@example.com")

    respuesta = await _enviar(admin, metodo, ruta, {**cuerpo, "campo_inventado": 1})

    assert respuesta.status_code == 422
    _verificar_sin_fuga(respuesta)


@pytest.mark.parametrize(("metodo", "ruta", "cuerpo"), RUTAS_CON_CUERPO)
async def test_barrido_tipo_incorrecto_da_4xx_nunca_500(seed_cargado, sesion_de, metodo, ruta, cuerpo):
    admin = await sesion_de("admin@example.com")
    clave = next(iter(cuerpo))

    for malo in ({"x": 1}, [1, 2], 12345678901234567890123, None):
        respuesta = await _enviar(admin, metodo, ruta, {**cuerpo, clave: malo})
        assert 400 <= respuesta.status_code < 500, (ruta, clave, malo, respuesta.status_code)
        _verificar_sin_fuga(respuesta)


@pytest.mark.parametrize(("metodo", "ruta", "cuerpo"), RUTAS_CON_CUERPO)
async def test_barrido_json_mal_formado_o_no_objeto_da_422(seed_cargado, sesion_de, metodo, ruta, cuerpo):
    admin = await sesion_de("admin@example.com")

    for contenido in CONTENIDOS_INVALIDOS:
        respuesta = await _enviar(admin, metodo, ruta, contenido=contenido)
        assert respuesta.status_code == 422, (ruta, contenido)
        _verificar_sin_fuga(respuesta)


@pytest.mark.parametrize("valor", FUERA_DE_RANGO + [0, -1])
async def test_ids_del_cuerpo_de_la_orden_fuera_de_rango_dan_422(seed_cargado, sesion_de, valor):
    admin = await sesion_de("admin@example.com")

    en_vehiculo = await admin.post("/ordenes", json={**ORDEN, "vehiculo_id": valor})
    en_item = await admin.post("/ordenes", json={**ORDEN, "items": [{"repuesto_id": valor, "cantidad": 1}]})

    for respuesta in (en_vehiculo, en_item):
        assert respuesta.status_code == 422
        _verificar_sin_fuga(respuesta)


@pytest.mark.parametrize("pagina", [0, -1, 10**25, "x"])
async def test_paginacion_invalida_nunca_da_500(seed_cargado, sesion_de, pagina):
    admin = await sesion_de("admin@example.com")

    for ruta in ("/repuestos", "/ordenes", "/mis-ordenes", "/eventos"):
        respuesta = await admin.get(ruta, params={"page": pagina})
        assert 400 <= respuesta.status_code < 500, (ruta, pagina, respuesta.status_code)
        _verificar_sin_fuga(respuesta)
