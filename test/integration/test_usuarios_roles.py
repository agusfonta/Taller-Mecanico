"""GET/POST /usuarios/{id}/roles contra PostgreSQL real (C-06, tareas 6.1 a 6.7; casos C-07/RN-03)."""
import asyncio
from datetime import UTC, datetime, timedelta, timezone

import pytest

from test.integration.sesiones import admin_con_sesion, clave, usuario_con_sesion

pytestmark = pytest.mark.integration

ADMIN = "admin@taller.com"
TABLAS = ("usuario", "asignacion_rol", "evento_seguridad")


def _hace(**kw):
    return datetime.now(UTC) - timedelta(**kw)


def _en(**kw):
    return datetime.now(UTC) + timedelta(**kw)


# --- 6.1 GET ----------------------------------------------------------------------------------


async def test_get_roles_devuelve_vigentes_y_las_tres_asignaciones_con_su_vigente(db_auth, fabrica_http):
    _, admin = await admin_con_sesion(db_auth, fabrica_http, ADMIN)
    uid = await db_auth.crear_usuario("u@taller.com", clave(), roles=())
    t = datetime(2026, 1, 1, tzinfo=UTC)
    for rol, desde, vence, revoca in (
        ("MECANICO", t, None, None),
        ("RECEPCION", t + timedelta(hours=1), None, _hace(days=1)),
        ("ADMIN", t + timedelta(hours=2), _hace(days=1), None),
    ):
        await db_auth.ejecutar(
            "INSERT INTO asignacion_rol (usuario_id, rol, desde, vence_en, revocada_en) "
            "VALUES (:u, :r, :d, :v, :x)",
            u=uid, r=rol, d=desde, v=vence, x=revoca,
        )
    r = await admin.get(f"/usuarios/{uid}/roles")
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert set(cuerpo) == {"usuario_id", "email", "roles_vigentes", "asignaciones"}
    assert cuerpo["usuario_id"] == uid and cuerpo["email"] == "u@taller.com"
    assert cuerpo["roles_vigentes"] == ["MECANICO"]
    assert [(a["rol"], a["vigente"]) for a in cuerpo["asignaciones"]] == [
        ("MECANICO", True), ("RECEPCION", False), ("ADMIN", False)]
    assert set(cuerpo["asignaciones"][0]) == {
        "id", "usuario_id", "rol", "desde", "vence_en", "revocada_en", "otorgada_por", "vigente"}


async def test_get_roles_usuario_inexistente_404_y_id_no_entero_422(db_auth, fabrica_http):
    _, admin = await admin_con_sesion(db_auth, fabrica_http, ADMIN)
    r = await admin.get("/usuarios/999999/roles")
    assert r.status_code == 404 and r.json() == {"detail": "Usuario no encontrado"}
    assert (await admin.get("/usuarios/abc/roles")).status_code == 422


async def test_get_roles_de_usuario_sin_asignaciones_devuelve_listas_vacias(db_auth, fabrica_http):
    _, admin = await admin_con_sesion(db_auth, fabrica_http, ADMIN)
    uid = await db_auth.crear_usuario("vacio@taller.com", clave(), roles=())
    r = await admin.get(f"/usuarios/{uid}/roles")
    assert r.status_code == 200
    assert r.json()["roles_vigentes"] == [] and r.json()["asignaciones"] == []


# --- 6.3 POST: asignar -------------------------------------------------------------------------


async def test_asignar_recepcion_sin_vencimiento(db_auth, fabrica_http):
    admin_id, admin = await admin_con_sesion(db_auth, fabrica_http, ADMIN)
    uid = await db_auth.crear_usuario("u@taller.com", clave(), roles=("CLIENTE",))
    r = await admin.post(f"/usuarios/{uid}/roles", json={"rol": "RECEPCION"})
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["usuario_id"] == uid and c["rol"] == "RECEPCION" and c["vence_en"] is None
    assert c["revocada_en"] is None and c["otorgada_por"] == admin_id and c["vigente"] is True
    (e,) = await db_auth.filas("SELECT actor, accion FROM evento_seguridad")
    assert e == {"actor": ADMIN, "accion": "Asignación de rol RECEPCION a u@taller.com"}


async def test_asignar_mecanico_con_vencimiento_futuro_con_zona(db_auth, fabrica_http):
    _, admin = await admin_con_sesion(db_auth, fabrica_http, ADMIN)
    uid, usuario, _ = await usuario_con_sesion(db_auth, fabrica_http, "u@taller.com", roles=("CLIENTE",))
    vence = _en(days=2).astimezone(timezone(timedelta(hours=-3))).isoformat()
    assert vence.endswith("-03:00")
    r = await admin.post(f"/usuarios/{uid}/roles", json={"rol": "MECANICO", "vence_en": vence})
    assert r.status_code == 201, r.text
    assert datetime.fromisoformat(r.json()["vence_en"]) == datetime.fromisoformat(vence)
    # el usuario, con su sesion abierta, ya lo tiene vigente
    yo = (await usuario.get("/auth/yo")).json()
    assert yo["roles_vigentes"] == ["CLIENTE", "MECANICO"]
    (e,) = await db_auth.filas("SELECT accion FROM evento_seguridad")
    utc = datetime.fromisoformat(vence).astimezone(UTC).isoformat()
    assert e["accion"] == f"Asignación de rol MECANICO a u@taller.com hasta {utc}"


