"""POST /auth/login y /auth/logout contra PostgreSQL real (C-05, tareas 8.1 a 8.8)."""
import secrets

import pytest

pytestmark = pytest.mark.integration

EMAIL = "ana@example.com"
IP = "203.0.113.5"


@pytest.fixture
def clave() -> str:
    return "pw-" + secrets.token_urlsafe(12)


@pytest.fixture
async def ana(db_auth, clave) -> int:
    return await db_auth.crear_usuario(EMAIL, clave)


def login(email, password):
    return {"email": email, "password": password}


# --- 8.1 login correcto -----------------------------------------------------------------


async def test_login_correcto_200_con_cuerpo_exacto_y_cookie(http, ana, clave):
    r = await http.post("/auth/login", json=login(EMAIL, clave))
    assert r.status_code == 200
    assert r.json() == {"mensaje": "Sesión iniciada", "debe_cambiar_password": False, "expira_en_segundos": 1800}
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("access_token=")
    for atributo in ("HttpOnly", "SameSite=lax", "Path=/", "Max-Age=1800"):
        assert atributo in cookie
    assert "Secure" not in cookie
    token = cookie.split(";")[0].split("=", 1)[1]
    assert token and token not in r.text


async def test_login_correcto_la_cookie_abre_sesion_en_una_ruta_autenticada(http, ana, clave):
    await http.post("/auth/login", json=login(EMAIL, clave))
    r = await http.get("/prueba/autenticada")
    assert (r.status_code, r.json()) == (200, {"id": ana})


async def test_login_con_cambio_pendiente_200_y_lo_informa(http, db_auth, clave):
    await db_auth.crear_usuario("nuevo@example.com", clave, debe_cambiar_password=True)
    r = await http.post("/auth/login", json=login("nuevo@example.com", clave))
    assert r.status_code == 200
    assert r.json()["debe_cambiar_password"] is True
    assert "access_token=" in r.headers["set-cookie"]


@pytest.mark.parametrize("escrito", ["ANA@example.com", "  Ana@Example.COM  "])
async def test_login_con_correo_en_mayusculas_o_con_espacios_200(http, ana, clave, escrito):
    r = await http.post("/auth/login", json=login(escrito, clave))
    assert r.status_code == 200


async def test_login_correcto_anota_un_intento_exitoso_confirmado(http, ana, clave, db_auth):
    await http.post("/auth/login", json=login("ANA@example.com", clave))
    (fila,) = await db_auth.filas("SELECT email, ip, exito FROM intento_acceso")
    assert fila == {"email": EMAIL, "ip": IP, "exito": True}


async def test_token_de_la_cookie_trae_los_roles_vigentes_y_iat_fraccional(http, db_auth, clave, settings_auth):
    from app.core.security import decodificar_token

    uid = await db_auth.crear_usuario("adm@example.com", clave, roles=["ADMIN", "RECEPCION"])
    r = await http.post("/auth/login", json=login("adm@example.com", clave))
    claims = decodificar_token(http.cookies["access_token"], settings_auth)
    assert claims.sub == uid
    assert claims.roles == ("ADMIN", "RECEPCION")
    assert claims.exp == claims.iat + 1800
    assert r.status_code == 200


# --- 8.3 anti-enumeración -----------------------------------------------------------------

CUERPO_401 = {"detail": "Correo o contraseña incorrectos"}


@pytest.fixture
def espias(app_auth, monkeypatch):
    """Cuenta llamadas a ``verificar`` / ``hashear`` del servicio de contrasenas de la app."""
    servicio = app_auth.state.contrasenas
    estado = {"verificar": [], "hashear": []}
    real_v, real_h = servicio.verificar, servicio.hashear

    async def verificar(password, hash_):
        estado["verificar"].append(hash_)
        return await real_v(password, hash_)

    async def hashear(password):
        estado["hashear"].append(password)
        return await real_h(password)

    monkeypatch.setattr(servicio, "verificar", verificar)
    monkeypatch.setattr(servicio, "hashear", hashear)
    return estado


