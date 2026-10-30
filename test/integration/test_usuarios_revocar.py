"""DELETE /usuarios/{id}/roles/{rol} contra PostgreSQL real (C-06, tareas 7.1 a 7.6; casos C-07 y C-08)."""
import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.core.database import crear_fabrica_sesiones
from app.core.dependencies import UsuarioActual
from app.modules.usuarios import service
from app.modules.usuarios.models import Rol
from app.modules.usuarios.unit_of_work import UsuariosUoW
from test.integration.sesiones import admin_con_sesion, clave, usuario_con_sesion

pytestmark = pytest.mark.integration

ADMIN = "admin@taller.com"
TABLAS = ("usuario", "asignacion_rol", "evento_seguridad")
SIN_PERMISO = {"detail": "No tiene permiso para esta operación"}


@pytest.fixture
def con_ruta_recepcion(app_auth):
    """Monta, en la app de prueba, una ruta que exige RECEPCION (sin tocar conftest.py)."""
    from fastapi import APIRouter, Depends

    from app.core.dependencies import exigir_acceso, requiere_rol

    router = APIRouter(dependencies=[Depends(exigir_acceso)])

    @router.get("/prueba/recepcion", dependencies=[Depends(requiere_rol(Rol.RECEPCION))])
    async def solo_recepcion():
        return {"ok": True}

    app_auth.include_router(router)


def _hace(**kw):
    return datetime.now(UTC) - timedelta(**kw)


# --- 7.1 revocacion con sesion abierta (C-07) --------------------------------------------------


async def test_revocar_recepcion_corta_el_permiso_en_la_peticion_siguiente_con_la_misma_cookie(
    db_auth, fabrica_http, con_ruta_recepcion
):
    _, admin = await admin_con_sesion(db_auth, fabrica_http, ADMIN)
    uid, usuario, _ = await usuario_con_sesion(
        db_auth, fabrica_http, "rec@taller.com", roles=("RECEPCION", "CLIENTE")
    )
    assert (await usuario.get("/prueba/recepcion")).status_code == 200

    r = await admin.delete(f"/usuarios/{uid}/roles/RECEPCION")
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["rol"] == "RECEPCION" and c["usuario_id"] == uid
    assert c["revocada_en"] is not None and c["vigente"] is False

    r = await usuario.get("/prueba/recepcion")  # la MISMA cookie
    assert r.status_code == 403 and r.json() == SIN_PERMISO
    yo = (await usuario.get("/auth/yo")).json()
    assert yo["roles_vigentes"] == ["CLIENTE"]
    assert "RECEPCION" in yo["roles_token"]  # el token es informativo (DD-01)

    (fila,) = await db_auth.filas(
        "SELECT revocada_en FROM asignacion_rol WHERE usuario_id = :u AND rol = 'RECEPCION'", u=uid
    )
    assert fila["revocada_en"] is not None  # la fila sigue: nunca se borra
    (e,) = await db_auth.filas("SELECT actor, accion FROM evento_seguridad")
    assert e == {"actor": ADMIN, "accion": "Revocación de rol RECEPCION a rec@taller.com"}


# --- 7.3 triangular 404 / 422 --------------------------------------------------------------------


async def test_revocar_dos_veces_200_y_luego_404_con_una_fila_revocada_y_un_evento(db_auth, fabrica_http):
    _, admin = await admin_con_sesion(db_auth, fabrica_http, ADMIN)
    uid = await db_auth.crear_usuario("u@taller.com", clave(), roles=("MECANICO",))
    assert (await admin.delete(f"/usuarios/{uid}/roles/MECANICO")).status_code == 200
    r = await admin.delete(f"/usuarios/{uid}/roles/MECANICO")
    assert r.status_code == 404 and r.json() == {"detail": "El usuario no tiene ese rol asignado"}
    filas = await db_auth.filas("SELECT revocada_en FROM asignacion_rol WHERE usuario_id = :u", u=uid)
    assert len(filas) == 1 and filas[0]["revocada_en"] is not None
    assert await db_auth.contar("evento_seguridad") == 1


