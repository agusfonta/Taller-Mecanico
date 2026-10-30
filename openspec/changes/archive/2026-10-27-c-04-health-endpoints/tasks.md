# Tasks — C-04 `health-endpoints`

> Governance **BAJO**: autonomía completa si los tests pasan.
> Strict TDD: en cada tarea de comportamiento, primero el test en ROJO (ejecutado y fallando), luego el mínimo código en VERDE, luego TRIANGULAR (≥ 2 casos por comportamiento) y REFACTOR con la suite en verde tras cada paso.
> Skills a cargar: `fastapi`, `async-python-patterns`, `python-testing-patterns`. Referencias: `design.md` (D1..D6), `specs/salud/spec.md`.
> Nunca leer ni imprimir el `.env`; los tests toman credenciales y puerto sólo vía `Settings`. Sin build, commit ni push. No tocar `openspec/changes/c-03-*` ni `CHANGES.md` (C-03 corre en paralelo).

## 1. Safety net

- [x] 1.1 Ejecutar `pytest -m "not integration"` y registrar la línea base de C-02 ("N passed"); si algo falla, DETENER y reportar como falla preexistente (no corregir).

## 2. `GET /health/live` — unitarios (`test/unit/test_health.py`)

- [x] 2.1 RED: fixtures `main_mod` (`importlib.reload(main)` con `secretos_validos`, patrón de `test_grupos_rutas.py`), `router_mod` (`app.modules.health.router`) y `cliente` (`TestClient(main_mod.crear_app(abiertos=[router_mod.router]))` sin contexto); test: `GET /health/live` → 200 y cuerpo exactamente `{"estado": "vivo"}`; ejecutar y confirmar que FALLA (módulo inexistente).
- [x] 2.2 GREEN: crear `app/modules/health/router.py` con `router = APIRouter(prefix="/health", tags=["health"])`, `EstadoVida` y `async def live()` sin dependencias (D1); confirmar VERDE.
- [x] 2.3 TRIANGULAR "no toca la base": override de `get_motor` (definirlo en `router.py` leyendo `request.app.state.engine` con `getattr(..., None)`) con un contador → `live` 200 y contador en 0; con el lifespan sin correr (`app.state` sin `engine`) → `live` 200; confirmar VERDE.

## 3. `GET /health/ready` — unitarios con dobles del motor

- [x] 3.1 RED: `MotorFalso` (`connect()` devuelve un gestor de contexto asíncrono cuya conexión registra el SQL ejecutado) vía `dependency_overrides[router_mod.get_motor]` → `GET /health/ready` 200, cuerpo `{"estado": "listo"}` y SQL registrado == `SELECT 1`; ejecutar y confirmar que FALLA.
- [x] 3.2 GREEN: `EstadoDisponibilidad`, `TIEMPO_MAXIMO_READY_SEGUNDOS = 2.0`, `base_disponible(motor)` y `async def ready(...)` según D2/D3 (503 vía `JSONResponse` con el mismo modelo; `responses={503: ...}`); confirmar VERDE.
- [x] 3.3 TRIANGULAR fallos (parametrizado): `connect()` lanza `OSError("could not connect to host-secreto:5433 as usuario-x")`; lanza `sqlalchemy.exc.OperationalError`; `get_motor` real sin lifespan (sin `engine`) → los tres 503 con cuerpo exactamente `{"estado": "no_listo"}`; para el primero, el texto de la respuesta NO contiene `host-secreto`, `5433`, `usuario-x` ni `OSError`; confirmar VERDE.
- [x] 3.4 TRIANGULAR tiempo máximo: `execute` hace `await asyncio.sleep(10)` y `monkeypatch.setattr(router_mod, "TIEMPO_MAXIMO_READY_SEGUNDOS", 0.1)` → 503 en < 1 s (medir con `time.perf_counter`); confirmar VERDE.
- [x] 3.5 TRIANGULAR log sin secretos: con `caplog`, el fallo de 3.3 registra un `WARNING` que contiene `OSError` y NO contiene `host-secreto` ni `5433`; confirmar VERDE.
- [x] 3.6 REFACTOR: `__all__`, docstrings (por qué sin servicio/UoW, por qué `Exception` y no `BaseException`, D1/D2); `pytest test/unit/test_health.py` VERDE.

## 4. Registro en el grupo abierto (`main.py`)

- [x] 4.1 RED: en `test/unit/test_health.py`, app con `crear_app(abiertos=[router_mod.router], protegidos=[r_control])` y override de `exigir_acceso` que cuenta invocaciones y lanza 401: `/health/live` y `/health/ready` (con `MotorFalso`) nunca responden 401/403 y el contador queda en 0, mientras `r_control` sí responde 401; y test que `main_mod.app` expone las rutas `/health/live` y `/health/ready` (inspección de `app.routes`); ejecutar y confirmar que FALLA (la `app` real aún no registra el router).
- [x] 4.2 GREEN: en `main.py` importar `router` de `app.modules.health.router` y construir `app = crear_app(abiertos=[router_health])` (D5); confirmar VERDE y que `test_main.py`, `test_grupos_rutas.py`, `test_lifespan.py` y `test_estructura.py` siguen VERDES.
- [x] 4.3 TRIANGULAR app real sin PostgreSQL: con `POSTGRES_HOST=127.0.0.1` y `POSTGRES_PORT` = puerto libre (socket ligado a `127.0.0.1:0` y cerrado) antes del `reload`, `with TestClient(main_mod.app)` (lifespan real) → `live` 200 y `ready` 503 `{"estado": "no_listo"}` en ≤ 3 s; confirmar VERDE.

## 5. Integración contra PostgreSQL real (`test/integration/test_health.py`)

- [x] 5.1 RED → GREEN: con `settings_db` (skip/fallo según `--exigir-db`), `with TestClient(main.app)` tras recargar `main` con el entorno real → `GET /health/ready` 200 `{"estado": "listo"}` (sin depender de tablas de C-03) y `GET /health/live` 200; confirmar VERDE con `docker compose up -d postgres`.
- [x] 5.2 TRIANGULAR recuperación: misma app; `dependency_overrides[get_motor]` con un motor real (`crear_motor(settings_db.model_copy(update={"postgres_port": puerto_libre}))`, con `dispose()` al final) → 503; quitar el override → 200 sin reiniciar la app; confirmar VERDE.

## 6. Verificación integral

- [x] 6.1 Con PostgreSQL levantado: `pytest --exigir-db` completo → todo VERDE y **0 skipped**; con el contenedor detenido: `pytest -m "not integration"` VERDE y `pytest -m integration` → SKIPPED con mensaje claro.
- [x] 6.2 Con un `.env` válido: `fastapi dev main.py`; `/health/live` → 200; `/health/ready` → 200 con la base arriba y 503 (en ≤ 3 s) tras `docker compose stop postgres`; tras `docker compose start postgres`, `/health/ready` vuelve a 200 sin reiniciar la app; `/docs` muestra ambas rutas sin candado ni dependencias.
