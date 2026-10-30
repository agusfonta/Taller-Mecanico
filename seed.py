"""Carga de los datos iniciales del taller (C-11).

Deja la base en un estado conocido y reproducible: catalogo de estados de orden, siete usuarios
(uno por rol y mas), clientes con vehiculos, repuestos con su stock inicial trazado, dos ordenes
y sus historiales. Sobre estos datos se demuestran los casos de prueba de la KB 11 (C-11 y C-12).

Puesta en marcha (desde la raiz del proyecto)::

    alembic upgrade head      # crea las tablas (el seed NO migra ni crea tablas)
    python seed.py            # carga los datos iniciales
    uvicorn main:app          # levanta la API

ADVERTENCIA: este script BORRA todos los datos de las 13 tablas de negocio (``TRUNCATE ... RESTART
IDENTITY CASCADE``) y los vuelve a cargar, en una unica transaccion: si algo falla, la base queda
exactamente como estaba. Es repetible (idempotente): cada corrida deja el mismo estado y los mismos ids.

Guarda de destino: informa ``host:puerto/base`` (nunca la contraseña) y se niega a correr (codigo 3)
si el host de ``POSTGRES_HOST`` no es local (``localhost``, ``127.0.0.1`` o ``::1``), salvo que se pase
la bandera ``--permitir-remoto``. Codigos de salida: 0 exito, 1 error al cargar, 2 configuracion
invalida, 3 destino remoto sin la bandera.

Contraseñas (DD-15): las siete contraseñas de demo son fijas y ficticias y viven SOLO en este archivo
(``CONTRASENAS_SEED``); la salida del script nunca las imprime ni imprime hashes. En la base solo se
guarda su hash bcrypt, con el costo de ``BCRYPT_ROUNDS``. Los hashes se calculan ANTES de abrir la
transaccion.
"""
import argparse
import asyncio
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, InterfaceError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlmodel import SQLModel

import app.modules.modelos  # noqa: F401  (registra los mapeos y la metadata de las 13 tablas)
from app.core.config import Settings
from app.core.database import crear_fabrica_sesiones, crear_motor
from app.core.security import ServicioContrasenas, crear_servicio_contrasenas
from app.core.unit_of_work import UnitOfWork
from app.modules.clientes.models import Cliente, Vehiculo
from app.modules.clientes.repository import ClienteRepository, VehiculoRepository
from app.modules.ordenes.models import EstadoOrden, EstadoOrdenCodigo, HistorialEstadoOrden, ItemOrden, OrdenTrabajo
from app.modules.ordenes.repository import (
    HistorialEstadoOrdenRepository,
    ItemOrdenRepository,
    OrdenRepository,
)
from app.modules.repuestos.models import HistorialPrecioRepuesto, Repuesto
from app.modules.repuestos.repository import (
    HistorialPrecioRepository,
    MovimientoStockRepository,
    RepuestoRepository,
)
from app.modules.repuestos.stock import MOTIVO_STOCK_INICIAL, mover_stock
from app.modules.usuarios.models import AsignacionRol, EventoSeguridad, Rol, Usuario
from app.modules.usuarios.repository import (
    AsignacionRolRepository,
    EventoSeguridadRepository,
    UsuarioRepository,
)

# --- Datos (D4): constantes inmutables; el orden de insercion fija los ids ------------------------


@dataclass(frozen=True)
class EstadoSeed:
    codigo: str
    descripcion: str
    posicion: int
    es_final: bool


@dataclass(frozen=True)
class UsuarioSeed:
    email: str
    nombre: str
    rol: Rol
    debe_cambiar_password: bool = False


@dataclass(frozen=True)
class VehiculoSeed:
    patente: str  # ya normalizada (mayusculas, sin espacios ni guiones)
    marca: str
    modelo: str
    anio: int


@dataclass(frozen=True)
class ClienteSeed:
    nombre: str
    documento: str
    telefono: str
    usuario_email: str | None
    vehiculos: tuple[VehiculoSeed, ...]


