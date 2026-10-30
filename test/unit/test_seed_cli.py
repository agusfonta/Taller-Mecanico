"""Guarda de destino y comportamiento de ``main`` de ``seed.py`` (C-11, 2.3; sin base de datos).

``main`` y ``crear_motor`` se sustituyen: ningun test de este archivo abre una conexion.
"""
import pytest

import seed


@pytest.fixture
def sin_env_file(monkeypatch, tmp_path):
    """``Settings()`` busca ``.env`` en el directorio actual: uno vacio evita leer el del desarrollador."""
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def motor_prohibido(monkeypatch):
    llamadas: list[object] = []

    def crear_motor(settings):
        llamadas.append(settings)
        raise AssertionError("no debe crearse el motor")

    monkeypatch.setattr(seed, "crear_motor", crear_motor)
    return llamadas


# --- destino_permitido (pura) -------------------------------------------------------------


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "::1", "LOCALHOST", "LocalHost"])
def test_hosts_locales_se_permiten_en_cualquier_caja(host):
    assert seed.destino_permitido(host, False) is True


@pytest.mark.parametrize("host", ["db.ejemplo.com", "10.0.0.5", "127.0.0.2", "localhost.evil.com", ""])
def test_otro_host_no_se_permite_sin_la_bandera(host):
    assert seed.destino_permitido(host, False) is False


@pytest.mark.parametrize("host", ["db.ejemplo.com", "10.0.0.5", "localhost"])
def test_otro_host_con_la_bandera_se_permite(host):
    assert seed.destino_permitido(host, True) is True


# --- main: guarda y configuracion ----------------------------------------------------------


async def test_host_remoto_sin_bandera_sale_con_3_menciona_la_bandera_y_no_crea_motor(
    secretos_validos, sin_env_file, motor_prohibido, monkeypatch, capsys
):
    monkeypatch.setenv("POSTGRES_HOST", "db.ejemplo.com")
    codigo = await seed.main([])
    salida = capsys.readouterr()
    assert codigo == 3
    assert "--permitir-remoto" in salida.out + salida.err
    assert motor_prohibido == []
    assert secretos_validos["POSTGRES_PASSWORD"] not in salida.out + salida.err


async def test_host_remoto_otro_nombre_tambien_sale_con_3(
    secretos_validos, sin_env_file, motor_prohibido, monkeypatch, capsys
):
    monkeypatch.setenv("POSTGRES_HOST", "10.1.2.3")
    codigo = await seed.main([])
    assert codigo == 3
    assert motor_prohibido == []
    assert "10.1.2.3" in capsys.readouterr().err


async def test_configuracion_invalida_sale_con_2_sin_traza_ni_secretos(
    entorno_limpio, sin_env_file, motor_prohibido, capsys
):
    secreto = "pw-no-debe-salir-en-la-salida"
    entorno_limpio.setenv("POSTGRES_PASSWORD", secreto)
    entorno_limpio.setenv("JWT_SECRET_KEY", "corta")  # < 32: Settings() levanta ValidationError
    codigo = await seed.main([])
    salida = capsys.readouterr()
    texto = salida.out + salida.err
    assert codigo == 2
    assert "Traceback" not in texto
    assert secreto not in texto
    assert "corta" not in texto
    assert motor_prohibido == []


async def test_configuracion_incompleta_sale_con_2(entorno_limpio, sin_env_file, motor_prohibido, capsys):
    codigo = await seed.main([])
    salida = capsys.readouterr()
    assert codigo == 2
    assert "Traceback" not in salida.out + salida.err
    assert motor_prohibido == []


# --- 5.1 main: camino feliz, errores conocidos y limpieza ---------------------------------------


class _MotorFalso:
    def __init__(self) -> None:
        self.eliminado = 0

    async def dispose(self) -> None:
        self.eliminado += 1