async def test_revocar_rol_nunca_asignado_404_sin_evento_y_usuario_inexistente_404(db_auth, fabrica_http):
    _, admin = await admin_con_sesion(db_auth, fabrica_http, ADMIN)
    uid = await db_auth.crear_usuario("u@taller.com", clave(), roles=("CLIENTE",))
    r = await admin.delete(f"/usuarios/{uid}/roles/RECEPCION")
    assert r.status_code == 404 and r.json() == {"detail": "El usuario no tiene ese rol asignado"}
    r = await admin.delete("/usuarios/999999/roles/RECEPCION")
    assert r.status_code == 404 and r.json() == {"detail": "Usuario no encontrado"}
    assert await db_auth.contar("evento_seguridad") == 0


async def test_rol_fuera_del_vocabulario_o_id_no_entero_en_la_ruta_dan_422(db_auth, fabrica_http):
    _, admin = await admin_con_sesion(db_auth, fabrica_http, ADMIN)
    assert (await admin.delete("/usuarios/1/roles/JEFE")).status_code == 422
    assert (await admin.delete("/usuarios/abc/roles/MECANICO")).status_code == 422
    assert (await admin.delete("/usuarios/1/roles/mecanico")).status_code == 422


async def test_revocar_una_asignacion_abierta_pero_vencida_da_200(db_auth, fabrica_http):
    _, admin = await admin_con_sesion(db_auth, fabrica_http, ADMIN)
    uid = await db_auth.crear_usuario("u@taller.com", clave(), roles=())
    await db_auth.asignar_rol(uid, "MECANICO", vence_en=_hace(days=1))
    r = await admin.delete(f"/usuarios/{uid}/roles/MECANICO")
    assert r.status_code == 200 and r.json()["vigente"] is False and r.json()["revocada_en"] is not None
    assert await db_auth.contar("evento_seguridad") == 1


# --- 7.4 autoproteccion (C-08, RN-05) -------------------------------------------------------------


async def test_el_admin_no_puede_revocarse_su_propio_admin_y_sigue_siendo_admin(db_auth, fabrica_http):
    admin_id, admin = await admin_con_sesion(db_auth, fabrica_http, ADMIN)
    r = await admin.delete(f"/usuarios/{admin_id}/roles/ADMIN")
    assert r.status_code == 409 and r.json() == {"detail": "No puede revocarse su propio rol ADMIN"}
    (fila,) = await db_auth.filas("SELECT revocada_en FROM asignacion_rol WHERE usuario_id = :u", u=admin_id)
    assert fila["revocada_en"] is None
    assert await db_auth.contar("evento_seguridad") == 0
    assert (await admin.get("/eventos")).status_code == 200


async def test_con_dos_admin_uno_revoca_al_otro_y_el_revocado_pierde_el_acceso(db_auth, fabrica_http):
    _, a = await admin_con_sesion(db_auth, fabrica_http, "a@taller.com")
    b_id, b = await admin_con_sesion(db_auth, fabrica_http, "b@taller.com")
    assert (await b.get("/eventos")).status_code == 200
    assert (await a.delete(f"/usuarios/{b_id}/roles/ADMIN")).status_code == 200
    r = await b.get("/eventos")
    assert r.status_code == 403 and r.json() == SIN_PERMISO
    assert (await a.get("/eventos")).status_code == 200


async def test_un_admin_puede_revocarse_su_propio_mecanico(db_auth, fabrica_http):
    admin_id, admin = await admin_con_sesion(db_auth, fabrica_http, ADMIN)
    await db_auth.asignar_rol(admin_id, "MECANICO")
    r = await admin.delete(f"/usuarios/{admin_id}/roles/MECANICO")
    assert r.status_code == 200 and r.json()["vigente"] is False
    assert (await admin.get("/eventos")).status_code == 200