@dataclass(frozen=True)
class RepuestoSeed:
    codigo: str
    descripcion: str
    precio: Decimal
    stock_inicial: int


@dataclass(frozen=True)
class PrecioSeed:
    codigo: str
    precio_anterior: Decimal
    precio_nuevo: Decimal


@dataclass(frozen=True)
class ItemSeed:
    codigo: str
    cantidad: int


@dataclass(frozen=True)
class TransicionSeed:
    desde: str | None
    hasta: str
    email: str


@dataclass(frozen=True)
class OrdenSeed:
    vehiculo_id: int  # ids fijos por orden de insercion: vehiculos 1 y 2 de Laura, 3 de Jorge
    mecanico_email: str | None
    estado: str
    falla: str
    items: tuple[ItemSeed, ...]
    historial: tuple[TransicionSeed, ...]


ESTADOS: tuple[EstadoSeed, ...] = (
    EstadoSeed(EstadoOrdenCodigo.PENDIENTE.value, "Pendiente", 1, False),
    EstadoSeed(EstadoOrdenCodigo.EN_REPARACION.value, "En reparación", 2, False),
    EstadoSeed(EstadoOrdenCodigo.TERMINADA.value, "Terminada", 3, True),
    EstadoSeed(EstadoOrdenCodigo.CANCELADA.value, "Cancelada", 4, True),
)

USUARIOS: tuple[UsuarioSeed, ...] = (
    UsuarioSeed("admin@example.com", "Administrador", Rol.ADMIN),
    UsuarioSeed("admin2@example.com", "Administrador Dos", Rol.ADMIN),
    UsuarioSeed("recepcion@example.com", "Recepción Demo", Rol.RECEPCION),
    UsuarioSeed("mecanico@example.com", "Mecánico Uno", Rol.MECANICO),
    UsuarioSeed("mecanico2@example.com", "Mecánico Dos", Rol.MECANICO),
    UsuarioSeed("cliente@example.com", "Laura", Rol.CLIENTE),
    UsuarioSeed("nuevo@example.com", "Mecánico Nuevo", Rol.MECANICO, debe_cambiar_password=True),
)

# DD-15: contraseñas fijas y ficticias de demo. Viven SOLO aqui (nunca en el entorno, la documentacion ni
# los tests: los tests importan esta constante). 8 a 72 bytes UTF-8, distintas entre si, sin caracter nulo.
CONTRASENAS_SEED: dict[str, str] = {
    "admin@example.com": "Tm-z7dSQKGNkp!",
    "admin2@example.com": "Tm-VWWA7XH7nE!",
    "recepcion@example.com": "Tm-s2GJ4ePSNX!",
    "mecanico@example.com": "Tm-zNd7723KfQ!",
    "mecanico2@example.com": "Tm-QHuTVuECgL!",
    "cliente@example.com": "Tm-5VR9PF2Jn4!",
    "nuevo@example.com": "Tm-NFaVKxW9yU!",
}

AUTOR_STOCK_Y_PRECIOS = "admin@example.com"

CLIENTES: tuple[ClienteSeed, ...] = (
    ClienteSeed(
        "Laura",
        "30111222",
        "1155550101",
        "cliente@example.com",
        (
            VehiculoSeed("AB123CD", "Fiat", "Uno", 2018),
            VehiculoSeed("AC456DE", "Ford", "Fiesta", 2020),
        ),
    ),
    ClienteSeed("Jorge", "20111222", "1155550102", None, (VehiculoSeed("AD789EF", "Renault", "Clio", 2015),)),
)

REPUESTOS: tuple[RepuestoSeed, ...] = (
    RepuestoSeed("FIL-001", "Filtro de aceite", Decimal("8500.00"), 10),
    RepuestoSeed("FRE-010", "Pastillas de freno", Decimal("25000.00"), 4),
    RepuestoSeed("BUJ-001", "Bujía", Decimal("3000.00"), 2),
    RepuestoSeed("ACE-530", "Aceite por litro", Decimal("6000.00"), 20),
)

