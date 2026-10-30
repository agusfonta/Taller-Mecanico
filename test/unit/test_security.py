"""Contraseñas (política, bcrypt bajo semáforo) y token/cookie de sesión (C-05)."""
import asyncio
import secrets
import threading
import time

import bcrypt
import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

pytestmark = pytest.mark.unit


def _modelos():
    from app.core.security import PasswordIngresada, PasswordNueva

    class Nueva(BaseModel):
        model_config = ConfigDict(extra="forbid")
        password: PasswordNueva

    class Ingresada(BaseModel):
        model_config = ConfigDict(extra="forbid")
        password: PasswordIngresada

    return Nueva, Ingresada


# --- 2.1 / 2.2 política de contraseña ------------------------------------------


def test_password_nueva_de_7_caracteres_se_rechaza():
    nueva, _ = _modelos()
    with pytest.raises(ValidationError):
        nueva(password="a" * 7)


def test_password_nueva_de_8_caracteres_se_acepta():
    nueva, _ = _modelos()
    assert nueva(password="a" * 8).password == "a" * 8


def test_password_ingresada_de_1_caracter_se_acepta_sin_minimo_de_8():
    _, ingresada = _modelos()
    assert ingresada(password="a").password == "a"


@pytest.mark.parametrize("indice", [0, 1])
def test_72_bytes_con_multibyte_se_acepta(indice):
    modelo = _modelos()[indice]
    assert modelo(password="ñ" * 36).password == "ñ" * 36  # 72 bytes


@pytest.mark.parametrize("indice", [0, 1])
def test_74_bytes_con_multibyte_se_rechaza(indice):
    modelo = _modelos()[indice]
    with pytest.raises(ValidationError):
        modelo(password="ñ" * 37)  # 37 caracteres, 74 bytes


def test_73_bytes_ascii_se_rechaza_y_72_se_acepta():
    nueva, ingresada = _modelos()
    assert ingresada(password="a" * 72)
    with pytest.raises(ValidationError):
        ingresada(password="a" * 73)
    with pytest.raises(ValidationError):
        nueva(password="a" * 73)


@pytest.mark.parametrize("indice", [0, 1])
def test_caracter_nulo_se_rechaza(indice):
    modelo = _modelos()[indice]
    with pytest.raises(ValidationError):
        modelo(password="abcdefg\x00h")


@pytest.mark.parametrize("indice", [0, 1])
def test_password_vacia_se_rechaza(indice):
    modelo = _modelos()[indice]
    with pytest.raises(ValidationError):
        modelo(password="")


def test_mensaje_de_error_de_72_bytes_es_propio_en_espanol():
    _, ingresada = _modelos()
    with pytest.raises(ValidationError) as info:
        ingresada(password="ñ" * 37)
    assert "72 bytes" in str(info.value)


# --- 2.3 servicio bcrypt ---------------------------------------------------------


@pytest.fixture
def servicio():
    from app.core.security import ServicioContrasenas

    return ServicioContrasenas(rondas=4, max_concurrencia=2)


async def test_hashear_declara_el_costo_configurado(servicio):
    hash_ = await servicio.hashear("clave-de-prueba-1")
    assert hash_.startswith("$2b$04$")


async def test_hashear_con_otro_costo_lo_declara():
    from app.core.security import ServicioContrasenas

    hash_ = await ServicioContrasenas(rondas=5, max_concurrencia=1).hashear("clave-de-prueba-1")
    assert hash_.startswith("$2b$05$")


async def test_verificar_true_con_la_correcta_y_false_con_otra(servicio):
    hash_ = await servicio.hashear("clave-correcta")
    assert await servicio.verificar("clave-correcta", hash_) is True
    assert await servicio.verificar("clave-otra", hash_) is False


async def test_verificar_con_hash_corrupto_devuelve_false_sin_excepcion(servicio):
    assert await servicio.verificar("lo-que-sea", "esto-no-es-un-hash") is False
    assert await servicio.verificar("lo-que-sea", "") is False


async def test_hashear_dos_veces_da_hashes_distintos(servicio):
    a = await servicio.hashear("misma-clave")
    b = await servicio.hashear("misma-clave")
    assert a != b