async def test_revocar_un_admin_inactivo_es_posible_porque_el_actor_sigue_siendo_admin_vigente(
    db_auth, fabrica_http
):
    _, admin = await admin_con_sesion(db_auth, fabrica_http, ADMIN)
    inactivo = await db_auth.crear_usuario("i@taller.com", clave(), roles=("ADMIN",), activo=False)
    r = await admin.delete(f"/usuarios/{inactivo}/roles/ADMIN")
    assert r.status_code == 200


async def _uow_nuevo(motor):
    fabrica = crear_fabrica_sesiones(motor)
    sesion = fabrica()
    return sesion, UsuariosUoW(sesion)


def _actor(uid, email):
    return UsuarioActual(
        id=uid, email=email, nombre="x", debe_cambiar_password=False,
        roles_vigentes=frozenset({Rol.ADMIN}), roles_token=("ADMIN",),
    )


async def test_el_servicio_rechaza_dejar_al_sistema_sin_admins_aunque_exista_uno_inactivo(db_auth, motor_auth):
    """Guarda por conteo (no por identidad): el actor ya no es admin vigente (perdio ADMIN en carrera)."""
    unico = await db_auth.crear_usuario("unico@taller.com", clave(), roles=("ADMIN",))
    await db_auth.crear_usuario("inactivo@taller.com", clave(), roles=("ADMIN",), activo=False)
    actor = await db_auth.crear_usuario("actor@taller.com", clave(), roles=("MECANICO",))
    sesion, uow = await _uow_nuevo(motor_auth)
    async with sesion:
        with pytest.raises(service.UltimoAdminError) as exc:
            await service.revocar_rol(uow, _actor(actor, "actor@taller.com"), unico, Rol.ADMIN)
    assert exc.value.mensaje == "El sistema debe conservar al menos un administrador"
    (fila,) = await db_auth.filas("SELECT revocada_en FROM asignacion_rol WHERE usuario_id = :u", u=unico)
    assert fila["revocada_en"] is None and await db_auth.contar("evento_seguridad") == 0


async def test_el_servicio_decide_auto_revocacion_antes_que_asignacion_inexistente(db_auth, motor_auth):
    solo_cliente = await db_auth.crear_usuario("c@taller.com", clave(), roles=("CLIENTE",))
    sesion, uow = await _uow_nuevo(motor_auth)
    async with sesion:
        with pytest.raises(service.AutoRevocacionAdminError):
            await service.revocar_rol(uow, _actor(solo_cliente, "c@taller.com"), solo_cliente, Rol.ADMIN)


# --- 7.5 carrera: dos admin se revocan mutuamente ---------------------------------------------------


@pytest.mark.parametrize("repeticion", range(5))
async def test_dos_admin_revocandose_a_la_vez_dan_200_y_409_y_queda_exactamente_un_admin(
    db_auth, fabrica_http, repeticion
):
    a_id, a = await admin_con_sesion(db_auth, fabrica_http, f"a{repeticion}@taller.com")
    b_id, b = await admin_con_sesion(db_auth, fabrica_http, f"b{repeticion}@taller.com")
    rs = await asyncio.gather(
        a.delete(f"/usuarios/{b_id}/roles/ADMIN"),
        b.delete(f"/usuarios/{a_id}/roles/ADMIN"),
    )
    assert sorted(r.status_code for r in rs) == [200, 409], [r.text for r in rs]
    perdedora = next(r for r in rs if r.status_code == 409)
    assert perdedora.json() == {"detail": "El sistema debe conservar al menos un administrador"}
    vigentes = await db_auth.filas(
        "SELECT usuario_id FROM asignacion_rol WHERE rol = 'ADMIN' AND revocada_en IS NULL"
    )
    assert len(vigentes) == 1
    assert await db_auth.contar("evento_seguridad") == 1
