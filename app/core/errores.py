"""Traduccion de errores de la base a errores de dominio (RN-18).

Los servicios convierten un ``IntegrityError`` en un 409 con mensaje propio decidiendo por el
NOMBRE de la restriccion violada, nunca por el texto del error (que contiene tablas, columnas y
valores) y sin devolverlo jamas al cliente. Reutilizable por C-06..C-10.
"""
from sqlalchemy.exc import IntegrityError

__all__ = ["restriccion_violada"]


def restriccion_violada(exc: IntegrityError) -> str | None:
    """Nombre de la restriccion violada (p. ej. ``uq_usuario_email``) o ``None`` si no se sabe.

    Con asyncpg el nombre vive en la excepcion original (``__cause__`` del adaptador de
    SQLAlchemy); se busca con ``getattr`` defensivo para no depender de la version del driver.
    """
    actual: BaseException | None = getattr(exc, "orig", None)
    for _ in range(3):  # orig -> __cause__ -> __cause__ (profundidad acotada)
        if actual is None:
            return None
        nombre = getattr(actual, "constraint_name", None)
        if isinstance(nombre, str) and nombre:
            return nombre
        actual = actual.__cause__
    return None
