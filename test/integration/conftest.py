"""Fixtures de integracion contra PostgreSQL real (D7).

Credenciales y puerto salen SOLO de ``Settings`` (entorno / ``.env``); nada fijo
aqui. Cada test usa un esquema efimero ``c02_prueba_<hex>`` con tablas creadas
solo desde ``BasePrueba.metadata`` (andamiaje desechable; el esquema de la app
se maneja con Alembic) y se elimina al terminar.
"""
import asyncio
import secrets
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.core.database import crear_fabrica_sesiones
from test.integration.modelos_prueba import BasePrueba

DIRECTORIO = Path(__file__).parent
RAIZ = DIRECTORIO.parents[1]
MENSAJE_SIN_DB = (
    "PostgreSQL no disponible: levantar `docker compose up -d postgres` "
    "y revisar POSTGRES_* (pytest --exigir-db convierte este skip en fallo)"
)


def pytest_collection_modifyitems(items):
    for item in items:
        if DIRECTORIO in Path(str(item.fspath)).parents:
            item.add_marker(pytest.mark.integration)


async def _ping(settings: Settings) -> None:
    motor = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with asyncio.timeout(3):
            async with motor.connect() as conexion:
                await conexion.execute(text("SELECT 1"))
    finally:
        await motor.dispose()


@pytest.fixture(scope="session")
def settings_db(request) -> Settings:
    """Settings reales si la base responde; si no, skip (o fallo con --exigir-db)."""
    exigir = request.config.getoption("--exigir-db")
    try:
        settings = Settings()
        asyncio.run(_ping(settings))
    except Exception as exc:  # noqa: BLE001 - config incompleta o base caida
        motivo = f"{MENSAJE_SIN_DB} [{type(exc).__name__}]"
        if exigir:
            pytest.fail(motivo)
        pytest.skip(motivo)
    return settings


@pytest.fixture
async def esquema_prueba(settings_db):
    """Crea el esquema efimero y lo elimina (CASCADE) al terminar."""
    nombre = f"c02_prueba_{secrets.token_hex(6)}"
    admin = create_async_engine(
        settings_db.database_url, poolclass=NullPool, isolation_level="AUTOCOMMIT"
    )
    try:
        async with admin.connect() as conexion:
            await conexion.execute(text(f'CREATE SCHEMA "{nombre}"'))
        yield nombre
    finally:
        try:
            async with admin.connect() as conexion:
                await conexion.execute(text(f'DROP SCHEMA IF EXISTS "{nombre}" CASCADE'))
        finally:
            await admin.dispose()


@pytest.fixture
async def motor_prueba(settings_db, esquema_prueba):
    motor = create_async_engine(
        settings_db.database_url,
        poolclass=NullPool,
        connect_args={"server_settings": {"search_path": esquema_prueba}},
    )
    try:
        async with motor.begin() as conexion:
            await conexion.run_sync(BasePrueba.metadata.create_all)
        yield motor
    finally:
        await motor.dispose()


@pytest.fixture
def fabrica_prueba(motor_prueba):
    return crear_fabrica_sesiones(motor_prueba)


# --- Migraciones reales (C-03, D9) ----------------------------------------------
# Los tests de restricciones/disparadores corren sobre el esquema que produce
# Alembic (no sobre create_all): el disparador solo existe en la migracion 2.


def _motor_en(settings: Settings, esquema: str):
    return create_async_engine(
        settings.database_url,
        poolclass=NullPool,
        connect_args={"server_settings": {"search_path": esquema}},
    )


