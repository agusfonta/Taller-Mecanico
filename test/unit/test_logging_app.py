"""Logging de la app (C-12, spec aviso-cliente): el aviso al cliente debe verse en la consola."""
import io
import logging

import pytest

from app.core.logs import NOMBRE_HANDLER, configurar_logging_app
from main import crear_app

pytestmark = pytest.mark.unit

LOGGER_AVISOS = "app.modules.ordenes.avisos"


@pytest.fixture(autouse=True)
def logging_limpio():
    """Deja el logger ``app`` como estaba: estos tests lo configuran de verdad."""
    logger_app = logging.getLogger("app")
    handlers_antes = list(logger_app.handlers)
    nivel_antes = logger_app.level
    # importar ``main`` ya creo la app y con ella el handler propio: cada test parte sin el
    logger_app.handlers[:] = [h for h in handlers_antes if h.get_name() != NOMBRE_HANDLER]
    yield
    logger_app.handlers[:] = handlers_antes
    logger_app.setLevel(nivel_antes)


def test_el_aviso_info_llega_a_un_handler_propio_de_app():
    salida = io.StringIO()
    configurar_logging_app(salida)

    logging.getLogger(LOGGER_AVISOS).info("Aviso a cliente %s: orden %s terminada", 2, 2)

    assert salida.getvalue() == "INFO app.modules.ordenes.avisos: Aviso a cliente 2: orden 2 terminada\n"


def test_otros_loggers_de_app_tambien_se_muestran_y_los_ajenos_no():
    salida = io.StringIO()
    configurar_logging_app(salida)

    logging.getLogger("app.core.otro").warning("algo")
    logging.getLogger("terceros.libreria").info("ruido ajeno")

    assert salida.getvalue() == "WARNING app.core.otro: algo\n"


def test_el_debug_no_se_muestra():
    salida = io.StringIO()
    configurar_logging_app(salida)

    logging.getLogger(LOGGER_AVISOS).debug("detalle")

    assert salida.getvalue() == ""


def test_configurar_dos_veces_no_duplica_la_linea():
    salida = io.StringIO()
    configurar_logging_app(salida)
    configurar_logging_app(salida)
    configurar_logging_app(io.StringIO())

    logging.getLogger(LOGGER_AVISOS).info("una sola vez")

    assert salida.getvalue().count("una sola vez") == 1
    propios = [h for h in logging.getLogger("app").handlers if h.get_name() == NOMBRE_HANDLER]
    assert len(propios) == 1


def test_no_cambia_el_nivel_de_sqlalchemy_ni_de_uvicorn():
    antes = {
        n: (logging.getLogger(n).level, list(logging.getLogger(n).handlers))
        for n in ("sqlalchemy.engine", "uvicorn", "uvicorn.access", "")
    }

    configurar_logging_app(io.StringIO())

    despues = {
        n: (logging.getLogger(n).level, list(logging.getLogger(n).handlers))
        for n in ("sqlalchemy.engine", "uvicorn", "uvicorn.access", "")
    }
    assert despues == antes


def test_caplog_sigue_capturando_el_aviso_porque_propaga(caplog):
    configurar_logging_app(io.StringIO())
    assert logging.getLogger("app").propagate is True

    with caplog.at_level(logging.INFO, logger=LOGGER_AVISOS):
        logging.getLogger(LOGGER_AVISOS).info("Aviso a cliente 1: orden 1 terminada")

    assert "Aviso a cliente 1: orden 1 terminada" in caplog.text


def test_crear_app_configura_el_logging():
    crear_app()

    nombres = [h.get_name() for h in logging.getLogger("app").handlers]
    assert NOMBRE_HANDLER in nombres
