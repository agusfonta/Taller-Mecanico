# Proposal — C-01 `foundation-setup`

## Why

El repositorio es greenfield: hoy sólo existen la KB (`knowledge-base/`), `CHANGES.md` y la consigna; no hay una sola línea de código de la aplicación. Todos los changes siguientes (C-02 en adelante) necesitan la estructura de directorios obligatoria del PDF y una configuración tipada que **no deje arrancar la app** si faltan la clave de firma JWT o la contraseña de la base (US-002, regla dura "NUNCA secretos ni valores por defecto en código"). Es el primer change del camino crítico y no depende de ningún otro.

## What Changes

- Se crea la **estructura de directorios obligatoria** (KB 08 §Estructura de directorios): `main.py`, `app/core/`, `app/modules/{health,usuarios,clientes,repuestos,ordenes}/` (como paquetes vacíos), `migrations/` y `test/`.
- Se agrega `requirements.txt` con el stack mínimo del proyecto (FastAPI, SQLModel, SQLAlchemy async, asyncpg, Alembic, pydantic-settings, bcrypt, PyJWT, uvicorn vía `fastapi[standard]`) y un `requirements-dev.txt` para la suite de tests.
- Se crea `app/core/config.py` con `Settings` (pydantic-settings):
  - variables `POSTGRES_*` y `SQL_ECHO` (fijadas por el PDF) y `JWT_SECRET_KEY`, `JWT_EXPIRE_MINUTES`, `BCRYPT_ROUNDS`, `BCRYPT_MAX_CONCURRENCY`, `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `COOKIE_SECURE` (DD-13);
  - `JWT_SECRET_KEY` y `POSTGRES_PASSWORD` **obligatorias y sin valor por defecto**; el resto con los valores de DD-17 (30 min, 12 rondas, semáforo 4, pool 5 + 10);
  - URL de base calculada con `@computed_field`, sin exponer secretos en `repr`.
- `main.py` mínimo que valida la configuración al importarse: si falta un secreto, el proceso no arranca (fail-fast). El lifespan, motor y grupos de rutas quedan para C-02.
- `env.example` con **todas** las variables y ningún secreto; `.gitignore` que excluye `.env`.
- `alembic.ini` (plantilla asincrónica) **sin `sqlalchemy.url`**; `migrations/env.py` toma la URL de `Settings`. Los modelos y las migraciones quedan para C-03.
- `docker-compose.yml` con PostgreSQL 16 para desarrollo/tests, leyendo la contraseña del entorno (sin default).
- Tests (pytest): arranque falla sin `JWT_SECRET_KEY` / sin `POSTGRES_PASSWORD`, URL computada correctamente, defaults de DD-17, `env.example` y `alembic.ini` sin secretos, estructura presente.

## Capabilities

### New Capabilities
- `configuracion`: carga tipada de la configuración desde el entorno/`.env`, secretos obligatorios sin default, URL de base computada, valores por defecto de rendimiento/seguridad y archivos de configuración sin secretos (`env.example`, `alembic.ini`).
- `estructura-proyecto`: estructura de directorios obligatoria, dependencias declaradas y punto de entrada `main.py` que no arranca con configuración incompleta.

### Modified Capabilities
<!-- Ninguna: no existen specs previas en openspec/specs/. -->

## Impact

- **Código nuevo** (no existe nada previo): `main.py`, `app/__init__.py`, `app/core/__init__.py`, `app/core/config.py`, `app/modules/*/__init__.py`, `migrations/env.py` (+ `script.py.mako`, `versions/`), `alembic.ini`, `requirements.txt`, `requirements-dev.txt`, `pytest.ini`, `env.example`, `.gitignore`, `docker-compose.yml`, `test/conftest.py`, `test/unit/test_config.py`, `test/unit/test_estructura.py`.
- **APIs**: ninguna ruta nueva (los endpoints de salud llegan con C-04).
- **Dependencias**: se fijan las versiones mínimas del stack (KB 02).
- **Desbloquea**: C-02 (`core-db-uow`) consume `Settings` (pool, `SQL_ECHO`, URL) y C-05 consume JWT/bcrypt/cookie.
- **Governance**: BAJO.
