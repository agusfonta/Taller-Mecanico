"""POST /usuarios (alta de personal) contra PostgreSQL real (C-06, tareas 5.1 a 5.6)."""
import pytest

from test.integration.sesiones import admin_con_sesion, clave, entrar, usuario_con_sesion

pytestmark = pytest.mark.integration

TABLAS = ("usuario", "asignacion_rol", "evento_seguridad")
ADMIN = "admin@taller.com"


def cuerpo(**cambios):
    base = {"email": "Nuevo@Taller.COM", "nombre": "Nuevo Mecánico", "password": clave(), "rol": "MECANICO"}
    base.update(cambios)
    return base


async def test_alta_valida_de_mecanico_devuelve_201_con_cuerpo_exacto_y_deja_filas_y_evento(db_auth, fabrica_http):
    admin_id, http = await admin_con_sesion(db_auth, fabrica_http, ADMIN)
    datos = cuerpo()
    r = await http.post("/usuarios", json=datos)
    assert r.status_code == 201, r.text
    nuevo = r.json()
    assert set(nuevo) == {"id", "email", "nombre", "debe_cambiar_password", "roles"}
    assert nuevo == {
        "id": nuevo["id"],
        "email": "nuevo@taller.com",
        "nombre": "Nuevo Mecánico",
        "debe_cambiar_password": True,
        "roles": ["MECANICO"],
    }
    assert "set-cookie" not in r.headers
    assert "password_hash" not in r.text and '"password"' not in r.text
    assert "$2b$" not in r.text and datos["password"] not in r.text

    (u,) = await db_auth.filas("SELECT * FROM usuario WHERE email = 'nuevo@taller.com'")
    assert u["id"] == nuevo["id"] and u["activo"] is True and u["debe_cambiar_password"] is True
    assert u["password_hash"].startswith("$2") and datos["password"] not in u["password_hash"]
    (a,) = await db_auth.filas("SELECT * FROM asignacion_rol WHERE usuario_id = :u", u=nuevo["id"])
    assert a["rol"] == "MECANICO" and a["vence_en"] is None and a["revocada_en"] is None
    assert a["otorgada_por"] == admin_id
    eventos = await db_auth.filas("SELECT actor, accion FROM evento_seguridad")
    assert eventos == [{"actor": ADMIN, "accion": "Alta de personal: nuevo@taller.com con rol MECANICO"}]


# --- 5.3 triangular: el creado entra con la provisoria; otros roles --------------------------


async def test_el_creado_inicia_sesion_con_la_provisoria_y_queda_bloqueado_por_cambio_pendiente(
    db_auth, fabrica_http
):
    _, admin = await admin_con_sesion(db_auth, fabrica_http, ADMIN)
    datos = cuerpo(email="mec@taller.com")
    assert (await admin.post("/usuarios", json=datos)).status_code == 201
    nuevo = fabrica_http()
    r = await nuevo.post("/auth/login", json={"email": "mec@taller.com", "password": datos["password"]})
    assert r.status_code == 200 and r.json()["debe_cambiar_password"] is True
    bloqueado = await nuevo.get("/prueba/protegida")
    assert bloqueado.status_code == 403
    assert bloqueado.json() == {"detail": "Debe cambiar la contraseña antes de continuar"}
    # /auth/yo sigue disponible y muestra su rol de la base
    assert (await nuevo.get("/auth/yo")).json()["roles_vigentes"] == ["MECANICO"]


@pytest.mark.parametrize("rol", ["RECEPCION", "ADMIN"])
async def test_alta_de_recepcion_y_de_admin(db_auth, fabrica_http, rol):
    _, admin = await admin_con_sesion(db_auth, fabrica_http, ADMIN)
    r = await admin.post("/usuarios", json=cuerpo(email=f"nuevo-{rol.lower()}@taller.com", rol=rol))
    assert r.status_code == 201 and r.json()["roles"] == [rol]
    (ev,) = await db_auth.filas("SELECT accion FROM evento_seguridad")
    assert ev["accion"] == f"Alta de personal: nuevo-{rol.lower()}@taller.com con rol {rol}"


