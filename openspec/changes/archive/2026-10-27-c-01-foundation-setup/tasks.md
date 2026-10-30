# Tasks — C-01 `foundation-setup`

> Proyecto greenfield: no existe código previo, por lo que no hay "safety net" que correr antes de empezar.
> Strict TDD: en cada tarea de comportamiento, primero el test en ROJO (ejecutado y fallando), luego el mínimo código en VERDE, luego triangular y refactorizar con la suite en verde.
> Skills a cargar: `python-project-structure`, `python-configuration`, `python-testing-patterns`, `fastapi`. Referencias: `design.md` (D1..D11), `specs/configuracion/spec.md`, `specs/estructura-proyecto/spec.md`.

## 1. Esqueleto y dependencias (scaffolding)

- [x] 1.1 Crear `requirements.txt` (D8: `fastapi[standard]>=0.111`, `sqlmodel>=0.0.24`, `sqlalchemy[asyncio]>=2.0`, `asyncpg>=0.30`, `alembic>=1.13`, `pydantic-settings>=2.0`, `bcrypt>=4.0`, `PyJWT>=2.8`) y `requirements-dev.txt` (`-r requirements.txt`, `pytest>=8`, `pytest-asyncio>=0.23`); verificar con `pip install -r requirements-dev.txt` en un venv de Python 3.12 sin errores.
- [x] 1.2 Crear `pytest.ini` (D9: `testpaths = test`, `pythonpath = .`, `asyncio_mode = auto`, markers `unit` e `integration`) y `test/__init__.py` vacío si hace falta para la recolección; verificar que `pytest` corre y reporta "no tests ran" sin errores de configuración.
- [x] 1.3 Crear `.gitignore` con `.env`, `.venv/`, `__pycache__/`, `.pytest_cache/`; verificar por inspección (lo cubre el test de 4.2).

## 2. Estructura de directorios obligatoria

- [x] 2.1 RED: escribir `test/unit/test_estructura.py` que verifique (a) existencia de `main.py`, `requirements.txt`, `alembic.ini`, `env.example`, `migrations/`, `test/`, `app/core/` y (b) que `app.modules.{health,usuarios,clientes,repuestos,ordenes}` se importan sin configuración (parametrizado por módulo); ejecutar y confirmar que FALLA.
- [x] 2.2 GREEN: crear `app/__init__.py`, `app/core/__init__.py`, `app/modules/__init__.py` y `app/modules/{health,usuarios,clientes,repuestos,ordenes}/__init__.py` (vacíos, sin imports que lean configuración); ejecutar `pytest test/unit/test_estructura.py -k modules` y confirmar VERDE para la parte de paquetes (los archivos raíz se completan en los grupos 3–5).
- [x] 2.3 Agregar a `test/unit/test_estructura.py` un test que lea `requirements.txt` y verifique que cada paquete de D8 aparece con versión mínima (`>=`); ejecutar y confirmar VERDE.

## 3. Configuración tipada (`app/core/config.py`)

- [x] 3.1 Crear `test/conftest.py` con un fixture `entorno_limpio` que, vía `monkeypatch`, borre del entorno las 13 variables reconocidas y limpie la caché de `get_settings` antes y después del test; y un fixture `secretos_validos` que fije `JWT_SECRET_KEY` (≥32 caracteres, generado en el test) y `POSTGRES_PASSWORD`.
- [x] 3.2 RED: en `test/unit/test_config.py`, tests `test_settings_sin_jwt_secret_key_falla` y `test_settings_sin_postgres_password_falla` (construyendo `Settings(_env_file=None)`; afirmar `ValidationError` cuyo `errors()` incluye el campo faltante); ejecutar y confirmar que FALLAN (módulo inexistente).
- [x] 3.3 GREEN: crear `app/core/config.py` con `Settings(BaseSettings)` (D1): `jwt_secret_key: SecretStr` y `postgres_password: SecretStr` sin default, `SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")`; ejecutar los tests de 3.2 y confirmar VERDE.
- [x] 3.4 TRIANGULAR secretos: parametrizar secretos vacíos (`""`) para ambas variables y `JWT_SECRET_KEY` de 31 caracteres → `ValidationError`; uno de exactamente 32 → carga OK (D2: `min_length=32` y `min_length=1`); ejecutar y confirmar VERDE.
- [x] 3.5 RED → GREEN defaults: test `test_settings_defaults_dd17` que, sólo con los secretos, afirma `jwt_expire_minutes == 30`, `bcrypt_rounds == 12`, `bcrypt_max_concurrency == 4`, `db_pool_size == 5`, `db_max_overflow == 10`, `sql_echo is False`, `cookie_secure is False`, `postgres_host == "localhost"`, `postgres_port == 5432`, `postgres_user == "taller"`, `postgres_db == "taller_db"`; luego agregar los campos al `Settings` hasta VERDE.
- [x] 3.6 TRIANGULAR entorno: test que fija `POSTGRES_HOST=db`, `POSTGRES_PORT=6543`, `JWT_EXPIRE_MINUTES=15`, `BCRYPT_ROUNDS=4` vía `monkeypatch.setenv` y verifica que se reflejan; y otro con `OTRA_COSA=1` en el entorno que carga sin error; ejecutar y confirmar VERDE.
- [x] 3.7 RED → GREEN rangos: parametrizar inválidos (`BCRYPT_ROUNDS` 3 y 32, `DB_POOL_SIZE` 0, `DB_MAX_OVERFLOW` -1, `BCRYPT_MAX_CONCURRENCY` 0, `JWT_EXPIRE_MINUTES` 0, `POSTGRES_PORT` 0 / 65536 / `abc`) esperando `ValidationError` sobre esa variable; agregar `Field(ge=..., le=...)` hasta VERDE.
- [x] 3.8 RED → GREEN duración en segundos: `jwt_expire_seconds` vale 1800 con el default y 900 con `JWT_EXPIRE_MINUTES=15` (D4); implementar y confirmar VERDE.
- [x] 3.9 RED → GREEN URL computada: `database_url == "postgresql+asyncpg://taller:secreto@localhost:5432/taller_db"` con valores simples; TRIANGULAR con contraseña `p@ss:w/rd` → contiene `p%40ss%3Aw%2Frd` y termina en `@localhost:5432/taller_db` (D3: `@computed_field(repr=False)` + `URL.create(...).render_as_string(hide_password=False)`); confirmar VERDE.
- [x] 3.10 RED → GREEN secretos ocultos: `repr(settings)` y `str(settings)` no contienen el valor de la clave ni de la contraseña; confirmar VERDE.
- [x] 3.11 RED → GREEN acceso cacheado: `get_settings()` devuelve la misma instancia en dos llamadas y `get_settings.cache_clear()` fuerza una nueva lectura (D5); implementar con `functools.lru_cache` y confirmar VERDE.
- [x] 3.12 REFACTOR: agrupar campos por sección (base, JWT, bcrypt, pool, cookie), agregar docstring que advierta no loguear `model_dump()` y definir `__all__ = ["Settings", "get_settings"]`; ejecutar `pytest test/unit/test_config.py` y confirmar VERDE tras cada paso.

