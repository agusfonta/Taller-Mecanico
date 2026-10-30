"""Contratos de C-06: alta de personal, asignacion de rol y respuestas (tareas 2.1 a 2.4)."""
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.modules.usuarios.schemas import (
    AltaPersonalEntrada,
    AsignacionRespuesta,
    AsignarRolEntrada,
    EventoRespuesta,
    RolesUsuarioRespuesta,
    UsuarioCreadoRespuesta,
)

PW = "pw-de-prueba-1"


def alta(**cambios):
    base = {"email": "nuevo@taller.com", "nombre": "Nuevo", "password": PW, "rol": "MECANICO"}
    base.update(cambios)
    return base


# --- AltaPersonalEntrada -------------------------------------------------------------


@pytest.mark.parametrize("rol", ["ADMIN", "RECEPCION", "MECANICO"])
def test_alta_acepta_roles_de_personal(rol):
    assert AltaPersonalEntrada(**alta(rol=rol)).rol == rol


@pytest.mark.parametrize("rol", ["CLIENTE", "JEFE", "", "mecanico"])
def test_alta_rechaza_roles_que_no_son_de_personal(rol):
    with pytest.raises(ValidationError):
        AltaPersonalEntrada(**alta(rol=rol))


def test_alta_exige_rol():
    datos = alta()
    del datos["rol"]
    with pytest.raises(ValidationError):
        AltaPersonalEntrada(**datos)


def test_alta_rechaza_campo_extra():
    with pytest.raises(ValidationError):
        AltaPersonalEntrada(**alta(debe_cambiar_password=False))


def test_alta_normaliza_el_correo():
    assert AltaPersonalEntrada(**alta(email="Nuevo@Taller.COM ")).email == "nuevo@taller.com"
    assert AltaPersonalEntrada(**alta(email="  OTRO@x.org")).email == "otro@x.org"


def test_alta_rechaza_password_corta_o_de_mas_de_72_bytes():
    with pytest.raises(ValidationError):
        AltaPersonalEntrada(**alta(password="1234567"))
    with pytest.raises(ValidationError):
        AltaPersonalEntrada(**alta(password="ñ" * 37))  # 74 bytes
    assert AltaPersonalEntrada(**alta(password="ñ" * 36)).password == "ñ" * 36  # 72 bytes


def test_alta_rechaza_nombre_solo_espacios_y_lo_recorta():
    with pytest.raises(ValidationError):
        AltaPersonalEntrada(**alta(nombre="   "))
    assert AltaPersonalEntrada(**alta(nombre="  Ana  ")).nombre == "Ana"


# --- AsignarRolEntrada ---------------------------------------------------------------


def test_asignar_sin_vencimiento_es_valido():
    datos = AsignarRolEntrada(rol="RECEPCION")
    assert datos.vence_en is None and datos.rol == "RECEPCION"


def test_asignar_rechaza_vencimiento_sin_zona():
    with pytest.raises(ValidationError):
        AsignarRolEntrada(rol="MECANICO", vence_en="2030-01-01T10:00:00")


def test_asignar_rechaza_vencimiento_pasado_con_zona():
    with pytest.raises(ValidationError):
        AsignarRolEntrada(rol="MECANICO", vence_en="2020-01-01T10:00:00Z")
    pasado = (datetime.now(UTC) - timedelta(seconds=5)).isoformat()
    with pytest.raises(ValidationError):
        AsignarRolEntrada(rol="MECANICO", vence_en=pasado)


def test_asignar_acepta_futuro_con_zona_y_conserva_el_instante():
    datos = AsignarRolEntrada(rol="MECANICO", vence_en="2099-01-01T10:00:00-03:00")
    assert datos.vence_en == datetime(2099, 1, 1, 13, 0, tzinfo=UTC)
    futuro = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    assert AsignarRolEntrada(rol="CLIENTE", vence_en=futuro).vence_en is not None


@pytest.mark.parametrize("rol", ["JEFE", "", "admin"])
def test_asignar_rechaza_rol_invalido(rol):
    with pytest.raises(ValidationError):
        AsignarRolEntrada(rol=rol)


def test_asignar_acepta_los_cuatro_roles_y_rechaza_campo_extra():
    for rol in ("ADMIN", "RECEPCION", "MECANICO", "CLIENTE"):
        assert AsignarRolEntrada(rol=rol).rol == rol
    with pytest.raises(ValidationError):
        AsignarRolEntrada(rol="ADMIN", otorgada_por=1)


# --- Respuestas ----------------------------------------------------------------------


def test_respuestas_no_exponen_hash_ni_password():
    campos = set()
    for modelo in (UsuarioCreadoRespuesta, AsignacionRespuesta, RolesUsuarioRespuesta, EventoRespuesta):
        campos |= set(modelo.model_fields)
    assert not {c for c in campos if "password_hash" in c or c == "password"}


def test_formas_de_respuesta_segun_supuesto_su_c06_3():
    assert set(UsuarioCreadoRespuesta.model_fields) == {
        "id", "email", "nombre", "debe_cambiar_password", "roles"}
    assert set(AsignacionRespuesta.model_fields) == {
        "id", "usuario_id", "rol", "desde", "vence_en", "revocada_en", "otorgada_por", "vigente"}
    assert set(RolesUsuarioRespuesta.model_fields) == {
        "usuario_id", "email", "roles_vigentes", "asignaciones"}
    assert set(EventoRespuesta.model_fields) == {"id", "cuando", "actor", "accion"}