HISTORIAL_PRECIOS: tuple[PrecioSeed, ...] = (PrecioSeed("FIL-001", Decimal("8000.00"), Decimal("8500.00")),)

ORDENES: tuple[OrdenSeed, ...] = (
    OrdenSeed(
        vehiculo_id=1,
        mecanico_email=None,
        estado=EstadoOrdenCodigo.PENDIENTE.value,
        falla="Cambio de aceite y filtro",
        items=(ItemSeed("FIL-001", 1), ItemSeed("ACE-530", 4)),
        historial=(TransicionSeed(None, "PENDIENTE", "recepcion@example.com"),),
    ),
    OrdenSeed(
        vehiculo_id=3,
        mecanico_email="mecanico@example.com",
        estado=EstadoOrdenCodigo.EN_REPARACION.value,
        falla="Falla en el encendido: cambio de filtro y bujías",
        items=(ItemSeed("FIL-001", 1), ItemSeed("BUJ-001", 4)),
        historial=(
            TransicionSeed(None, "PENDIENTE", "recepcion@example.com"),
            TransicionSeed("PENDIENTE", "EN_REPARACION", "mecanico@example.com"),
        ),
    ),
)

ACTOR_EVENTO = "SISTEMA"
ACCION_EVENTO = "Carga de los datos iniciales"

HOSTS_LOCALES = frozenset({"localhost", "127.0.0.1", "::1"})
LOCK_TIMEOUT = "5s"
_FORMATO_LOCK_TIMEOUT = re.compile(r"^\d+(ms|s)$")


def calcular_total(orden: OrdenSeed) -> Decimal:
    """Suma exacta (``Decimal``) de cantidad por el precio vigente de cada repuesto."""
    precios = {r.codigo: r.precio for r in REPUESTOS}
    return sum((precios[i.codigo] * i.cantidad for i in orden.items), Decimal("0"))


# --- Errores esperables (D6) -----------------------------------------------------------------------


class SeedError(Exception):
    """Fallo esperable del seed: ``main`` lo informa sin traza y sale con codigo 1."""

    MENSAJE = "No se pudo cargar los datos iniciales."

    def __init__(self, mensaje: str | None = None) -> None:
        super().__init__(mensaje or self.MENSAJE)


class BaseSinMigrarError(SeedError):
    MENSAJE = "La base no tiene las tablas: correr `alembic upgrade head` y volver a ejecutar el seed."


class BloqueoTimeoutError(SeedError):
    MENSAJE = (
        "No se pudo vaciar las tablas porque otra conexión las tiene bloqueadas: "
        "cerrar el servidor de la API o reintentar."
    )


class BaseInalcanzableError(SeedError):
    MENSAJE = "No se pudo conectar con la base de datos: revisar POSTGRES_* y que PostgreSQL esté levantado."


_TABLA_INEXISTENTE = "42P01"
_BLOQUEO_NO_DISPONIBLE = "55P03"


def _sqlstate(exc: DBAPIError) -> str | None:
    original = getattr(exc, "orig", None)
    return getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)


def _traducir(exc: DBAPIError) -> SeedError | None:
    """Errores de la base que el seed explica; el resto (restricciones, etc.) se propaga sin tocar."""
    codigo = _sqlstate(exc)
    if codigo == _TABLA_INEXISTENTE:
        return BaseSinMigrarError()
    if codigo == _BLOQUEO_NO_DISPONIBLE:
        return BloqueoTimeoutError()
    if isinstance(exc, InterfaceError) or (codigo is not None and codigo.startswith("08")):
        return BaseInalcanzableError()
    return None


# --- Nucleo ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ResumenSeed:
    emails: tuple[str, ...]
    conteos: dict[str, int]