async def test_tres_fallos_distintos_dan_el_mismo_401_sin_cookie(http, db_auth, clave, ana, espias, app_auth):
    await db_auth.crear_usuario("off@example.com", clave, activo=False)
    respuestas = [
        await http.post("/auth/login", json=login(EMAIL, "clave-equivocada")),  # existe, clave mala
        await http.post("/auth/login", json=login("fantasma@example.com", clave)),  # no existe
        await http.post("/auth/login", json=login("off@example.com", clave)),  # inactivo, clave correcta
    ]
    for r in respuestas:
        assert r.status_code == 401
        assert r.json() == CUERPO_401
        assert "set-cookie" not in r.headers
    assert {r.headers["content-type"] for r in respuestas} == {"application/json"}
    assert len({r.content for r in respuestas}) == 1  # cuerpos byte a byte identicos


async def test_exactamente_una_verificacion_por_intento_y_ninguna_generacion_de_hash(
    http, db_auth, clave, ana, espias, app_auth
):
    await db_auth.crear_usuario("off@example.com", clave, activo=False)
    for correo, pw in ((EMAIL, "mala-1"), ("fantasma@example.com", clave), ("off@example.com", clave)):
        antes = len(espias["verificar"])
        await http.post("/auth/login", json=login(correo, pw))
        assert len(espias["verificar"]) == antes + 1
    assert espias["hashear"] == []


async def test_correo_inexistente_verifica_contra_el_hash_ficticio(http, espias, app_auth):
    await http.post("/auth/login", json=login("fantasma@example.com", "cualquiera"))
    assert espias["verificar"] == [app_auth.state.hash_ficticio]


async def test_correo_existente_verifica_contra_su_propio_hash(http, ana, espias, app_auth, db_auth):
    await http.post("/auth/login", json=login(EMAIL, "mala"))
    (fila,) = await db_auth.filas("SELECT password_hash FROM usuario")
    assert espias["verificar"] == [fila["password_hash"]]
    assert espias["verificar"][0] != app_auth.state.hash_ficticio


async def test_los_tres_fallos_quedan_anotados_confirmados(http, db_auth, clave, ana):
    await db_auth.crear_usuario("off@example.com", clave, activo=False)
    await http.post("/auth/login", json=login(EMAIL, "mala"))
    await http.post("/auth/login", json=login("fantasma@example.com", clave))
    await http.post("/auth/login", json=login("off@example.com", clave))
    filas = await db_auth.filas("SELECT email, ip, exito FROM intento_acceso ORDER BY id")
    assert filas == [
        {"email": EMAIL, "ip": IP, "exito": False},
        {"email": "fantasma@example.com", "ip": IP, "exito": False},
        {"email": "off@example.com", "ip": IP, "exito": False},
    ]


# --- 8.4 límite de intentos ----------------------------------------------------------------


class Reloj:
    def __init__(self, base):
        self.t = base

    def __call__(self):
        return self.t


@pytest.fixture
def reloj(monkeypatch):
    from datetime import UTC, datetime

    from app.modules.usuarios import service

    r = Reloj(datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC))
    monkeypatch.setattr(service, "ahora", r)
    return r


async def _fallar(http, correo=EMAIL):
    return await http.post("/auth/login", json=login(correo, "clave-incorrecta"))


async def test_sexto_intento_429_con_retry_after_sin_verificar_y_cinco_filas(
    http, ana, db_auth, reloj, espias
):
    from datetime import timedelta

    base = reloj.t
    for i in range(5):
        reloj.t = base + timedelta(seconds=2 * i)
        assert (await _fallar(http)).status_code == 401
    reloj.t = base + timedelta(seconds=10)
    verificaciones_antes = len(espias["verificar"])
    r = await _fallar(http)
    assert r.status_code == 429
    assert r.json() == {"detail": "Demasiados intentos fallidos; intente más tarde"}
    assert r.headers["retry-after"] == "50"  # el 5.o fallo mas reciente (t0) sale a t0 + 60 s
    assert "set-cookie" not in r.headers
    assert len(espias["verificar"]) == verificaciones_antes  # sin hash en el 429
    assert espias["hashear"] == []
    assert await db_auth.contar("intento_acceso") == 5  # el 429 no se anota


@pytest.mark.parametrize("segundos_desde_el_fallo", [0, 30, 59])
async def test_retry_after_es_entero_entre_1_y_60(http, ana, db_auth, reloj, segundos_desde_el_fallo):
    from datetime import timedelta

    base = reloj.t
    for _ in range(5):
        await db_auth.insertar_intento(EMAIL, IP, False, base)
    reloj.t = base + timedelta(seconds=segundos_desde_el_fallo)
    r = await _fallar(http)
    assert r.status_code == 429
    assert r.headers["retry-after"] == str(60 - segundos_desde_el_fallo)
    assert 1 <= int(r.headers["retry-after"]) <= 60