def test_crear_servicio_toma_rondas_y_concurrencia_de_settings():
    from app.core.config import Settings
    from app.core.security import crear_servicio_contrasenas

    ajustes = Settings(
        _env_file=None,
        jwt_secret_key=secrets.token_urlsafe(48),
        postgres_password="pw-" + secrets.token_hex(4),
        bcrypt_rounds=5,
        bcrypt_max_concurrency=3,
    )

    async def correr():
        servicio = crear_servicio_contrasenas(ajustes)
        return servicio, await servicio.hashear("clave-de-prueba-1")

    servicio, hash_ = asyncio.run(correr())
    assert hash_.startswith("$2b$05$")
    assert servicio.max_concurrencia == 3
    assert servicio.rondas == 5


# --- 2.4 concurrencia ------------------------------------------------------------


@pytest.fixture
def checkpw_lento(monkeypatch):
    """Sustituye bcrypt.checkpw por una función lenta que mide la concurrencia real."""
    estado = {"actual": 0, "maximo": 0, "llamadas": 0}
    cerrojo = threading.Lock()

    def falso(password, hash_):
        with cerrojo:
            estado["actual"] += 1
            estado["llamadas"] += 1
            estado["maximo"] = max(estado["maximo"], estado["actual"])
        time.sleep(0.05)
        with cerrojo:
            estado["actual"] -= 1
        return True

    monkeypatch.setattr(bcrypt, "checkpw", falso)
    return estado


async def test_tope_de_concurrencia_se_respeta_y_todas_terminan(servicio, checkpw_lento):
    resultados = await asyncio.gather(*(servicio.verificar("x", "$2b$04$hash") for _ in range(6)))
    assert resultados == [True] * 6
    assert checkpw_lento["llamadas"] == 6
    assert checkpw_lento["maximo"] == 2


async def test_tope_1_serializa_las_verificaciones(checkpw_lento):
    from app.core.security import ServicioContrasenas

    uno = ServicioContrasenas(rondas=4, max_concurrencia=1)
    await asyncio.gather(*(uno.verificar("x", "h") for _ in range(4)))
    assert checkpw_lento["maximo"] == 1


async def test_el_bucle_sigue_libre_durante_una_verificacion_lenta(servicio, checkpw_lento):
    tarea = asyncio.create_task(servicio.verificar("x", "h"))
    await asyncio.sleep(0.01)  # el bucle atiende otra corrutina mientras bcrypt "calcula"
    assert not tarea.done()
    assert checkpw_lento["actual"] == 1
    assert await tarea is True


# --- 3 token y cookie ------------------------------------------------------------


@pytest.fixture
def ajustes():
    from app.core.config import Settings

    return Settings(
        _env_file=None,
        jwt_secret_key=secrets.token_urlsafe(48),
        postgres_password="pw-" + secrets.token_hex(4),
    )


def test_emitir_token_trae_claims_con_iat_fraccional(ajustes):
    import jwt

    from app.core.security import emitir_token

    token = emitir_token(7, ["CLIENTE"], ajustes, ahora=1700000000.123456)
    datos = jwt.decode(
        token, ajustes.jwt_secret_key.get_secret_value(), algorithms=["HS256"], options={"verify_exp": False}
    )
    assert datos["sub"] == "7"
    assert datos["iat"] == 1700000000.123456
    assert datos["exp"] == datos["iat"] + 1800
    assert datos["roles"] == ["CLIENTE"]


def test_emitir_token_ordena_los_roles_y_usa_la_hora_actual_por_defecto(ajustes):
    import jwt

    from app.core.security import emitir_token

    antes = time.time()
    token = emitir_token(9, ["MECANICO", "ADMIN"], ajustes)
    datos = jwt.decode(token, ajustes.jwt_secret_key.get_secret_value(), algorithms=["HS256"])
    assert datos["roles"] == ["ADMIN", "MECANICO"]
    assert antes <= datos["iat"] <= time.time()
    assert isinstance(datos["iat"], float)


def test_decodificar_token_devuelve_claims_con_sub_entero(ajustes):
    from app.core.security import decodificar_token, emitir_token

    ahora = time.time()
    claims = decodificar_token(emitir_token(7, ["ADMIN", "CLIENTE"], ajustes, ahora=ahora), ajustes)
    assert claims.sub == 7
    assert isinstance(claims.sub, int)
    assert claims.iat == ahora
    assert claims.exp == ahora + 1800
    assert claims.roles == ("ADMIN", "CLIENTE")


