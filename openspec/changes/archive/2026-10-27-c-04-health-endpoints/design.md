# Design — C-04 `health-endpoints`

> Governance **BAJO** (CHANGES.md §C-04): autonomía completa si los tests pasan. No requiere aprobación humana previa a `/opsx:apply`; las decisiones no obvias se reportan en el resumen del apply.

## Context

- Estado tras C-02 (observado en el código):
  - `main.py`: `settings = get_settings()` a nivel de módulo (fail-fast); `lifespan` publica `app.state.engine` (`crear_motor`, con `pool_pre_ping=True`) y `app.state.session_factory`, y hace `dispose()` al salir; `crear_app(abiertos, protegidos)` arma el grupo abierto (sin dependencias) y el protegido (`Depends(exigir_acceso)`, que hoy **falla cerrado** con 401); `app = crear_app()` sin routers.
  - `app/core/database.py`: `crear_motor`, `crear_fabrica_sesiones`, `get_session`/`SessionDep`. El motor es perezoso: el arranque no contacta la base (spec `sesion-base-datos` §Arranque sin base disponible).
  - `app/modules/health/` existe sólo con `__init__.py` vacío (C-01).
  - Tests: `test/conftest.py` (`entorno_limpio`, `secretos_validos`, `--exigir-db`); `test/integration/conftest.py` (`settings_db` hace ping con `asyncio.timeout(3)` y salta/falla si no hay base; esquema efímero sólo para tablas de prueba). Patrón unitario de `test/unit/test_grupos_rutas.py`: `importlib.reload(main)` con `secretos_validos` + `TestClient(crear_app(...))` + `dependency_overrides`.
- Motivación y alcance: ver `proposal.md`. Requisitos observables: `specs/salud/spec.md`.
- Restricciones: reglas duras de `CLAUDE.md` (todo `async def`, ninguna llamada bloqueante, nada de recursos creados al importar, tests de integración contra PostgreSQL real); KB 08 §Estructura (`health/ (router.py)`) y §Patrones (lifespan / recursos en `app.state`); DD-07 (dos grupos); DD-12 (motor en el lifespan); KB 06 US-001; KB 03 (salud: "Cualquiera"); KB 07 flujo de cambio obligatorio (`/health/*` exento).

### Discrepancias detectadas con `CHANGES.md` / KB / pedido

1. El pedido de planificación sugería `router.py` + `service.py` + `schemas.py`. **KB 08 fija `health/ (router.py)`** (y KB 02: "`health` | sólo `router.py`"). Se respeta la KB: un único `router.py` (ver D1). No hay regla de negocio, ni transacción, ni cuerpo de entrada que justifique servicio, UoW o contratos de entrada.
2. `CHANGES.md` no fija el **cuerpo** de las respuestas ni el **tiempo máximo** de `ready`; la KB tampoco. Se deciden en D3/D4 y se fijan como contrato en la spec (cuerpo propio fijo, 503 en ≤ 3 s).
3. KB 07 (flujo de cambio obligatorio) exime `/health/*` del 403: no requiere código en C-04 porque el control vive en el grupo protegido y salud está en el abierto; queda como escenario en la spec para que C-05 no lo rompa.

## Goals / Non-Goals

**Goals:**
- `live` y `ready` con semántica separada: `live` jamás toca la base; `ready` responde rápido (acotado) y nunca filtra detalles internos.
- Primeras rutas reales registradas en el grupo abierto, verificando de punta a punta `crear_app` + lifespan + motor.
- Cero dependencia de C-03 (ni modelos, ni tablas, ni migraciones).

**Non-Goals:**
- Chequeos de dependencias más allá de PostgreSQL, métricas, versión de esquema/migraciones aplicadas (`alembic current`), `HEAD`/`startup` probes.
- Hacer configurable el tiempo máximo por variable de entorno (DD-13 cerró la lista de variables; ver D4).
- Endpoints de salud autenticados o con detalle para administradores.

## Decisions

### D1 — Módulo `health`: sólo `router.py`, sin servicio ni UoW
```python
# app/modules/health/router.py
router = APIRouter(prefix="/health", tags=["health"])
TIEMPO_MAXIMO_READY_SEGUNDOS: float = 2.0

class EstadoVida(BaseModel):          estado: Literal["vivo"]
class EstadoDisponibilidad(BaseModel): estado: Literal["listo", "no_listo"]

def get_motor(request: Request) -> AsyncEngine | None
async def base_disponible(motor: AsyncEngine | None) -> bool
@router.get("/live", response_model=EstadoVida)
async def live() -> EstadoVida
@router.get("/ready", response_model=EstadoDisponibilidad, responses={503: {"model": EstadoDisponibilidad}})
async def ready(motor: Annotated[AsyncEngine | None, Depends(get_motor)]) -> EstadoDisponibilidad | JSONResponse
```
- **Por qué sin servicio/UoW**: la regla "router construye el UoW, servicio lo abre" aplica a operaciones de negocio con transacción. `ready` es una sonda de infraestructura de sólo lectura (`SELECT 1`) sin reglas ni escrituras; envolverla en un UoW agregaría un `COMMIT` sin sentido. KB 08 lo confirma al fijar sólo `router.py`.
- **Contratos de salida** (`EstadoVida`, `EstadoDisponibilidad`) son `BaseModel` de Pydantic, separados de cualquier modelo de tabla. `extra="forbid"` no aplica: no hay esquemas de **entrada** (ningún cuerpo ni query). Viven en `router.py` para respetar la estructura de la KB.
- `live` **no declara dependencias**: no recibe `Request`, motor ni sesión → por construcción no puede tocar la base.
- **Alternativa**: `service.py` + `schemas.py` (patrón de los módulos de dominio) → contradice KB 08 y agrega capas vacías; descartada.