## 4. Archivos de configuración versionados

- [x] 4.1 RED: en `test/unit/test_config.py`, test `test_env_example_completo_y_sin_secretos` que parsea `env.example` y verifica una entrada por cada campo de `Settings` (comparando contra `Settings.model_fields`, en mayúsculas), `JWT_SECRET_KEY=` y `POSTGRES_PASSWORD=` vacías y ninguna clave `SEED_*`; ejecutar y confirmar que FALLA.
- [x] 4.2 GREEN: crear `env.example` con las 13 variables, valores de ejemplo de KB 08/DD-17, secretos vacíos y comentarios (cómo generar la clave con `secrets.token_urlsafe(48)`; `COOKIE_SECURE=true` en producción; los tests pueden bajar `BCRYPT_ROUNDS` a 4); agregar al mismo archivo de test la verificación de que `.gitignore` incluye `.env`; confirmar VERDE.
- [x] 4.3 Crear `docker-compose.yml` (D10) con servicio `postgres:16`, `env_file: .env`, `POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?definir POSTGRES_PASSWORD}` y puerto `${POSTGRES_PORT:-5432}:5432`; verificar con `docker compose config` usando un `.env` local (no versionado) que resuelve sin error, y que sin `POSTGRES_PASSWORD` falla.

## 5. Alembic sin secretos

- [x] 5.1 RED: test `test_alembic_ini_sin_url` que lee `alembic.ini` con `configparser` (sin interpolación) y verifica que `script_location` es `migrations` y no hay `sqlalchemy.url` con valor; ejecutar y confirmar que FALLA.
- [x] 5.2 GREEN: ejecutar `alembic init -t async migrations`, eliminar la línea `sqlalchemy.url` de `alembic.ini`; confirmar VERDE.
- [x] 5.3 Modificar `migrations/env.py` (D7): tomar la URL de `get_settings().database_url` y crear el motor con `create_async_engine(url, poolclass=NullPool)` en lugar de `async_engine_from_config`/`set_main_option` (evita la interpolación de `%`); en modo offline usar la misma URL; dejar `target_metadata = None` con un comentario `# C-03: SQLModel.metadata`. Verificar que `python -c "import ast; ast.parse(open('migrations/env.py').read())"` no falla y que `alembic current` con `.env` válido y PostgreSQL de `docker compose` levantado responde sin error (no hay revisiones aún).

## 6. Punto de entrada fail-fast (`main.py`)

- [x] 6.1 RED: en `test/unit/test_main.py`, tests con `subprocess.run([sys.executable, "-c", "import main"], cwd=tmp_path, env=...)` (D6; `PYTHONPATH` = raíz del repo; entorno sin `.env`): sin `JWT_SECRET_KEY` → código ≠ 0 y stderr menciona `JWT_SECRET_KEY`; sin `POSTGRES_PASSWORD` → código ≠ 0 y stderr menciona `POSTGRES_PASSWORD`; en ambos casos stderr no contiene el valor del otro secreto; ejecutar y confirmar que FALLAN.
- [x] 6.2 GREEN: crear `main.py` que llama `get_settings()` a nivel de módulo y luego crea `app = FastAPI(title="Taller Mecánico")` sin rutas ni lifespan (C-02 los agrega); confirmar VERDE.
- [x] 6.3 TRIANGULAR: test con ambos secretos y `POSTGRES_HOST` apuntando a un host inexistente → `import main` termina con código 0 y `main.app` es una instancia de `FastAPI` (no contacta la base); confirmar VERDE. Completar los asserts pendientes de `test_estructura.py` (archivos raíz) y ejecutar toda la suite.

## 7. Verificación integral

- [x] 7.1 Ejecutar `pytest -m "not integration"` completo en un venv limpio con `requirements-dev.txt` y confirmar todo VERDE; con un `.env` válido, `fastapi dev main.py` (o `uvicorn main:app`) arranca, y sin `JWT_SECRET_KEY` aborta mostrando el nombre de la variable.
- [x] 7.2 Revisión de reglas duras: `grep` por la clave/contraseña de ejemplo en el repo no encuentra secretos en código, `alembic.ini` ni `env.example`; no hay variables `SEED_*`; no se hizo build, commit ni push.
