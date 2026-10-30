# Design — C-01 `foundation-setup`

## Context

- **Greenfield**: el repo sólo tiene `knowledge-base/`, `CHANGES.md`, `docs/`, `openspec/` y los `CLAUDE.md`/`AGENTS.md`. No existe `app/`, `main.py`, `requirements.txt` ni tests; no hay convenciones de código previas que respetar más allá de la KB y las reglas duras. El directorio no es (todavía) un repositorio git.
- Motivación y alcance: ver `proposal.md`. Requisitos observables: `specs/configuracion/spec.md` y `specs/estructura-proyecto/spec.md`.
- Restricciones que moldean el diseño:
  - Estructura de directorios **obligatoria** del PDF (KB 08): el directorio de tests se llama `test/` (singular) y además alojará los `*.http` y `solo_agregado.sql` de entregas posteriores.
  - Reglas duras: sin secretos ni defaults para la clave JWT y la contraseña de la base; nada de credenciales en `alembic.ini`; no crear recursos al importar (EA-08, DD-12) — el motor llega en C-02 dentro del lifespan.
  - Nombres de variables: DD-13/DD-17 (decisión del equipo aprobada por el usuario).

### Discrepancia detectada: nombres de variables en `CHANGES.md`

`CHANGES.md` §C-01 y la tabla de KB 08 §Variables de entorno listan los nombres **sugeridos** antiguos: `JWT_EXPIRE_SECONDS`, `BCRYPT_COST` y no incluyen `DB_MAX_OVERFLOW`. La decisión vigente es **DD-13/DD-17** (KB 09), que los reemplaza por `JWT_EXPIRE_MINUTES` (30 → 1800 s, coincide con `expira_en_segundos: 1800` del PDF, SU-03), `BCRYPT_ROUNDS` y agrega `DB_MAX_OVERFLOW`. Este change implementa **DD-13/DD-17**. Se recomienda re-sincronizar `CHANGES.md` y la tabla de KB 08 (fuera del alcance de este change; no se editan aquí).

## Goals / Non-Goals

**Goals:**
- Una única fuente de configuración tipada, validada al arranque (fail-fast) y testeable sin base de datos ni archivo `.env`.
- Dejar el esqueleto de paquetes listo para que C-02..C-12 sólo agreguen archivos.
- Alembic configurado con plantilla asincrónica y URL tomada de `Settings`, para que C-03 sólo tenga que enchufar `target_metadata`.

**Non-Goals:**
- Motor, fábrica de sesiones, lifespan, `get_session`, grupos de rutas (C-02).
- Modelos y migraciones (C-03); endpoints de salud (C-04); seguridad/JWT/bcrypt en uso (C-05).
- `seed.py` y `README.md` completos (changes posteriores). No se agregan variables `SEED_*` (DD-15).
- Tests de integración contra PostgreSQL: C-01 no toca la base; el `docker-compose.yml` queda listo para C-02/C-03.

## Decisions

### D1 — `Settings` con pydantic-settings, secretos como `SecretStr`
`app/core/config.py` define `Settings(BaseSettings)` con `model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False)`.
- `jwt_secret_key: SecretStr = Field(min_length=32)` y `postgres_password: SecretStr = Field(min_length=1)` **sin default** → pydantic los marca obligatorios y `ValidationError` nombra el campo.
- El resto con los defaults de DD-17 y restricciones `Field(ge=..., le=...)` (spec §Rangos válidos).
- `extra="ignore"`: el entorno del proceso trae muchas variables ajenas (`PATH`, etc.). La regla dura `extra="forbid"` aplica a **schemas de entrada de la API**, no a `Settings`.
- Sin prefijo de variables (`env_prefix=""`): el PDF fija `POSTGRES_*` y `SQL_ECHO` sin prefijo y DD-13 elige nombres explícitos. La skill `python-configuration` sugiere prefijar; se descarta para respetar el PDF.
- **Alternativas**: `os.environ` a mano (sin tipado ni validación agrupada); `str` para secretos (se filtrarían en `repr`/logs).

### D2 — Longitud mínima de 32 caracteres para `JWT_SECRET_KEY`
HS256 necesita una clave de al menos 256 bits; PyJWT ≥ 2.10 emite `InsecureKeyLengthWarning` con claves cortas. `env.example` y el README de C-12 indicarán generarla con `python -c "import secrets; print(secrets.token_urlsafe(48))"`. **Supuesto** (no está en la KB): se registra aquí; si la cátedra usa claves cortas en su `.env`, bajar el mínimo es un cambio de una línea.

### D3 — URL con `@computed_field` y `sqlalchemy.engine.URL.create`
`database_url` es un `@computed_field(repr=False)` que arma la URL con `URL.create(drivername="postgresql+asyncpg", username=..., password=..., host=..., port=..., database=...)` y la serializa con `render_as_string(hide_password=False)`. Así se escapan `@ : /` de la contraseña (spec §URL de conexión). No existe variable `DATABASE_URL`: una sola fuente evita que URL y `POSTGRES_*` diverjan.
- **Alternativa**: f-string a mano → rompe con contraseñas con caracteres especiales; descartada.
- `repr=False` y `SecretStr` cumplen spec §Los secretos no se exponen. Nota: `model_dump()` sí incluye `database_url`; no se debe loguear `model_dump()` (se documenta en el docstring).