async def test_retry_after_nunca_baja_de_1_segundo(http, ana, db_auth, reloj):
    from datetime import timedelta

    base = reloj.t
    for _ in range(5):
        await db_auth.insertar_intento(EMAIL, IP, False, base)
    reloj.t = base + timedelta(seconds=59, milliseconds=900)
    r = await _fallar(http)
    assert (r.status_code, r.headers["retry-after"]) == (429, "1")


async def test_bloqueado_el_login_correcto_tambien_es_429_sin_cookie(http, ana, clave, db_auth, reloj):
    for _ in range(5):
        await db_auth.insertar_intento(EMAIL, IP, False, reloj.t)
    r = await http.post("/auth/login", json=login(EMAIL, clave))
    assert r.status_code == 429 and "set-cookie" not in r.headers


async def test_mismo_correo_desde_otra_ip_y_otro_correo_desde_la_misma_no_se_bloquean(
    http, fabrica_http, ana, db_auth, clave, reloj
):
    await db_auth.crear_usuario("beto@example.com", clave)
    for _ in range(5):
        await db_auth.insertar_intento(EMAIL, IP, False, reloj.t)
    assert (await _fallar(http)).status_code == 429
    otra_ip = fabrica_http("198.51.100.77")
    assert (await _fallar(otra_ip)).status_code == 401
    assert (await http.post("/auth/login", json=login("beto@example.com", clave))).status_code == 200
    assert (await _fallar(http, "beto@example.com")).status_code == 401


async def test_con_cinco_fallos_de_hace_61_segundos_se_verifica_normalmente(
    http, ana, clave, db_auth, reloj, espias
):
    from datetime import timedelta

    for _ in range(5):
        await db_auth.insertar_intento(EMAIL, IP, False, reloj.t - timedelta(seconds=61))
    assert (await _fallar(http)).status_code == 401
    assert len(espias["verificar"]) == 1
    assert (await http.post("/auth/login", json=login(EMAIL, clave))).status_code == 200


async def test_login_correcto_reinicia_solo_esa_cuenta_y_los_fallos_siguen_en_la_tabla(
    http, ana, clave, db_auth, reloj
):
    from datetime import timedelta

    for i in range(4):
        reloj.t += timedelta(seconds=1)
        assert (await _fallar(http)).status_code == 401
    reloj.t += timedelta(seconds=1)
    assert (await http.post("/auth/login", json=login(EMAIL, clave))).status_code == 200
    for i in range(4):
        reloj.t += timedelta(seconds=1)
        assert (await _fallar(http)).status_code == 401  # ningun 429
    filas = await db_auth.filas("SELECT exito FROM intento_acceso")
    assert sum(1 for f in filas if not f["exito"]) == 8
    assert sum(1 for f in filas if f["exito"]) == 1


async def test_exito_desde_otra_ip_no_reinicia_el_conteo_de_esta(
    http, fabrica_http, ana, clave, db_auth, reloj
):
    for _ in range(5):
        await db_auth.insertar_intento(EMAIL, IP, False, reloj.t)
    otra = fabrica_http("198.51.100.77")
    assert (await otra.post("/auth/login", json=login(EMAIL, clave))).status_code == 200
    assert (await _fallar(http)).status_code == 429


# --- 8.5 contrato -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"email": EMAIL, "password": "x", "recordarme": True},
        {"email": "no-es-correo", "password": "x"},
        {"email": EMAIL, "password": ""},
        {"email": EMAIL, "password": "ñ" * 37},
        {"email": EMAIL, "password": "ab\x00c"},
        {"email": EMAIL},
        {},
    ],
)
async def test_login_con_contrato_invalido_422_y_sin_intento_anotado(http, ana, db_auth, cuerpo):
    r = await http.post("/auth/login", json=cuerpo)
    assert r.status_code == 422
    assert await db_auth.contar("intento_acceso") == 0


async def test_login_acepta_password_corta_de_1_caracter_sin_minimo_de_8(http, ana, db_auth):
    r = await http.post("/auth/login", json=login(EMAIL, "x"))
    assert r.status_code == 401  # llego a verificarse (no es 422)
    assert await db_auth.contar("intento_acceso") == 1


