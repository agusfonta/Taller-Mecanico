"""Registro central de modelos de tabla (C-03, D1).

Importa los cuatro ``models.py`` y expone la metadata completa. Lo importan
``migrations/env.py`` (autogenerate) y ``main.py`` (mapeos completos antes de la
primera consulta). Importarlo no requiere configuracion ni abre conexiones.
"""
from sqlmodel import SQLModel

from app.modules.clientes.models import Cliente, Vehiculo
from app.modules.ordenes.models import EstadoOrden, HistorialEstadoOrden, ItemOrden, OrdenTrabajo
from app.modules.repuestos.models import HistorialPrecioRepuesto, MovimientoStock, Repuesto
from app.modules.usuarios.models import (
    AsignacionRol,
    EventoSeguridad,
    IntentoAcceso,
    Rol,
    Usuario,
)

metadata = SQLModel.metadata

__all__ = [
    "metadata",
    "Rol",
    "Usuario",
    "AsignacionRol",
    "IntentoAcceso",
    "EventoSeguridad",
    "Cliente",
    "Vehiculo",
    "Repuesto",
    "MovimientoStock",
    "HistorialPrecioRepuesto",
    "EstadoOrden",
    "OrdenTrabajo",
    "ItemOrden",
    "HistorialEstadoOrden",
]
