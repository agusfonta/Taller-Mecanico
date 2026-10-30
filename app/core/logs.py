"""Logging de la app: hace visible en consola lo que emiten los loggers ``app.*`` (C-12, aviso-cliente).

Bajo ``uvicorn`` solo se configuran los loggers ``uvicorn.*``: el raiz queda en WARNING y el aviso
al cliente (INFO) no se veria. Se agrega un handler propio al logger ``app`` SIN tocar el raiz,
``sqlalchemy.*`` ni ``uvicorn.*``; ``propagate`` sigue en ``True`` (``caplog`` sigue capturando).
"""
import logging
from typing import TextIO

__all__ = ["NOMBRE_HANDLER", "configurar_logging_app"]

NOMBRE_HANDLER = "app-consola"
FORMATO = "%(levelname)s %(name)s: %(message)s"


def configurar_logging_app(stream: TextIO | None = None) -> None:
    """Idempotente: agrega el handler propio al logger ``app`` solo si todavia no lo tiene."""
    logger_app = logging.getLogger("app")
    logger_app.setLevel(logging.INFO)
    if any(h.get_name() == NOMBRE_HANDLER for h in logger_app.handlers):
        return
    handler = logging.StreamHandler(stream)
    handler.set_name(NOMBRE_HANDLER)
    handler.setFormatter(logging.Formatter(FORMATO))
    logger_app.addHandler(handler)
