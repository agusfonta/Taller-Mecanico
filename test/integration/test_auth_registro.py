"""POST /auth/registro contra PostgreSQL real (C-05, tareas 7.3 a 7.6)."""
import secrets

import pytest

pytestmark = pytest.mark.integration

TABLAS = ("usuario", "asignacion_rol", "cliente", "evento_seguridad")


@pytest.fixture
def clave() -> str:
    return "pw-" + secrets.token_urlsafe(12)


def datos(clave, **cambios):
    base = {
        "email": "ana@example.com",
        "password": clave,
        "nombre": "Ana Pérez",
        "documento": "30111222",
        "telefono": "3815550000",
    }
    base.update(cambios)
    return base


# --- 7.3 registro válido ---------------------------------------------------------------


async def test_registro_valido_201_con_cuerpo_y_sin_cookie(http, db_auth, clave):
    r = await http.post("/auth/registro", json=datos(clave))
    assert r.status_code == 201
    cuerpo = r.json()
    assert set(cuerpo) == {"id", "email", "nombre", "cliente_id", "roles"}
    assert cuerpo["email"] == "ana@example.com"
    assert cuerpo["nombre"] == "Ana Pérez"
    assert cuerpo["roles"] == ["CLIENTE"]
    assert "set-cookie" not in r.headers
    assert "password" not in r.text and clave not in r.text and "$2b$" not in r.text


async def test_registro_valido_deja_usuario_rol_cliente_y_evento_en_la_base(http, db_auth, clave):
    r = await http.post("/auth/registro", json=datos(clave))
    cuerpo = r.json()

    (usuario,) = await db_auth.filas("SELECT * FROM usuario")
    assert usuario["id"] == cuerpo["id"]
    assert usuario["activo"] is True and usuario["debe_cambiar_password"] is False
    assert usuario["password_cambiada_en"] is None
    assert usuario["password_hash"].startswith("$2b$04$") and clave not in usuario["password_hash"]

    (asignacion,) = await db_auth.filas("SELECT * FROM asignacion_rol")
    assert asignacion["usuario_id"] == usuario["id"]
    assert asignacion["rol"] == "CLIENTE"
    assert asignacion["vence_en"] is None and asignacion["revocada_en"] is None
    assert asignacion["otorgada_por"] is None

    (cliente,) = await db_auth.filas("SELECT * FROM cliente")
    assert cliente["id"] == cuerpo["cliente_id"] and cliente["usuario_id"] == usuario["id"]
    assert (cliente["nombre"], cliente["documento"], cliente["telefono"]) == (
        "Ana Pérez", "30111222", "3815550000",
    )

    (evento,) = await db_auth.filas("SELECT * FROM evento_seguridad")
    assert evento["actor"] == "ana@example.com"
    assert evento["accion"] == "Registro de cliente"


async def test_registro_de_dos_personas_distintas_crea_dos_juegos_de_filas(http, db_auth, clave):
    a = await http.post("/auth/registro", json=datos(clave))
    b = await http.post(
        "/auth/registro", json=datos(clave, email="beto@example.com", documento="27999888", nombre="Beto")
    )
    assert (a.status_code, b.status_code) == (201, 201)
    assert a.json()["id"] != b.json()["id"] and a.json()["cliente_id"] != b.json()["cliente_id"]
    assert await db_auth.conteos(*TABLAS) == dict.fromkeys(TABLAS, 2)


# --- 7.5 conflictos y contrato ----------------------------------------------------------

PROHIBIDO_EN_CUERPO = ("IntegrityError", "duplicate key", "uq_", "usuario_email", "Traceback", "asyncpg", "DETAIL")


def _sin_detalles_de_base(texto: str) -> None:
    for fragmento in PROHIBIDO_EN_CUERPO:
        assert fragmento not in texto, fragmento
    for tabla in ("asignacion_rol", "evento_seguridad", '"usuario"', "cliente_usuario"):
        assert tabla not in texto, tabla


async def test_correo_repetido_409_sin_filas_sueltas(http, db_auth, clave):
    assert (await http.post("/auth/registro", json=datos(clave))).status_code == 201
    antes = await db_auth.conteos(*TABLAS)
    r = await http.post("/auth/registro", json=datos(clave, documento="27999888"))
    assert r.status_code == 409
    assert r.json() == {"detail": "El correo ya está registrado"}
    _sin_detalles_de_base(r.text)
    assert await db_auth.conteos(*TABLAS) == antes


async def test_correo_repetido_con_otra_capitalizacion_tambien_409(http, db_auth, clave):
    await http.post("/auth/registro", json=datos(clave, email="Ana@Example.COM"))
    assert (await db_auth.filas("SELECT email FROM usuario"))[0]["email"] == "ana@example.com"
    antes = await db_auth.conteos(*TABLAS)
    r = await http.post("/auth/registro", json=datos(clave, email="ana@example.com", documento="1"))
    assert (r.status_code, r.json()) == (409, {"detail": "El correo ya está registrado"})
    assert await db_auth.conteos(*TABLAS) == antes