class SeedUoW(UnitOfWork):
    """Los repositorios existentes sobre UNA sesion; cumple ``ConStock`` (``repuestos`` + ``movimientos``)."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.usuarios = UsuarioRepository(session)
        self.asignaciones = AsignacionRolRepository(session)
        self.eventos = EventoSeguridadRepository(session)
        self.clientes = ClienteRepository(session)
        self.vehiculos = VehiculoRepository(session)
        self.repuestos = RepuestoRepository(session)
        self.movimientos = MovimientoStockRepository(session)
        self.precios = HistorialPrecioRepository(session)
        self.ordenes = OrdenRepository(session)
        self.items = ItemOrdenRepository(session)
        self.historial = HistorialEstadoOrdenRepository(session)


def _tablas_de_negocio() -> list[str]:
    """Las 13 tablas de la KB 04 desde la metadata de los modelos (nunca de la entrada del usuario)."""
    return sorted(SQLModel.metadata.tables)


async def _contar(uow: SeedUoW) -> dict[str, int]:
    preparador = uow.session.bind.dialect.identifier_preparer
    conteos: dict[str, int] = {}
    for tabla in _tablas_de_negocio():
        resultado = await uow.session.execute(text(f"SELECT count(*) FROM {preparador.quote(tabla)}"))
        conteos[tabla] = resultado.scalar_one()
    return conteos


async def _vaciar(uow: SeedUoW) -> None:
    """``SET LOCAL lock_timeout`` + ``TRUNCATE`` de las 13 tablas, dentro de la transaccion de la carga."""
    if not _FORMATO_LOCK_TIMEOUT.match(LOCK_TIMEOUT):
        raise ValueError("LOCK_TIMEOUT debe ser una cantidad con unidad ms o s")
    await uow.session.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
    preparador = uow.session.bind.dialect.identifier_preparer
    tablas = ", ".join(preparador.quote(t) for t in _tablas_de_negocio())
    await uow.session.execute(text(f"TRUNCATE {tablas} RESTART IDENTITY CASCADE"))


async def _cargar(uow: SeedUoW, hashes: dict[str, str]) -> None:
    # Catalogo primero: las ordenes y sus historiales lo referencian por FK.
    uow.session.add_all(
        [EstadoOrden(codigo=e.codigo, descripcion=e.descripcion, posicion=e.posicion, es_final=e.es_final) for e in ESTADOS]
    )
    await uow.session.flush()

    usuarios: dict[str, int] = {}
    for u in USUARIOS:
        creado = await uow.usuarios.add(
            Usuario(
                email=u.email,
                nombre=u.nombre,
                password_hash=hashes[u.email],
                activo=True,
                debe_cambiar_password=u.debe_cambiar_password,
            )
        )
        usuarios[u.email] = creado.id
    for u in USUARIOS:
        await uow.asignaciones.add(AsignacionRol(usuario_id=usuarios[u.email], rol=u.rol.value))

    for c in CLIENTES:
        cliente = await uow.clientes.add(
            Cliente(
                usuario_id=usuarios[c.usuario_email] if c.usuario_email else None,
                nombre=c.nombre,
                documento=c.documento,
                telefono=c.telefono,
            )
        )
        for v in c.vehiculos:
            await uow.vehiculos.add(
                Vehiculo(cliente_id=cliente.id, patente=v.patente, marca=v.marca, modelo=v.modelo, anio=v.anio)
            )

    autor = usuarios[AUTOR_STOCK_Y_PRECIOS]
    repuestos: dict[str, int] = {}
    for r in REPUESTOS:
        creado = await uow.repuestos.add(
            Repuesto(codigo=r.codigo, descripcion=r.descripcion, precio=r.precio, stock=0)
        )
        repuestos[r.codigo] = creado.id
        # El stock entra SOLO por mover_stock: queda el movimiento "Stock inicial" que lo respalda.
        await mover_stock(
            uow,
            repuesto_id=creado.id,
            cantidad=r.stock_inicial,
            motivo=MOTIVO_STOCK_INICIAL,
            usuario_id=autor,
        )
    for p in HISTORIAL_PRECIOS:
        await uow.precios.add(
            HistorialPrecioRepuesto(
                repuesto_id=repuestos[p.codigo],
                usuario_id=autor,
                precio_anterior=p.precio_anterior,
                precio_nuevo=p.precio_nuevo,
            )
        )

    precios = {r.codigo: r.precio for r in REPUESTOS}
    for o in ORDENES:
        orden = await uow.ordenes.add(
            OrdenTrabajo(
                vehiculo_id=o.vehiculo_id,
                mecanico_id=usuarios[o.mecanico_email] if o.mecanico_email else None,
                estado=o.estado,
                falla=o.falla,
                total=calcular_total(o),
            )
        )
        await uow.items.add_todos(
            [
                ItemOrden(
                    orden_id=orden.id,
                    repuesto_id=repuestos[i.codigo],
                    cantidad=i.cantidad,
                    precio_unitario=precios[i.codigo],
                )
                for i in o.items
            ]
        )
        for t in o.historial:
            await uow.historial.add(
                HistorialEstadoOrden(
                    orden_id=orden.id, desde_estado=t.desde, hasta_estado=t.hasta, usuario_id=usuarios[t.email]
                )
            )

    await uow.eventos.add(EventoSeguridad(actor=ACTOR_EVENTO, accion=ACCION_EVENTO))


async def cargar_datos_iniciales(
    fabrica: async_sessionmaker[AsyncSession], contrasenas: ServicioContrasenas
) -> ResumenSeed:
    """Hashea, vacia y carga en UNA transaccion; si algo falla se revierte todo (datos y secuencias)."""
    # D3: los hashes se calculan ANTES de abrir la sesion; ninguna transaccion espera a bcrypt.
    calculados = await asyncio.gather(*(contrasenas.hashear(CONTRASENAS_SEED[u.email]) for u in USUARIOS))
    hashes = {u.email: h for u, h in zip(USUARIOS, calculados, strict=True)}
    try:
        async with fabrica() as sesion:
            async with SeedUoW(sesion) as uow:
                await _vaciar(uow)
                await _cargar(uow, hashes)
                conteos = await _contar(uow)
    except DBAPIError as exc:
        traducido = _traducir(exc)
        if traducido is None:
            raise
        raise traducido from None
    except OSError:
        raise BaseInalcanzableError() from None
    return ResumenSeed(emails=tuple(u.email for u in USUARIOS), conteos=conteos)


# --- CLI (D6, D7) -------------------------------------------------------------------------------------


def destino_permitido(host: str, permitir_remoto: bool) -> bool:
    """Host local, o cualquiera con la bandera explicita ``--permitir-remoto``."""
    return permitir_remoto or host.lower() in HOSTS_LOCALES


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="seed.py", description="Carga los datos iniciales (BORRA los datos).")
    parser.add_argument(
        "--permitir-remoto",
        action="store_true",
        help="permite correr contra un host que no es local (localhost, 127.0.0.1, ::1)",
    )
    return parser


async def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        settings = Settings()
    except ValidationError as exc:
        campos = sorted({str(e["loc"][0]) for e in exc.errors() if e["loc"]})
        print("Configuración inválida (revisar el entorno o .env): " + ", ".join(campos), file=sys.stderr)
        return 2

    print(f"Destino: {settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}")
    if not destino_permitido(settings.postgres_host, args.permitir_remoto):
        print(
            f"El host {settings.postgres_host} no es local: el seed BORRA los datos y no se ejecuta. "
            "Si es el destino correcto, repetir con --permitir-remoto.",
            file=sys.stderr,
        )
        return 3

    motor = crear_motor(settings)
    try:
        resumen = await cargar_datos_iniciales(crear_fabrica_sesiones(motor), crear_servicio_contrasenas(settings))
    except SeedError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - sin detalles: el mensaje de la base puede traer parametros
        print(f"Error inesperado ({type(exc).__name__}): la carga se revirtió y la base quedó como estaba.", file=sys.stderr)
        return 1
    finally:
        await motor.dispose()

    print("Datos iniciales cargados.")
    print("Usuarios creados: " + ", ".join(resumen.emails))
    print("Contraseñas de demo: ver CONTRASENAS_SEED en seed.py")
    print("Filas por tabla: " + ", ".join(f"{t}={n}" for t, n in sorted(resumen.conteos.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