### D2 — Cómo se chequea la base: conexión del motor del lifespan, `SELECT 1`, tiempo acotado
```python
async def base_disponible(motor):
    if motor is None:
        return False
    try:
        async with asyncio.timeout(TIEMPO_MAXIMO_READY_SEGUNDOS):
            async with motor.connect() as conexion:
                await conexion.execute(text("SELECT 1"))
    except Exception as exc:          # NO BaseException: CancelledError se propaga
        logger.warning("Health ready: base no disponible (%s)", type(exc).__name__)
        return False
    return True
```
- **`get_motor`** lee `request.app.state.engine` (creado por el lifespan, DD-12) con `getattr(..., None)`: si el lifespan no corrió, `ready` responde 503 en vez de 500. Es una dependencia para que los tests la sustituyan con `dependency_overrides` (dobles de motor sin base).
- **`motor.connect()` y no `SessionDep`**: la sesión ORM abriría una transacción y pasaría por la fábrica sin aportar nada; la conexión Core es la sonda mínima y devuelve la conexión al pool al salir. Usa el **mismo pool** que la app: si el pool está agotado y no se libera a tiempo, `ready` da 503, lo que es correcto (la instancia no puede atender más). `pool_pre_ping=True` (C-02) descarta conexiones muertas tras un reinicio del contenedor, lo que habilita la **recuperación sin reiniciar** la app.
- **`asyncio.timeout`** envuelve checkout + conexión + consulta: sin él, asyncpg espera hasta 60 s por defecto y `pool_timeout` 30 s, inaceptable para una sonda. La cancelación por tiempo es cooperativa y libera la conexión (el `async with` la cierra/invalida).
- **Captura amplia de `Exception`**: para una sonda, *cualquier* fallo al alcanzar la base (`OSError`, `OperationalError`/`DBAPIError`, `TimeoutError`, `InterfaceError` de asyncpg, `socket.gaierror`) significa "no listo"; un 500 por un tipo no previsto sería un falso diagnóstico. **No** se captura `BaseException`: `CancelledError` (cliente que corta) se propaga (skill async-python-patterns).
- **Log sin secretos**: sólo el **nombre de la clase** de la excepción, nunca `str(exc)` (asyncpg incluye host/puerto/usuario en el mensaje) ni la URL. `logging` estándar a nivel `warning`; no es una llamada bloqueante relevante.
- SQL `text("SELECT 1")` literal, sin parámetros ni concatenación.
- **Alternativa**: reutilizar `_ping` de `test/integration/conftest.py` → crea un motor nuevo por llamada (`NullPool`) y no prueba el pool real de la app; descartada.

### D3 — Cuerpos y códigos
| Ruta | Condición | Código | Cuerpo |
|---|---|---|---|
| `GET /health/live` | siempre | 200 | `{"estado": "vivo"}` |
| `GET /health/ready` | `SELECT 1` OK | 200 | `{"estado": "listo"}` |
| `GET /health/ready` | falla / tiempo / sin motor | 503 | `{"estado": "no_listo"}` |
- El 503 se devuelve con `JSONResponse(status_code=503, content=EstadoDisponibilidad(estado="no_listo").model_dump())`, misma forma que el 200 para que un monitor parsee un único contrato. **Alternativa**: `HTTPException(503, detail=...)` → cuerpo `{"detail": ...}` distinto del 200; descartada. Sin `Retry-After` (no hay estimación honesta).

### D4 — Tiempo máximo: constante de módulo de 2 s
- `TIEMPO_MAXIMO_READY_SEGUNDOS = 2.0` en `router.py`; la spec promete respuesta en ≤ 3 s (1 s de margen para el resto de la petición).
- **Por qué no variable de entorno**: DD-13/DD-17 fijaron el conjunto de variables y la spec `configuracion` lo verifica; agregar una obligaría a modificar esa capability por un valor que no necesita ajuste en el TP. Los tests lo bajan con `monkeypatch.setattr(router_mod, "TIEMPO_MAXIMO_READY_SEGUNDOS", 0.1)` (por eso `base_disponible` lee la constante del módulo en tiempo de llamada).