async def test_documento_de_cliente_sin_usuario_409_y_la_ficha_queda_intacta(http, db_auth, clave):
    cliente_id = await db_auth.sembrar_cliente_sin_usuario("30111222")
    antes = await db_auth.conteos(*TABLAS)
    r = await http.post("/auth/registro", json=datos(clave))
    assert r.status_code == 409
    assert r.json() == {"detail": "El documento ya pertenece a un cliente del taller"}
    _sin_detalles_de_base(r.text)
    assert await db_auth.conteos(*TABLAS) == antes
    (ficha,) = await db_auth.filas("SELECT * FROM cliente WHERE id = :i", i=cliente_id)
    assert ficha["usuario_id"] is None and ficha["nombre"] == "Cargado por recepcion"


async def test_documento_de_cliente_con_usuario_tambien_409(http, db_auth, clave):
    await http.post("/auth/registro", json=datos(clave))
    antes = await db_auth.conteos(*TABLAS)
    r = await http.post("/auth/registro", json=datos(clave, email="otro@example.com"))
    assert (r.status_code, r.json()) == (409, {"detail": "El documento ya pertenece a un cliente del taller"})
    assert await db_auth.conteos(*TABLAS) == antes


async def test_si_chocan_correo_y_documento_gana_el_correo(http, db_auth, clave):
    await http.post("/auth/registro", json=datos(clave))
    r = await http.post("/auth/registro", json=datos(clave))
    assert r.json() == {"detail": "El correo ya está registrado"}


@pytest.mark.parametrize("extra", [{"rol": "ADMIN"}, {"activo": True}, {"id": 5}])
async def test_campo_extra_422_sin_filas(http, db_auth, clave, extra):
    r = await http.post("/auth/registro", json=datos(clave, **extra))
    assert r.status_code == 422
    assert await db_auth.conteos(*TABLAS) == dict.fromkeys(TABLAS, 0)


@pytest.mark.parametrize("password", ["a" * 7, "ñ" * 37, "abcdefg\x00h"])
async def test_password_fuera_de_politica_422_sin_filas_y_sin_500(http, db_auth, password):
    r = await http.post("/auth/registro", json=datos(password))
    assert r.status_code == 422
    assert await db_auth.conteos(*TABLAS) == dict.fromkeys(TABLAS, 0)


async def test_password_de_72_bytes_se_acepta(http, db_auth):
    r = await http.post("/auth/registro", json=datos("ñ" * 36))
    assert r.status_code == 201


async def test_documento_con_solo_espacios_422(http, db_auth, clave):
    r = await http.post("/auth/registro", json=datos(clave, documento="   "))
    assert r.status_code == 422


async def test_en_422_no_se_calcula_ningun_hash(http, app_auth, db_auth, clave, monkeypatch):
    llamadas = []
    real = app_auth.state.contrasenas.hashear

    async def espia(password):
        llamadas.append(password)
        return await real(password)

    monkeypatch.setattr(app_auth.state.contrasenas, "hashear", espia)
    for malo in (datos("corta"), datos(clave, rol="ADMIN"), datos(clave, documento=" ")):
        assert (await http.post("/auth/registro", json=malo)).status_code == 422
    assert llamadas == []
    assert (await http.post("/auth/registro", json=datos(clave))).status_code == 201
    assert len(llamadas) == 1


async def test_el_hash_se_calcula_antes_de_abrir_la_transaccion(http, app_auth, db_auth, clave, monkeypatch):
    # Mientras corre el hash no debe haber ninguna sentencia SQL en la peticion (conexion no tomada).
    from sqlalchemy import event

    sentencias = []
    motor = app_auth.state.engine.sync_engine
    event.listen(motor, "before_cursor_execute", lambda *a: sentencias.append(a[2]))
    en_hash = []
    real = app_auth.state.contrasenas.hashear

    async def espia(password):
        en_hash.append(len(sentencias))
        return await real(password)

    monkeypatch.setattr(app_auth.state.contrasenas, "hashear", espia)
    assert (await http.post("/auth/registro", json=datos(clave))).status_code == 201
    assert en_hash == [0]


# --- 7.6 atomicidad -----------------------------------------------------------------------


async def test_fallo_despues_de_insertar_el_usuario_no_deja_filas(http, db_auth, clave, monkeypatch):
    from app.modules.clientes.repository import ClienteRepository

    async def falla(self, entidad):
        raise RuntimeError("fallo simulado al crear la ficha")

    monkeypatch.setattr(ClienteRepository, "add", falla)
    with pytest.raises(RuntimeError):
        await http.post("/auth/registro", json=datos(clave))
    assert await db_auth.conteos(*TABLAS) == dict.fromkeys(TABLAS, 0)


async def test_fallo_al_escribir_el_evento_revierte_usuario_rol_y_ficha(http, db_auth, clave, monkeypatch):
    from app.modules.usuarios.repository import EventoSeguridadRepository

    async def falla(self, entidad):
        raise RuntimeError("fallo simulado al escribir el evento")

    monkeypatch.setattr(EventoSeguridadRepository, "add", falla)
    with pytest.raises(RuntimeError):
        await http.post("/auth/registro", json=datos(clave))
    assert await db_auth.conteos(*TABLAS) == dict.fromkeys(TABLAS, 0)
