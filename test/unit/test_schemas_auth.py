"""Contratos de entrada de /auth: ``extra="forbid"``, normalización del correo, textos (C-05)."""
import pytest
from pydantic import ValidationError

pytestmark = pytest.mark.unit


def _registro(**cambios):
    datos = {
        "email": "ana@example.com",
        "password": "clave-de-prueba-1",
        "nombre": "Ana Pérez",
        "documento": "30111222",
        "telefono": "3815550000",
    }
    datos.update(cambios)
    return datos


# --- 7.1 RegistroEntrada ------------------------------------------------------------


def test_registro_valido_se_acepta():
    from app.modules.usuarios.schemas import RegistroEntrada

    entrada = RegistroEntrada(**_registro())
    assert entrada.email == "ana@example.com"
    assert entrada.nombre == "Ana Pérez"


@pytest.mark.parametrize("campo,valor", [("rol", "ADMIN"), ("activo", True), ("cliente_id", 1)])
def test_registro_con_campo_extra_se_rechaza(campo, valor):
    from app.modules.usuarios.schemas import RegistroEntrada

    with pytest.raises(ValidationError) as info:
        RegistroEntrada(**_registro(**{campo: valor}))
    assert info.value.errors()[0]["type"] == "extra_forbidden"


@pytest.mark.parametrize("crudo", ["Ana@Example.COM ", "  ANA@example.com", "ana@EXAMPLE.com"])
def test_registro_normaliza_el_correo(crudo):
    from app.modules.usuarios.schemas import RegistroEntrada

    assert RegistroEntrada(**_registro(email=crudo)).email == "ana@example.com"


@pytest.mark.parametrize("invalido", ["no-es-correo", "ana@", "@example.com", "", "   "])
def test_registro_con_correo_invalido_se_rechaza(invalido):
    from app.modules.usuarios.schemas import RegistroEntrada

    with pytest.raises(ValidationError):
        RegistroEntrada(**_registro(email=invalido))


@pytest.mark.parametrize("campo", ["nombre", "documento", "telefono"])
@pytest.mark.parametrize("vacio", ["", "   ", "\t\n"])
def test_registro_con_texto_vacio_o_solo_espacios_se_rechaza(campo, vacio):
    from app.modules.usuarios.schemas import RegistroEntrada

    with pytest.raises(ValidationError):
        RegistroEntrada(**_registro(**{campo: vacio}))


def test_registro_recorta_espacios_de_los_textos():
    from app.modules.usuarios.schemas import RegistroEntrada

    entrada = RegistroEntrada(**_registro(nombre="  Ana  ", documento=" 30111222 ", telefono=" 381 "))
    assert (entrada.nombre, entrada.documento, entrada.telefono) == ("Ana", "30111222", "381")


@pytest.mark.parametrize("password", ["a" * 7, "ñ" * 37, "abcdefg\x00h", ""])
def test_registro_con_password_fuera_de_politica_se_rechaza(password):
    from app.modules.usuarios.schemas import RegistroEntrada

    with pytest.raises(ValidationError):
        RegistroEntrada(**_registro(password=password))


def test_registro_con_password_de_72_bytes_se_acepta():
    from app.modules.usuarios.schemas import RegistroEntrada

    assert RegistroEntrada(**_registro(password="ñ" * 36)).password == "ñ" * 36


def test_registro_falta_un_campo_se_rechaza():
    from app.modules.usuarios.schemas import RegistroEntrada

    datos = _registro()
    del datos["documento"]
    with pytest.raises(ValidationError):
        RegistroEntrada(**datos)


def test_registro_respuesta_no_tiene_campos_de_contrasena():
    from app.modules.usuarios.schemas import RegistroRespuesta

    assert set(RegistroRespuesta.model_fields) == {"id", "email", "nombre", "cliente_id", "roles"}