### D5 — Registro en el grupo abierto
```python
# main.py
from app.modules.health.router import router as router_health
app = crear_app(abiertos=[router_health])
```
- `crear_app` no cambia: el router entra al grupo abierto, que no lleva `exigir_acceso` (DD-07). C-05 reemplazará el cuerpo de `exigir_acceso` (incluido el bloqueo por cambio obligatorio) sin afectar `/health/*`.
- Importar `router.py` no crea recursos ni lee configuración (sólo FastAPI/SQLAlchemy/Pydantic): se preserva la spec `estructura-proyecto` (los módulos importan sin configuración) y `sesion-base-datos` (importar no crea motor).
- C-06+ agregarán sus routers en `protegidos=[...]` (y `/auth` en `abiertos`) en la misma línea.

### D6 — Estrategia de tests (Strict TDD)
- **Unitarios** (`test/unit/test_health.py`, sin base): fixture `main_mod` = `importlib.reload(main)` con `secretos_validos` (patrón de `test_grupos_rutas.py`); `router_mod = importlib.import_module("app.modules.health.router")`; app = `crear_app(abiertos=[router_mod.router])`; `TestClient` **sin** contexto (no corre el lifespan) + `dependency_overrides[router_mod.get_motor]` con dobles:
  - `MotorFalso` cuyo `connect()` devuelve un gestor de contexto asíncrono con `execute` que registra el SQL (→ 200 y se ejecutó `SELECT 1`); que lanza `OSError("... host-secreto:5433 usuario ...")` o `OperationalError` en `connect()` (→ 503 cuerpo exacto, sin `host-secreto`, `5433`, `OSError`); cuyo `execute` hace `await asyncio.sleep(10)` con el tiempo bajado a 0.1 s (→ 503 en < 1 s).
  - `get_motor` real sin lifespan (`app.state` sin `engine`) → 503.
  - `live`: con un override de `get_motor` que cuenta llamadas → 200, cuerpo exacto y **0** llamadas; también sin lifespan.
  - Grupo abierto: `dependency_overrides[exigir_acceso]` con contador → `/health/*` nunca da 401/403 y el contador queda en 0; una ruta protegida de control en la misma app sí da 401.
  - App real: `main_mod.app` expone `/health/live` y `/health/ready` (inspección de `app.routes`); con `POSTGRES_HOST=127.0.0.1` y `POSTGRES_PORT` = puerto libre (socket ligado a `:0` y cerrado), `with TestClient(main_mod.app)` corre el lifespan real → `live` 200 y `ready` 503 en ≤ 3 s (conexión rechazada real, no requiere PostgreSQL).
  - Mockear el motor acá es válido: es una frontera en tests unitarios; la regla dura "nunca mockear la base" aplica a integración.
- **Integración** (`test/integration/test_health.py`, PostgreSQL real, usa `settings_db` → skip/fallo con `--exigir-db`):
  - `with TestClient(main_mod.app)` con el entorno real (lifespan real, `get_settings()` del `.env`) → `ready` 200 `{"estado": "listo"}` aun sin migraciones (no depende de C-03).
  - Recuperación: misma app, override de `get_motor` con un motor real (`crear_motor`) apuntando a un puerto libre → 503; quitar el override → 200 sin reiniciar.
  - No necesita esquema efímero: `SELECT 1` no escribe.
- Credenciales y puerto sólo vía `Settings`; nunca se lee ni imprime el `.env`.

## Risks / Trade-offs

- [**Windows tarda ~2 s en reportar "conexión rechazada" a localhost** (reintentos de SYN)] → el tiempo máximo de 2 s acota igual la respuesta; el test de la app real mide ≤ 3 s, no un valor menor.
- [**Puerto "libre" que alguien ocupa entre el cierre del socket y la conexión**] → ventana mínima; si ocurre, el test falla visiblemente (no da falso verde).
- [**Captura de `Exception` puede ocultar un bug de programación en `base_disponible`**] → el log registra el tipo de excepción; los tests unitarios cubren el camino feliz con el motor falso, por lo que un error de código en el camino OK se ve como 503 en un test que espera 200.
- [**`ready` comparte el pool con las peticiones de negocio**] → un pool agotado da 503: es el comportamiento deseado para una sonda de disponibilidad. Costo: una conexión por llamada durante milisegundos.
- [**Sondas frecuentes generan logs `warning` repetidos con la base caída**] → aceptable para el TP; no se agrega deduplicación.
- [**`TIEMPO_MAXIMO_READY_SEGUNDOS` no configurable**] → si hiciera falta, se agrega una variable en un change futuro modificando `configuracion`.

## Migration Plan

Sin esquema ni datos. Rollback = revertir la línea de `app = crear_app(...)` en `main.py` y borrar `app/modules/health/router.py` y los dos archivos de test. No afecta C-03 (que puede estar en curso en paralelo): C-04 no toca modelos, migraciones ni `CHANGES.md`.