def test_decodificar_token_de_otro_usuario_da_otro_sub(ajustes):
    from app.core.security import decodificar_token, emitir_token

    assert decodificar_token(emitir_token(42, [], ajustes), ajustes).sub == 42


def _token_a_mano(clave: str | None, algoritmo: str, **claims) -> str:
    import jwt

    base = {"sub": "7", "iat": time.time(), "exp": time.time() + 600, "roles": []}
    base.update(claims)
    base = {k: v for k, v in base.items() if v is not None}
    return jwt.encode(base, clave, algorithm=algoritmo)


@pytest.mark.parametrize(
    "construir",
    [
        pytest.param(lambda c: _token_a_mano(secrets.token_urlsafe(48), "HS256"), id="otra-clave"),
        pytest.param(lambda c: _token_a_mano(None, "none"), id="alg-none"),
        pytest.param(lambda c: _token_a_mano(c, "HS512"), id="hs512"),
        pytest.param(
            lambda c: _token_a_mano(c, "HS256", iat=time.time() - 4000, exp=time.time() - 2000), id="vencido"
        ),
        pytest.param(lambda c: _token_a_mano(c, "HS256", sub=None), id="sin-sub"),
        pytest.param(lambda c: _token_a_mano(c, "HS256", iat=None), id="sin-iat"),
        pytest.param(lambda c: _token_a_mano(c, "HS256", exp=None), id="sin-exp"),
        pytest.param(lambda c: _token_a_mano(c, "HS256", sub="abc"), id="sub-no-numerico"),
        pytest.param(lambda c: _token_a_mano(c, "HS256", roles="ADMIN"), id="roles-no-lista"),
        pytest.param(lambda c: "esto.no.es-un-jwt", id="basura"),
        pytest.param(lambda c: "", id="vacio"),
    ],
)
def test_token_invalido_lanza_token_invalido_error(ajustes, construir):
    from app.core.security import TokenInvalidoError, decodificar_token

    token = construir(ajustes.jwt_secret_key.get_secret_value())
    with pytest.raises(TokenInvalidoError):
        decodificar_token(token, ajustes)


def test_emitir_token_vencido_con_ahora_en_el_pasado_se_rechaza(ajustes):
    from app.core.security import TokenInvalidoError, decodificar_token, emitir_token

    token = emitir_token(7, [], ajustes, ahora=time.time() - 3600)
    with pytest.raises(TokenInvalidoError):
        decodificar_token(token, ajustes)


def _set_cookie(response) -> str:
    return response.headers["set-cookie"]


def test_poner_cookie_sesion_sin_secure(ajustes):
    from starlette.responses import Response

    from app.core.security import poner_cookie_sesion

    respuesta = Response()
    poner_cookie_sesion(respuesta, "TOKEN123", ajustes)
    cookie = _set_cookie(respuesta)
    assert cookie.startswith("access_token=TOKEN123")
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/" in cookie
    assert "Max-Age=1800" in cookie
    assert "Secure" not in cookie
    assert "Domain" not in cookie


def test_poner_cookie_sesion_con_secure(ajustes):
    from starlette.responses import Response

    from app.core.security import poner_cookie_sesion

    respuesta = Response()
    poner_cookie_sesion(respuesta, "T", ajustes.model_copy(update={"cookie_secure": True}))
    assert "Secure" in _set_cookie(respuesta)


def test_poner_cookie_usa_la_duracion_configurada(ajustes):
    from starlette.responses import Response

    from app.core.security import poner_cookie_sesion

    respuesta = Response()
    poner_cookie_sesion(respuesta, "T", ajustes.model_copy(update={"jwt_expire_minutes": 5}))
    assert "Max-Age=300" in _set_cookie(respuesta)


@pytest.mark.parametrize("seguro", [False, True])
def test_borrar_cookie_sesion_usa_los_mismos_atributos(ajustes, seguro):
    from starlette.responses import Response

    from app.core.security import borrar_cookie_sesion

    respuesta = Response()
    borrar_cookie_sesion(respuesta, ajustes.model_copy(update={"cookie_secure": seguro}))
    cookie = _set_cookie(respuesta)
    assert cookie.startswith("access_token=")
    assert "Max-Age=0" in cookie
    assert "Path=/" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert ("Secure" in cookie) is seguro
