"""Aviso al cliente cuando su orden se termina (C-10, D7, DD-10/DD-21).

Se agenda como tarea en segundo plano DESPUES de que el servicio confirmo la transaccion: nunca
bloquea la respuesta (espera con ``asyncio.sleep``, nunca con una pausa bloqueante) ni la hace fallar. El "envio" es una
linea de log con formato fijo.
"""
import asyncio
import logging

__all__ = ["DEMORA_AVISO", "avisar_cliente"]

DEMORA_AVISO = 0.5  # segundos que simulan el envio del aviso

logger = logging.getLogger("app.modules.ordenes.avisos")


async def avisar_cliente(cliente_id: int, orden_id: int) -> None:
    """Espera ``DEMORA_AVISO`` y registra el aviso; una falla se registra y no se propaga."""
    try:
        await asyncio.sleep(DEMORA_AVISO)
        logger.info("Aviso a cliente %s: orden %s terminada", cliente_id, orden_id)
    except Exception:
        logger.exception("No se pudo avisar al cliente %s de la orden %s", cliente_id, orden_id)