@pytest.fixture
def nucleo_falso(monkeypatch, secretos_validos, sin_env_file):
    """Sustituye motor, fabrica, contrasenas y nucleo: ``main`` corre entero sin tocar una base."""
    estado: dict = {"motor": _MotorFalso(), "llamadas": [], "resultado": None, "error": None}
    monkeypatch.setenv("POSTGRES_HOST", "localhost")
    monkeypatch.setenv("POSTGRES_PORT", "5999")
    monkeypatch.setenv("POSTGRES_DB", "base_demo")

    monkeypatch.setattr(seed, "crear_motor", lambda settings: estado["motor"])
    monkeypatch.setattr(seed, "crear_fabrica_sesiones", lambda motor: ("fabrica", motor))
    monkeypatch.setattr(seed, "crear_servicio_contrasenas", lambda settings: "contrasenas")

    async def nucleo(fabrica, contrasenas):
        estado["llamadas"].append((fabrica, contrasenas))
        if estado["error"] is not None:
            raise estado["error"]
        return estado["resultado"]

    monkeypatch.setattr(seed, "cargar_datos_iniciales", nucleo)
    estado["resultado"] = seed.ResumenSeed(
        emails=tuple(u.email for u in seed.USUARIOS), conteos={"usuario": 7, "cliente": 2}
    )
    return estado


async def test_host_local_informa_destino_sin_contrasena_y_llama_al_nucleo_con_la_fabrica_del_motor(
    nucleo_falso, secretos_validos, capsys
):
    codigo = await seed.main([])
    salida = capsys.readouterr()
    assert codigo == 0
    assert "localhost:5999/base_demo" in salida.out
    assert secretos_validos["POSTGRES_PASSWORD"] not in salida.out + salida.err
    assert nucleo_falso["llamadas"] == [(("fabrica", nucleo_falso["motor"]), "contrasenas")]
    assert nucleo_falso["motor"].eliminado == 1


async def test_exito_imprime_los_emails_y_nunca_contrasenas_ni_hashes(nucleo_falso, capsys):
    codigo = await seed.main([])
    texto = capsys.readouterr().out
    assert codigo == 0
    assert all(u.email in texto for u in seed.USUARIOS)
    assert not [c for c in seed.CONTRASENAS_SEED.values() if c in texto]
    assert "$2b$" not in texto and "$2a$" not in texto


async def test_la_bandera_permite_un_host_remoto_y_corre_el_nucleo(nucleo_falso, monkeypatch, capsys):
    monkeypatch.setenv("POSTGRES_HOST", "db.ejemplo.com")
    assert await seed.main(["--permitir-remoto"]) == 0
    assert "db.ejemplo.com:5999/base_demo" in capsys.readouterr().out
    assert len(nucleo_falso["llamadas"]) == 1


@pytest.mark.parametrize(
    ("error", "fragmento"),
    [
        (seed.BaseSinMigrarError(), "alembic upgrade head"),
        (seed.BloqueoTimeoutError(), "reintentar"),
        (seed.BaseInalcanzableError(), "conectar"),
    ],
)
async def test_errores_conocidos_dan_codigo_1_sin_traza_y_liberan_el_motor(nucleo_falso, capsys, error, fragmento):
    nucleo_falso["error"] = error
    codigo = await seed.main([])
    salida = capsys.readouterr()
    assert codigo == 1
    assert fragmento in salida.err
    assert "Traceback" not in salida.out + salida.err
    assert nucleo_falso["motor"].eliminado == 1


async def test_un_error_inesperado_da_codigo_1_sin_detalles_ni_traza_y_libera_el_motor(nucleo_falso, capsys):
    nucleo_falso["error"] = RuntimeError("detalle-sensible-con-parametros")
    codigo = await seed.main([])
    salida = capsys.readouterr()
    assert codigo == 1
    assert "RuntimeError" in salida.err
    assert "detalle-sensible-con-parametros" not in salida.out + salida.err
    assert "Traceback" not in salida.out + salida.err
    assert nucleo_falso["motor"].eliminado == 1


async def test_cada_corrida_libera_el_motor_una_vez(nucleo_falso):
    await seed.main([])
    await seed.main([])
    assert nucleo_falso["motor"].eliminado == 2
