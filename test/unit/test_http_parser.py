"""Interprete minimo de archivos ``.http`` (subconjunto de REST Client usado por ``test/c*.http``, C-12, D3)."""
import httpx
import pytest

from test.integration.http_casos import SintaxisNoSoportada, ejecutar, parsear

pytestmark = pytest.mark.unit

EJEMPLO = """\
# Caso de ejemplo
# Precondicion: python seed.py
@base = http://localhost:8000
@correo = admin@example.com

### login
# @name loginAdmin
# @prompt clave_admin Contrasena de admin
# Esperado: 200 OK
POST {{base}}/auth/login
Content-Type: application/json

{"email": "{{correo}}", "password": "{{clave_admin}}"}

### con la cookie explicita
# @no-cookie-jar
# Esperado: 403 Forbidden - {"detail": "..."}
GET {{base}}/ordenes/2 HTTP/1.1
Cookie: {{loginAdmin.response.headers.Set-Cookie}}
"""


def test_parsea_variables_pedidos_y_directivas():
    doc = parsear(EJEMPLO)

    assert doc.variables == {"base": "http://localhost:8000", "correo": "admin@example.com"}
    assert [p.metodo for p in doc.pedidos] == ["POST", "GET"]
    login, cookie = doc.pedidos
    assert login.titulo == "login"
    assert login.nombre == "loginAdmin"
    assert login.prompts == [("clave_admin", "Contrasena de admin")]
    assert login.esperado == 200
    assert login.url == "{{base}}/auth/login"
    assert login.cabeceras == [("Content-Type", "application/json")]
    assert login.cuerpo == '{"email": "{{correo}}", "password": "{{clave_admin}}"}'
    assert login.sin_jar is False
    assert cookie.sin_jar is True
    assert cookie.esperado == 403
    assert cookie.url == "{{base}}/ordenes/2"
    assert cookie.cuerpo is None


def test_los_comentarios_de_cabecera_no_son_pedidos():
    doc = parsear("# solo comentarios\n@base = http://x\n")

    assert doc.pedidos == []
    assert doc.variables == {"base": "http://x"}


def test_un_pedido_sin_esperado_queda_con_none():
    doc = parsear("### sin esperado\nGET http://x/y\n")

    assert doc.pedidos[0].esperado is None


@pytest.mark.parametrize(
    "texto",
    [
        "### x\n# Esperado: 200\nGET {{$guid}}/a\n",
        "### x\n# Esperado: 200\nGET http://x/a\nContent-Type: application/json\n\n< ./cuerpo.json\n",
        "### x\n# @note algo\n# Esperado: 200\nGET http://x/a\n",
        "### x\n# Esperado: 200\nGET http://x/a\nCookie: {{n.response.body.$.token}}\n",
        "### x\n# Esperado: 200\nTRACE http://x/a\n",
    ],
)
def test_la_sintaxis_no_soportada_falla_con_mensaje_claro(texto):
    with pytest.raises(SintaxisNoSoportada, match="no soportad"):
        parsear(texto)


async def test_ejecuta_con_cookie_jar_prompt_y_variables():
    vistos = []

    def manejador(request: httpx.Request) -> httpx.Response:
        vistos.append((request.method, str(request.url), request.headers.get("cookie"), request.content))
        if request.url.path == "/auth/login":
            return httpx.Response(200, headers={"set-cookie": "access_token=abc; HttpOnly; Path=/"})
        return httpx.Response(200 if request.headers.get("cookie") else 401)

    texto = (
        "@base = http://h\n"
        "### login\n# @prompt clave_x Clave\n# Esperado: 200\nPOST {{base}}/auth/login\n\n"
        '{"password": "{{clave_x}}"}\n'
        "### con jar\n# Esperado: 200\nGET {{base}}/yo\n"
        "### sin jar\n# @no-cookie-jar\n# Esperado: 401\nGET {{base}}/yo\n"
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(manejador)) as cliente:
        resultados = await ejecutar(parsear(texto), cliente, {"clave_x": "secreta"})

    assert [(r.codigo, r.pedido.esperado) for r in resultados] == [(200, 200), (200, 200), (401, 401)]
    assert vistos[0][3] == b'{"password": "secreta"}'
    assert vistos[1][2] == "access_token=abc"
    assert vistos[2][2] is None


async def test_dos_sesiones_con_cookie_explicita_por_nombre():
    def manejador(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login/a":
            return httpx.Response(200, headers={"set-cookie": "access_token=AAA; Path=/"})
        if request.url.path == "/login/b":
            return httpx.Response(200, headers={"set-cookie": "access_token=BBB; Path=/"})
        return httpx.Response(200, text=request.headers.get("cookie", "").split(";")[0])

    texto = (
        "@base = http://h\n"
        "### a\n# @name sesionA\n# @no-cookie-jar\n# Esperado: 200\nPOST {{base}}/login/a\n"
        "### b\n# @name sesionB\n# @no-cookie-jar\n# Esperado: 200\nPOST {{base}}/login/b\n"
        "### usa a\n# @no-cookie-jar\n# Esperado: 200\nGET {{base}}/eco\nCookie: {{sesionA.response.headers.Set-Cookie}}\n"
        "### usa b\n# @no-cookie-jar\n# Esperado: 200\nGET {{base}}/eco\nCookie: {{sesionB.response.headers.Set-Cookie}}\n"
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(manejador)) as cliente:
        resultados = await ejecutar(parsear(texto), cliente, {})

    assert [r.texto for r in resultados[2:]] == ["access_token=AAA", "access_token=BBB"]


async def test_clave_sin_valor_o_variable_desconocida_falla_con_su_nombre():
    texto = "### x\n# @prompt clave_z Clave\n# Esperado: 200\nPOST http://h/a\n\n{{clave_z}}\n"
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200))) as cliente:
        with pytest.raises(SintaxisNoSoportada, match="clave_z"):
            await ejecutar(parsear(texto), cliente, {})
        with pytest.raises(SintaxisNoSoportada, match="nada"):
            await ejecutar(parsear("### x\n# Esperado: 200\nGET http://h/{{nada}}\n"), cliente, {})


async def test_referencia_a_pedido_aun_no_ejecutado_falla_con_su_nombre():
    texto = "### x\n# Esperado: 200\nGET http://h/a\nCookie: {{todavia.response.headers.Set-Cookie}}\n"
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200))) as cliente:
        with pytest.raises(SintaxisNoSoportada, match="todavia"):
            await ejecutar(parsear(texto), cliente, {})