### D4 — `jwt_expire_seconds` derivado
Propiedad (`@computed_field` o `@property`) `jwt_expire_seconds = jwt_expire_minutes * 60`, usada por C-05 para `exp`, `Max-Age` de la cookie y `expira_en_segundos`.

### D5 — Acceso cacheado `get_settings()`
`get_settings()` decorada con `functools.lru_cache` devuelve una instancia única; servirá como dependencia FastAPI (`Annotated[Settings, Depends(get_settings)]`) en changes posteriores. Los tests construyen `Settings(_env_file=None, ...)` directamente o limpian la caché (`get_settings.cache_clear()`) en un fixture, con `monkeypatch` sobre el entorno.

### D6 — Fail-fast en `main.py`
`main.py` llama `get_settings()` a nivel de módulo y luego crea `app = FastAPI(title="Taller Mecánico")`. Si falta un secreto, la importación levanta `ValidationError` y `uvicorn`/`fastapi run` no arrancan. `Settings` no crea conexiones, así que no viola EA-08. C-02 reemplazará la creación de `app` por la versión con lifespan sin cambiar este comportamiento.
- Test: `subprocess.run([sys.executable, "-c", "import main"], cwd=tmp_path, env={...sin el secreto..., "PYTHONPATH": raíz})` — `cwd` en un directorio temporal garantiza que no se lea un `.env` real del desarrollador.
- **Alternativa**: validar en el lifespan → el proceso arrancaría y fallaría tarde; descartada.

### D7 — Alembic con plantilla asincrónica, URL fuera de `alembic.ini`
Se genera con `alembic init -t async migrations`. En `alembic.ini` se **elimina** la línea `sqlalchemy.url`. `migrations/env.py` obtiene la URL de `get_settings().database_url` y crea el motor con `create_async_engine(url, poolclass=NullPool)` directamente — **no** vía `config.set_main_option(...)`, porque `configparser` interpreta `%` y una contraseña escapada (`%40`) rompería la interpolación. `target_metadata = None` hasta C-03.

### D8 — Dependencias
`requirements.txt` (producción): `fastapi[standard]>=0.111`, `sqlmodel>=0.0.24`, `sqlalchemy[asyncio]>=2.0`, `asyncpg>=0.30`, `alembic>=1.13`, `pydantic-settings>=2.0`, `bcrypt>=4.0`, `PyJWT>=2.8` (uvicorn viene con `fastapi[standard]`). `requirements-dev.txt`: `-r requirements.txt`, `pytest>=8`, `pytest-asyncio>=0.23`, `httpx` (ya transitivo). **Supuesto**: separar dev para no inflar la entrega; la KB sólo exige `requirements.txt`.

### D9 — Layout de tests dentro de `test/`
La KB obliga a `test/` (no `tests/` como sugiere la skill `python-project-structure`). Suite pytest en `test/unit/` (sin DB) y, desde C-02, `test/integration/` (PostgreSQL real). `pytest.ini` en la raíz con `testpaths = test`, `pythonpath = .`, `asyncio_mode = auto` y markers `unit`/`integration`. `test/conftest.py` ofrece un fixture que limpia del entorno todas las variables reconocidas y la caché de `get_settings`, para tests independientes.

### D10 — PostgreSQL 16 de desarrollo con docker compose
`docker-compose.yml` con `postgres:16`, `env_file: .env` y `POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?definir POSTGRES_PASSWORD}` (sin default), puerto `${POSTGRES_PORT:-5432}`. No es parte de la estructura obligatoria pero no la contradice y habilita la regla dura "tests de integración contra PostgreSQL real".

### D11 — `COOKIE_SECURE=false` por defecto
Coincide con KB 08 (`false` en dev) para que los `.http` funcionen sobre `http://localhost`. `env.example` documenta ponerlo en `true` en producción.

## Risks / Trade-offs

- [La cátedra espera otros nombres de variables] → DD-13 lo acepta; renombrar es local a `Settings`, `env.example` y tests.
- [`CHANGES.md`/KB 08 desactualizados respecto de DD-13/DD-17 confunden a futuros agentes] → se señala aquí y en el resumen del propose; re-sincronizar los documentos por separado.
- [Validar en import complica tests que importen `main`] → los tests que necesiten `main` fijan los secretos vía fixture; las pruebas de fallo usan subprocess.
- [Mínimo de 32 caracteres para la clave puede chocar con un `.env` de corrección] → error explícito que nombra la variable; ajuste trivial.
- [Un `.env` local del desarrollador contamina los tests] → `Settings(_env_file=None)` en unit tests y `cwd=tmp_path` en subprocess.
- [`model_dump()` expone `database_url` con contraseña] → documentado; nunca loguear el dump completo.

## Migration Plan

No aplica: no hay código ni datos previos. Rollback = borrar los archivos creados.

## Open Questions

- Ninguna que bloquee. La re-sincronización de `CHANGES.md`/KB 08 con DD-13/DD-17 queda como tarea documental fuera del change.