# --- 8.6 tiempo parecido (RN-09) ----------------------------------------------------------------


async def test_tiempo_de_login_similar_exista_o_no_el_correo(fabrica_http, app_auth, db_auth, clave):
    import statistics
    import time

    from app.core.security import ServicioContrasenas

    caro = ServicioContrasenas(rondas=10, max_concurrencia=2)
    app_auth.state.contrasenas = caro
    app_auth.state.hash_ficticio = await caro.hashear(secrets.token_urlsafe(32))
    db_auth._hasher = caro
    await db_auth.crear_usuario(EMAIL, clave)
    (fila,) = await db_auth.filas("SELECT password_hash FROM usuario")

    medidas_verificacion = []
    for _ in range(3):
        t0 = time.perf_counter()
        await caro.verificar("x", fila["password_hash"])
        medidas_verificacion.append(time.perf_counter() - t0)
    una_verificacion = statistics.median(medidas_verificacion)

    async def cronometrar(correo, ip):
        # Una IP distinta por peticion: el limite de intentos (RN-08) es por (correo, IP) y con
        # muchas muestras bloquearia al correo existente (429) y falsearia la medicion.
        async with fabrica_http(ip) as cliente:
            t0 = time.perf_counter()
            r = await cliente.post("/auth/login", json=login(correo, "clave-incorrecta"))
            duracion = time.perf_counter() - t0
        assert r.status_code == 401
        return duracion

    # Una peticion de calentamiento por camino (no se mide) y muestras INTERCALADAS: si la maquina
    # se carga a mitad de la prueba, el ruido afecta a los dos caminos por igual.
    await cronometrar(EMAIL, "198.51.100.1")
    await cronometrar("fantasma@example.com", "198.51.100.2")
    existente, inexistente = [], []
    for i in range(15):
        existente.append(await cronometrar(EMAIL, f"198.51.100.{10 + i}"))
        inexistente.append(await cronometrar("fantasma@example.com", f"198.51.100.{100 + i}"))
    diferencia = abs(statistics.median(existente) - statistics.median(inexistente))
    # Sin hash ficticio el camino inexistente seria ~una verificacion completa mas rapido.
    assert diferencia < una_verificacion, (diferencia, una_verificacion)


# --- 8.7 logout -----------------------------------------------------------------------------------


async def test_logout_con_sesion_borra_la_cookie_y_cierra_la_sesion(http, ana, clave):
    await http.post("/auth/login", json=login(EMAIL, clave))
    assert (await http.get("/prueba/autenticada")).status_code == 200
    r = await http.post("/auth/logout")
    assert r.status_code == 200
    assert r.json() == {"mensaje": "Sesión cerrada"}
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("access_token=")
    assert "Max-Age=0" in cookie and "Path=/" in cookie
    assert (await http.get("/prueba/autenticada")).status_code == 401


async def test_logout_sin_cookie_dos_veces_y_con_cookie_basura_dan_lo_mismo(http):
    a = await http.post("/auth/logout")
    b = await http.post("/auth/logout")
    c = await http.post("/auth/logout", headers={"Cookie": "access_token=basura"})
    for r in (a, b, c):
        assert r.status_code == 200
        assert r.json() == {"mensaje": "Sesión cerrada"}
        assert "Max-Age=0" in r.headers["set-cookie"]


# --- 8.8 el bucle sigue libre durante un login ----------------------------------------------------


async def test_health_live_responde_mientras_un_login_calcula_bcrypt(http, fabrica_http, ana, monkeypatch):
    import asyncio
    import time

    import bcrypt

    def checkpw_lento(password, hash_):
        time.sleep(0.5)  # bloqueante a proposito: solo es inocuo si corre fuera del bucle
        return False

    monkeypatch.setattr(bcrypt, "checkpw", checkpw_lento)
    otro = fabrica_http("198.51.100.9")
    t0 = time.perf_counter()
    tarea_login = asyncio.create_task(http.post("/auth/login", json=login(EMAIL, "x")))
    await asyncio.sleep(0.05)
    vivo = await otro.get("/health/live")
    tiempo_live = time.perf_counter() - t0
    assert vivo.status_code == 200
    assert not tarea_login.done()  # el login sigue calculando
    assert tiempo_live < 0.4
    assert (await tarea_login).status_code == 401