# --- 6.5 triangular ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "vence",
    ["2099-01-01T10:00:00", (datetime.now(UTC) - timedelta(minutes=1)).isoformat(), "2020-01-01T00:00:00Z"],
)
async def test_vencimiento_sin_zona_o_pasado_da_422_sin_filas_ni_eventos(db_auth, fabrica_http, vence):
    _, admin = await admin_con_sesion(db_auth, fabrica_http, ADMIN)
    uid = await db_auth.crear_usuario("u@taller.com", clave(), roles=("CLIENTE",))
    antes = await db_auth.conteos(*TABLAS)
    r = await admin.post(f"/usuarios/{uid}/roles", json={"rol": "MECANICO", "vence_en": vence})
    assert r.status_code == 422
    assert await db_auth.conteos(*TABLAS) == antes


async def test_rol_abierto_y_vigente_da_409_sin_filas_nuevas_ni_evento(db_auth, fabrica_http):
    _, admin = await admin_con_sesion(db_auth, fabrica_http, ADMIN)
    uid = await db_auth.crear_usuario("u@taller.com", clave(), roles=("MECANICO",))
    antes = await db_auth.conteos(*TABLAS)
    r = await admin.post(f"/usuarios/{uid}/roles", json={"rol": "MECANICO"})
    assert r.status_code == 409 and r.json() == {"detail": "El usuario ya tiene ese rol asignado"}
    assert await db_auth.conteos(*TABLAS) == antes


async def test_usuario_inexistente_con_cuerpo_valido_da_404_y_cuerpos_invalidos_422(db_auth, fabrica_http):
    _, admin = await admin_con_sesion(db_auth, fabrica_http, ADMIN)
    antes = await db_auth.conteos(*TABLAS)
    r = await admin.post("/usuarios/999999/roles", json={"rol": "MECANICO"})
    assert r.status_code == 404 and r.json() == {"detail": "Usuario no encontrado"}
    assert (await admin.post("/usuarios/999999/roles", json={"rol": "JEFE"})).status_code == 422
    assert (await admin.post("/usuarios/999999/roles", json={"rol": "ADMIN", "x": 1})).status_code == 422
    assert await db_auth.conteos(*TABLAS) == antes


async def test_reasignar_un_mecanico_abierto_y_vencido_cierra_la_fila_vieja_y_abre_una_nueva(
    db_auth, fabrica_http
):
    admin_id, admin = await admin_con_sesion(db_auth, fabrica_http, ADMIN)
    uid = await db_auth.crear_usuario("u@taller.com", clave(), roles=())
    await db_auth.asignar_rol(uid, "MECANICO", vence_en=_hace(days=3))
    (vieja,) = await db_auth.filas("SELECT * FROM asignacion_rol WHERE usuario_id = :u", u=uid)
    r = await admin.post(f"/usuarios/{uid}/roles", json={"rol": "MECANICO"})
    assert r.status_code == 201, r.text
    filas = await db_auth.filas("SELECT * FROM asignacion_rol WHERE usuario_id = :u ORDER BY id", u=uid)
    assert len(filas) == 2
    cerrada, nueva = filas
    assert cerrada["revocada_en"] is not None
    assert {k: v for k, v in cerrada.items() if k != "revocada_en"} == {
        k: v for k, v in vieja.items() if k != "revocada_en"}
    assert nueva["id"] == r.json()["id"] and nueva["revocada_en"] is None and nueva["otorgada_por"] == admin_id
    assert len([f for f in filas if f["rol"] == "MECANICO" and f["revocada_en"] is None]) == 1
    assert len(await db_auth.filas("SELECT 1 FROM evento_seguridad")) == 1  # un unico evento


# --- 6.6 concurrencia -----------------------------------------------------------------------------


async def test_dos_asignaciones_simultaneas_iguales_dan_201_y_409_una_sola_abierta_y_un_evento(
    db_auth, fabrica_http
):
    _, a1 = await admin_con_sesion(db_auth, fabrica_http, "a1@taller.com")
    _, a2 = await admin_con_sesion(db_auth, fabrica_http, "a2@taller.com")
    uid = await db_auth.crear_usuario("u@taller.com", clave(), roles=("CLIENTE",))
    antes = await db_auth.contar("evento_seguridad")
    rs = await asyncio.gather(
        a1.post(f"/usuarios/{uid}/roles", json={"rol": "RECEPCION"}),
        a2.post(f"/usuarios/{uid}/roles", json={"rol": "RECEPCION"}),
    )
    assert sorted(r.status_code for r in rs) == [201, 409]
    perdedora = next(r for r in rs if r.status_code == 409)
    assert perdedora.json() == {"detail": "El usuario ya tiene ese rol asignado"}
    for prohibido in ("IntegrityError", "duplicate key", "uq_", "asignacion_rol"):
        assert prohibido not in perdedora.text
    abiertas = await db_auth.filas(
        "SELECT 1 FROM asignacion_rol WHERE usuario_id = :u AND rol = 'RECEPCION' AND revocada_en IS NULL",
        u=uid,
    )
    assert len(abiertas) == 1
    assert await db_auth.contar("evento_seguridad") == antes + 1