async def crear_esquema(settings: Settings, prefijo: str = "c03_mig") -> str:
    nombre = f"{prefijo}_{secrets.token_hex(6)}"
    admin = create_async_engine(settings.database_url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conexion:
            await conexion.execute(text(f'CREATE SCHEMA "{nombre}"'))
    finally:
        await admin.dispose()
    return nombre


async def borrar_esquema(settings: Settings, nombre: str) -> None:
    admin = create_async_engine(settings.database_url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conexion:
            await conexion.execute(text(f'DROP SCHEMA IF EXISTS "{nombre}" CASCADE'))
    finally:
        await admin.dispose()


async def _ejecutar_alembic(settings: Settings, esquema: str, accion: str, destino: str) -> None:
    """Corre ``alembic <accion> <destino>`` en el esquema, con la conexion inyectada (D8)."""
    motor = _motor_en(settings, esquema)

    def _correr(conexion_sync) -> None:
        cfg = Config(str(RAIZ / "alembic.ini"))
        cfg.attributes["connection"] = conexion_sync
        getattr(command, accion)(cfg, destino)

    try:
        async with motor.begin() as conexion:
            await conexion.run_sync(_correr)
    finally:
        await motor.dispose()


async def aplicar_migraciones(settings: Settings, esquema: str, destino: str = "head") -> None:
    await _ejecutar_alembic(settings, esquema, "upgrade", destino)


async def revertir_migraciones(settings: Settings, esquema: str, destino: str = "base") -> None:
    await _ejecutar_alembic(settings, esquema, "downgrade", destino)


@pytest.fixture(scope="session")
def esquema_migrado(settings_db) -> str:
    """Esquema ``c03_mig_<hex>`` migrado a ``head`` UNA vez por sesion; se borra al final."""
    nombre = asyncio.run(crear_esquema(settings_db))
    try:
        asyncio.run(aplicar_migraciones(settings_db, nombre, "head"))
        yield nombre
    finally:
        asyncio.run(borrar_esquema(settings_db, nombre))


@pytest.fixture
async def conexion_migrada(settings_db, esquema_migrado):
    """Conexion sobre el esquema migrado dentro de una transaccion externa que se REVIERTE.

    Cada test parte del esquema vacio. Probar cada violacion dentro de
    ``async with conexion.begin_nested()`` (SAVEPOINT) para seguir usando la conexion.
    """
    motor = _motor_en(settings_db, esquema_migrado)
    try:
        async with motor.connect() as conexion:
            transaccion = await conexion.begin()
            try:
                yield conexion
            finally:
                await transaccion.rollback()
    finally:
        await motor.dispose()


# --- Autenticacion HTTP sobre el esquema migrado (C-05, D12) ---------------------------
# ``intento_acceso`` se confirma en su propia sesion: una transaccion externa revertida
# no sirve. Por eso el esquema es propio (``c05_auth_<hex>``) y cada test lo deja vacio
# con TRUNCATE (los disparadores de solo-agregado son por fila y no frenan TRUNCATE).


def tablas_de_negocio() -> list[str]:
    """Las 13 tablas de la KB (sin ``alembic_version``), desde la metadata de los modelos."""
    import app.modules.modelos  # noqa: F401  (registra todos los mapeos)
    from sqlmodel import SQLModel

    return sorted(SQLModel.metadata.tables)


@pytest.fixture(scope="session")
def esquema_auth(settings_db) -> str:
    """Esquema ``c05_auth_<hex>`` migrado a ``head`` UNA vez por sesion; se borra al final."""
    nombre = asyncio.run(crear_esquema(settings_db, "c05_auth"))
    try:
        asyncio.run(aplicar_migraciones(settings_db, nombre, "head"))
        yield nombre
    finally:
        asyncio.run(borrar_esquema(settings_db, nombre))


@pytest.fixture
def settings_auth(settings_db):
    """Settings reales con bcrypt de 4 rondas (suite rapida; el costo real no se prueba aqui)."""
    return settings_db.model_copy(update={"bcrypt_rounds": 4})


@pytest.fixture
async def motor_auth(settings_db, esquema_auth):
    """Motor con ``search_path`` en el esquema de auth; deja las 13 tablas vacias al terminar."""
    motor = _motor_en(settings_db, esquema_auth)
    try:
        yield motor
    finally:
        try:
            tablas = ", ".join(f'"{t}"' for t in tablas_de_negocio())
            async with motor.begin() as conexion:
                await conexion.execute(text(f"TRUNCATE {tablas} RESTART IDENTITY CASCADE"))
        finally:
            await motor.dispose()


class AyudantesAuth:
    """Siembra y conteo de filas con SQL ligado (no pasa por la API ni por los repositorios)."""

    def __init__(self, motor) -> None:
        self.motor = motor
        self._hasher = None

    async def _hash(self, password: str) -> str:
        from app.core.security import ServicioContrasenas

        if self._hasher is None:
            self._hasher = ServicioContrasenas(rondas=4, max_concurrencia=1)
        return await self._hasher.hashear(password)

    async def crear_usuario(
        self,
        email: str,
        password: str,
        roles=("CLIENTE",),
        activo: bool = True,
        debe_cambiar_password: bool = False,
        nombre: str = "Usuario de prueba",
    ) -> int:
        hash_ = await self._hash(password)
        async with self.motor.begin() as c:
            uid = (
                await c.execute(
                    text(
                        "INSERT INTO usuario (email, nombre, password_hash, activo, debe_cambiar_password) "
                        "VALUES (:e, :n, :h, :a, :d) RETURNING id"
                    ),
                    {"e": email, "n": nombre, "h": hash_, "a": activo, "d": debe_cambiar_password},
                )
            ).scalar_one()
            for rol in roles:
                await c.execute(
                    text("INSERT INTO asignacion_rol (usuario_id, rol) VALUES (:u, :r)"),
                    {"u": uid, "r": rol},
                )
        return uid

    async def asignar_rol(self, usuario_id: int, rol: str, vence_en=None, revocada_en=None) -> None:
        async with self.motor.begin() as c:
            await c.execute(
                text(
                    "INSERT INTO asignacion_rol (usuario_id, rol, vence_en, revocada_en) "
                    "VALUES (:u, :r, :v, :x)"
                ),
                {"u": usuario_id, "r": rol, "v": vence_en, "x": revocada_en},
            )

    async def insertar_intento(self, email: str, ip: str, exito: bool, cuando) -> None:
        async with self.motor.begin() as c:
            await c.execute(
                text("INSERT INTO intento_acceso (cuando, email, ip, exito) VALUES (:w, :e, :i, :x)"),
                {"w": cuando, "e": email, "i": ip, "x": exito},
            )

    async def sembrar_cliente_sin_usuario(self, documento: str) -> int:
        async with self.motor.begin() as c:
            return (
                await c.execute(
                    text(
                        "INSERT INTO cliente (usuario_id, nombre, documento, telefono) "
                        "VALUES (NULL, 'Cargado por recepcion', :d, '555') RETURNING id"
                    ),
                    {"d": documento},
                )
            ).scalar_one()

    async def contar(self, tabla: str) -> int:
        assert tabla in tablas_de_negocio(), tabla
        async with self.motor.connect() as c:
            return (await c.execute(text(f'SELECT count(*) FROM "{tabla}"'))).scalar_one()

    async def conteos(self, *tablas: str) -> dict[str, int]:
        return {t: await self.contar(t) for t in tablas}

    async def filas(self, sql: str, **params) -> list[dict]:
        async with self.motor.connect() as c:
            return [dict(f._mapping) for f in (await c.execute(text(sql), params)).all()]

    async def ejecutar(self, sql: str, **params) -> None:
        async with self.motor.begin() as c:
            await c.execute(text(sql), params)


@pytest.fixture
def db_auth(motor_auth) -> AyudantesAuth:
    return AyudantesAuth(motor_auth)


# --- App HTTP de auth sobre el esquema migrado (C-05, D12) ----------------------------------


@pytest.fixture
def ejecuciones_prueba() -> dict[str, int]:
    return {"protegida": 0, "admin": 0}


@pytest.fixture
async def app_auth(settings_auth, motor_auth, ejecuciones_prueba):
    """App armada como el lifespan, con motor en el esquema de auth y bcrypt de 4 rondas.

    Rutas de prueba (solo tests): ``/prueba/autenticada`` (grupo abierto, exige usuario),
    ``/prueba/protegida`` y ``/prueba/admin`` (grupo protegido; esta ultima con ``requiere_rol``).
    """
    from fastapi import APIRouter, Depends

    from app.core.config import get_settings
    from app.core.dependencies import UsuarioActualDep, requiere_rol
    from app.core.security import crear_servicio_contrasenas
    from app.modules.clientes.router import router as router_clientes
    from app.modules.health.router import router as router_health
    from app.modules.usuarios.models import Rol
    from app.modules.usuarios.router import router_auth, router_eventos, router_usuarios
    from main import crear_app

    abierto = APIRouter()
    protegido = APIRouter()

    @abierto.get("/prueba/autenticada")
    async def autenticada(usuario: UsuarioActualDep):
        return {"id": usuario.id}

    @protegido.get("/prueba/protegida")
    async def prueba_protegida():
        ejecuciones_prueba["protegida"] += 1
        return {"ok": True}

    @protegido.get("/prueba/admin", dependencies=[Depends(requiere_rol(Rol.ADMIN))])
    async def prueba_admin():
        ejecuciones_prueba["admin"] += 1
        return {"ok": True}

    abiertos = [router_health, abierto, router_auth]
    app = crear_app(abiertos=abiertos, protegidos=[protegido, router_usuarios, router_eventos, router_clientes])
    app.dependency_overrides[get_settings] = lambda: settings_auth
    app.state.engine = motor_auth
    app.state.session_factory = crear_fabrica_sesiones(motor_auth)
    app.state.contrasenas = crear_servicio_contrasenas(settings_auth)
    app.state.hash_ficticio = await app.state.contrasenas.hashear(secrets.token_urlsafe(32))
    return app


@pytest.fixture
async def fabrica_http(app_auth):
    """Crea clientes HTTP en proceso; cada uno con su propia IP de origen y su propia cookie jar."""
    import httpx

    creados: list[httpx.AsyncClient] = []

    def crear(ip: str = "203.0.113.5") -> httpx.AsyncClient:
        cliente = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app_auth, client=(ip, 51000)),
            base_url="http://test",
        )
        creados.append(cliente)
        return cliente

    yield crear
    for cliente in creados:
        await cliente.aclose()


@pytest.fixture
async def http(fabrica_http):
    async with fabrica_http() as cliente:
        yield cliente