async def test_el_nuevo_admin_tras_cambiar_la_contrasena_puede_dar_de_alta(db_auth, fabrica_http):
    _, admin = await admin_con_sesion(db_auth, fabrica_http, ADMIN)
    datos = cuerpo(email="otro-admin@taller.com", rol="ADMIN")
    assert (await admin.post("/usuarios", json=datos)).status_code == 201
    nuevo = fabrica_http()
    await entrar(nuevo, "otro-admin@taller.com", datos["password"])
    # con el cambio pendiente no puede dar de alta
    assert (await nuevo.post("/usuarios", json=cuerpo(email="x@taller.com"))).status_code == 403
    clave_nueva = clave()
    r = await nuevo.post(
        "/auth/cambiar-password", json={"password_actual": datos["password"], "password_nueva": clave_nueva}
    )
    assert r.status_code == 200
    r = await nuevo.post("/usuarios", json=cuerpo(email="x@taller.com"))
    assert r.status_code == 201
    (a,) = await db_auth.filas("SELECT u.id FROM usuario u WHERE email = 'x@taller.com'")
    (asig,) = await db_auth.filas("SELECT otorgada_por FROM asignacion_rol WHERE usuario_id = :u", u=a["id"])
    (otro,) = await db_auth.filas("SELECT id FROM usuario WHERE email = 'otro-admin@taller.com'")
    assert asig["otorgada_por"] == otro["id"]


# --- 5.4 triangular: conflictos y contrato --------------------------------------------------


async def test_correo_existente_con_otra_capitalizacion_da_409_sin_filas_nuevas_ni_texto_de_la_base(
    db_auth, fabrica_http
):
    _, admin = await admin_con_sesion(db_auth, fabrica_http, ADMIN)
    existente = await db_auth.crear_usuario("ya@taller.com", clave(), roles=("RECEPCION",), nombre="Original")
    antes = await db_auth.conteos(*TABLAS)
    hash_antes = (await db_auth.filas("SELECT password_hash FROM usuario WHERE id = :i", i=existente))[0]
    r = await admin.post("/usuarios", json=cuerpo(email="YA@Taller.com", nombre="Otro"))
    assert r.status_code == 409
    assert r.json() == {"detail": "El correo ya está registrado"}
    for prohibido in ("IntegrityError", "duplicate key", "uq_", "usuario", "asignacion_rol"):
        assert prohibido not in r.text
    assert await db_auth.conteos(*TABLAS) == antes
    (u,) = await db_auth.filas("SELECT nombre, password_hash FROM usuario WHERE id = :i", i=existente)
    assert u["nombre"] == "Original" and u["password_hash"] == hash_antes["password_hash"]


@pytest.mark.parametrize(
    "cambios",
    [
        {"rol": None},  # se elimina la clave
        {"rol": "CLIENTE"},
        {"rol": "JEFE"},
        {"debe_cambiar_password": False},
        {"password": "1234567"},
        {"password": "ñ" * 37},
        {"nombre": "   "},
        {"email": "no-es-correo"},
    ],
)
async def test_cuerpos_invalidos_dan_422_sin_filas_y_sin_calcular_hash(
    db_auth, fabrica_http, app_auth, monkeypatch, cambios
):
    _, admin = await admin_con_sesion(db_auth, fabrica_http, ADMIN)
    antes = await db_auth.conteos(*TABLAS)
    llamadas = []
    original = app_auth.state.contrasenas.hashear

    async def espia(password):
        llamadas.append(1)
        return await original(password)

    monkeypatch.setattr(app_auth.state.contrasenas, "hashear", espia)
    datos = cuerpo()
    for k, v in cambios.items():
        if v is None:
            del datos[k]
        else:
            datos[k] = v
    r = await admin.post("/usuarios", json=datos)
    assert r.status_code == 422, r.text
    assert await db_auth.conteos(*TABLAS) == antes
    assert llamadas == []


# --- 5.5 triangular: atomicidad -------------------------------------------------------------


@pytest.mark.parametrize("repo", ["EventoSeguridadRepository", "AsignacionRolRepository"])
async def test_si_falla_un_paso_posterior_al_usuario_no_queda_ninguna_fila(
    db_auth, fabrica_http, monkeypatch, repo
):
    from app.modules.usuarios import repository

    _, admin = await admin_con_sesion(db_auth, fabrica_http, ADMIN)
    antes = await db_auth.conteos(*TABLAS)

    async def falla(self, entidad):
        raise RuntimeError("fallo forzado")

    monkeypatch.setattr(getattr(repository, repo), "add", falla)
    with pytest.raises(RuntimeError, match="fallo forzado"):
        await admin.post("/usuarios", json=cuerpo(email="atomico@taller.com"))
    monkeypatch.undo()
    assert await db_auth.conteos(*TABLAS) == antes
    assert await db_auth.filas("SELECT 1 FROM usuario WHERE email = 'atomico@taller.com'") == []
