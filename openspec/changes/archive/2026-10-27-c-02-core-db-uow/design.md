# Design — C-02 `core-db-uow`

> ⚠️ **Governance CRITICO** (CHANGES.md §C-02): este diseño define la frontera transaccional de toda la aplicación. **Requiere aprobación humana explícita antes de `/opsx:apply`.** Ningún agente debe empezar a implementar sin ese visto bueno.

## Context

- Estado tras C-01 (observado en el código):
  - `app/core/config.py`: `Settings` con `database_url` (`postgresql+asyncpg`, `@computed_field(repr=False)`), `db_pool_size=5`, `db_max_overflow=10`, `sql_echo=False`; `get_settings()` con `lru_cache`.
  - `main.py`: llama `get_settings()` a nivel de módulo (fail-fast) y crea `app = FastAPI(title="Taller Mecánico")` sin lifespan ni rutas. `test/unit/test_main.py` verifica por subprocess que importa sin secretos → error, y con host inexistente → éxito.
  - `test/conftest.py`: fixtures `entorno_limpio` y `secretos_validos`. `pytest.ini`: `asyncio_mode = auto`, markers `unit`/`integration`. Sólo existe `test/unit/`.
  - `docker-compose.yml`: `postgres:16`, puerto `${POSTGRES_PORT:-5432}:5432` (en esta máquina el 5432 está ocupado: el `.env` local usa otro puerto, p. ej. 5433; los tests no deben asumir ninguno).
  - `app/core/` sólo tiene `config.py`; no hay modelos (llegan en C-03).
- Motivación y alcance: ver `proposal.md`. Requisitos observables: `specs/{sesion-base-datos,unidad-de-trabajo,repositorios,paginacion,grupos-de-rutas}/spec.md`.
- Restricciones que moldean el diseño: reglas duras de `CLAUDE.md` (repositorio sólo `flush()`, router construye el UoW, servicio lo abre con `async with`, UoW no cierra la sesión, sin carga perezosa, todo `async`, SQL con parámetros ligados, tests de integración contra PostgreSQL real); KB 08 §Patrones aplicados y §Reglas de las capas; DD-07 (dos grupos), DD-12/EA-08 (recursos en el lifespan), DD-05 (la fábrica en `app.state` permite a C-05 abrir una sesión propia para `intento_acceso`).

### Discrepancias detectadas con `CHANGES.md` / KB

1. **`app/core/dependencies.py`** no figura en el scope de C-02, pero el grupo protegido (DD-07) necesita *alguna* dependencia montada. Se crea el archivo con **sólo** el gancho del grupo protegido; C-05 lo completa (usuario actual, roles, control de cambio, `requiere_rol`).
2. **Flujo 10** (KB 07) incluye "calcula el hash ficticio" en el arranque: queda para **C-05** (bcrypt/seguridad). El lifespan de C-02 deja el punto de extensión.
3. `CHANGES.md` menciona sólo `add`/`update` en `BaseRepository`; KB 08 dice que heredar "daría `add/update/delete`". Se incluyen además `get_by_id`, `list`, `count` y `delete`, necesarios para paginar y para los módulos.
4. El **422 por página fuera de rango** (KB 05 §Reglas de contrato) necesita un traductor de error; no figura en el scope de C-02. Se registra en la fábrica de la app junto a `paginacion.py` para que C-06..C-10 no lo dupliquen.

## Goals / Non-Goals

**Goals:**
- Piezas genéricas y pequeñas que los módulos **extienden** sin copiar: `BaseRepository[T]`, `SoftDeleteRepository[T]`, `UnitOfWork`, paginación.
- Recursos de base creados y liberados sólo por el lifespan; la app sigue importando y arrancando sin base disponible.
- Verificación del comportamiento transaccional contra **PostgreSQL real**, sin depender de los modelos de C-03.

**Non-Goals:**
- Modelos de dominio, migraciones, `target_metadata` (C-03). Endpoints de salud (C-04).
- Autenticación, JWT, roles, hash ficticio en el lifespan, control de cambio de contraseña (C-05).
- Traducción de `IntegrityError` a 409 (la hacen los routers de cada módulo, RN-18).
- Paginación por cursor/keyset: el PDF pide `page`/`size` (OFFSET); el volumen del TP lo permite.

## Decisions

### D1 — `database.py`: fábricas puras, sin estado de módulo
```python
def crear_motor(settings: Settings) -> AsyncEngine
def crear_fabrica_sesiones(motor: AsyncEngine) -> async_sessionmaker[AsyncSession]
async def get_session(request: Request) -> AsyncIterator[AsyncSession]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
```
- `crear_motor` → `create_async_engine(settings.database_url, pool_size=settings.db_pool_size, max_overflow=settings.db_max_overflow, echo=settings.sql_echo, pool_pre_ping=True)`. `create_async_engine` no conecta: la app arranca sin base (spec §Arranque sin base disponible) y C-04 `ready` reporta 503.
- `pool_pre_ping=True`: descarta conexiones muertas tras un reinicio del contenedor a costo de un ping por checkout. **Alternativa**: `pool_recycle` → no detecta caídas; descartada.
- `crear_fabrica_sesiones` → `async_sessionmaker(motor, expire_on_commit=False)`. **Imprescindible en async**: con `expire_on_commit=True`, leer un atributo tras el commit dispara una carga implícita → `MissingGreenlet` (equivale a carga perezosa, prohibida). `autoflush` queda en su default.
- `get_session` toma `request.app.state.session_factory` y hace `async with fabrica() as sesion: yield sesion`. **Quien crea la sesión la cierra** (la dependencia), nunca la UoW. Las excepciones de la ruta atraviesan el `yield`, por lo que el cierre ocurre también con error.
- Nada a nivel de módulo crea objetos de SQLAlchemy (ni `engine = ...`, ni `SessionLocal = ...`). **Alternativa**: motor global perezoso → viola DD-12/EA-08; descartada.

### D2 — `main.py`: fábrica de app + lifespan + dos grupos
```python
settings = get_settings()                    # fail-fast de C-01, se conserva

@asynccontextmanager
async def lifespan(app: FastAPI):
    motor = crear_motor(get_settings())
    app.state.engine = motor
    app.state.session_factory = crear_fabrica_sesiones(motor)
    try:
        yield                                 # C-05: hash ficticio antes del yield
    finally:
        await motor.dispose()

def crear_app(abiertos: Sequence[APIRouter] = (), protegidos: Sequence[APIRouter] = ()) -> FastAPI
app = crear_app(abiertos=[], protegidos=[])   # C-04+ agregan sus routers acá
```
- `crear_app` arma `grupo_abierto = APIRouter()` y `grupo_protegido = APIRouter(dependencies=[Depends(exigir_acceso)])`, incluye en cada uno los routers recibidos, luego `app.include_router(...)` de ambos y registra el manejador de `PaginaFueraDeRangoError` (D6).
- **Por qué fábrica**: `include_router` copia las rutas en el momento de incluir; agregar routers a un grupo después de incluirlo no tiene efecto. La fábrica hace explícito el orden y permite a los tests construir una app con routers de prueba sin tocar la `app` real. **Alternativa**: grupos a nivel de módulo mutados por cada módulo → frágil y dependiente del orden de importación; descartada.
- `try/finally` garantiza `dispose()` aun si el código posterior al `yield` falla.

### D3 — Gancho del grupo protegido que **falla cerrado**
`app/core/dependencies.py`: `async def exigir_acceso() -> None` que lanza `HTTPException(401, "Se requiere iniciar sesión")`. Montado **una vez** en el grupo protegido (DD-07: FastAPI suma dependencias y no las resta).
- **Por qué cerrado y no un no-op**: un no-op dejaría abierta cualquier ruta protegida que se agregue antes de C-05 (governance CRITICO). Rechazar todo es inocuo porque en C-02 el grupo protegido no tiene rutas y C-05 precede a todo módulo que las agrega (C-06+).
- C-05 reemplaza el cuerpo (usuario actual + control de cambio de contraseña) **manteniendo el nombre** y el punto de montaje.

### D4 — `repository.py`
```python
class BaseRepository[T: SQLModel]:
    def __init__(self, session: AsyncSession, model: type[T]) -> None
    def _consulta(self) -> Select[tuple[T]]          # punto de extensión de filtros/opciones
    async def get_by_id(self, id_: int) -> T | None
    async def list(self, *, offset: int, limit: int) -> list[T]   # ORDER BY pk
    async def count(self) -> int                     # mismos filtros que _consulta()
    async def add(self, entidad: T) -> T             # session.add + flush
    async def update(self, entidad: T, cambios: Mapping[str, Any]) -> T   # setattr + flush
    async def delete(self, entidad: T) -> None       # session.delete + flush

class SoftDeleteRepository[T](BaseRepository[T]):
    def _consulta(self)                              # + WHERE borrado_en IS NULL
    async def get_by_id_including_deleted(self, id_: int) -> T | None
    async def soft_delete(self, entidad: T) -> T     # borrado_en = now(UTC) + flush
```
- **Clase del modelo explícita** en el constructor: los genéricos se borran en runtime (KB 08). Los repositorios de módulo hacen `super().__init__(session, Vehiculo)`.
- **PK por introspección** (`sqlalchemy.inspect(model).primary_key`); si no es de una sola columna → `TypeError` al construir. `estado_orden` (PK `codigo`) **no** hereda (repositorio de sólo lectura, KB 08).
- `get_by_id` usa `select(...).where(pk == :id)` y **no** `session.get()`: `get()` devuelve del identity map sin aplicar el filtro de borrado lógico.
- `count` = `select(func.count()).select_from(self._consulta().subquery())`: garantiza "total con los mismos filtros" (KB 05) con un único punto de filtrado.
- `update` valida las claves contra `inspect(model).column_attrs` **antes** de asignar; clave desconocida → `ValueError` sin cambios parciales. Recibe un `Mapping` para encajar con `model_dump(exclude_unset=True)` del PATCH parcial.
- **Ningún método llama `commit()`** ni `close()`. Todas las consultas se construyen con la API de expresiones (parámetros ligados).
- **Sin carga perezosa**: los métodos base no cargan relaciones; los repositorios de módulo declaran `selectinload/joinedload` en el método que lo necesita (sobrescribiendo `_consulta()` o con métodos propios). Recomendación para C-03: relaciones con `lazy="raise"` para que una carga olvidada falle en tests en vez de emitir SQL oculto.
- `soft_delete` asigna `datetime.now(UTC)` en Python. **Alternativa**: `func.now()` del servidor → el atributo queda expirado y leerlo exige `refresh` (otra consulta) o dispararía carga implícita; descartada. Diferencia de reloj app/base aceptable para el TP.
- Sintaxis de genéricos PEP 695 (Python ≥ 3.12, KB 02). `list` como nombre de método sombrea el builtin dentro de la clase: se anotan retornos con `builtins.list` o `Sequence`.

### D5 — `unit_of_work.py`
```python
class UnitOfWork:
    def __init__(self, session: AsyncSession) -> None
    async def __aenter__(self) -> Self
    async def __aexit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None:
            await self.session.rollback(); return False      # propaga
        try:
            await self.session.commit()
        except BaseException:
            await self.session.rollback(); raise
        return False
```
- **Nunca** `close()`: la sesión la cierra `get_session` (D1).
- Extensión por módulo (C-06+): `class ClientesUoW(UnitOfWork)` que en `__init__` crea `self.clientes = ClienteRepository(session)`, `self.vehiculos = VehiculoRepository(session)` sobre **la misma** sesión. Dependencia del router: `def get_clientes_uow(session: SessionDep) -> ClientesUoW` → el router construye, el servicio abre con `async with uow:` (regla dura).
- `rollback` ante `BaseException` (incluye `CancelledError`) y se re-lanza (skill async-python-patterns).
- No reentrante: un bloque por operación de negocio (RN-02/RN-13/RN-20 en **un solo** `async with`). No se agrega guarda en runtime; se documenta en el docstring.
- **Alternativa**: `session.begin()` como contexto → cierra el ciclo transaccional pero no permite la composición por módulo ni el patrón exigido por el PDF; descartada.

### D6 — `paginacion.py`
- Constantes `PAGINA_TAMANIO_DEFECTO = 20`, `PAGINA_TAMANIO_MAXIMO = 100`.
- `ParametrosPaginacion` (dataclass congelada: `page`, `size`, propiedad `offset = (page-1)*size`) construida por la dependencia `parametros_paginacion(page: Annotated[int, Query(ge=1)] = 1, size: Annotated[int, Query(ge=1, le=100)] = 20)`; alias `PaginacionDep`. Usa `Query` en una función y no un modelo de query (`FastAPI ≥ 0.115`) para respetar el mínimo `fastapi>=0.111`. Valores inválidos → 422 de validación de FastAPI.
- `calcular_paginas(total, size) = max(1, ceil(total / size))` (cero resultados → 1 página vacía).
- `verificar_pagina(params, total) -> int`: devuelve `pages` o lanza `PaginaFueraDeRangoError` si `page > pages`. Se llama **después de contar y antes de listar** (evita la consulta de items inútil).
- `Pagina[T]` (Pydantic `BaseModel` genérico, `Generic[T]`): `items: list[T]`, `total`, `page`, `size`, `pages`; `Pagina.crear(items, total, params)`.
- Manejador registrado en `crear_app`: `PaginaFueraDeRangoError` → `JSONResponse(422, {"detail": "La página solicitada no existe"})` (mensaje propio, RN-18).
- Uso previsto en servicios: `total = await repo.count()` → `pages = verificar_pagina(p, total)` → `items = await repo.list(offset=p.offset, limit=p.size)` → `Pagina.crear(...)`, todo dentro del mismo `async with uow` (lectura consistente).

### D7 — Tests: unitarios con dobles, integración con PostgreSQL real y modelos **sólo de test**
- **Unitarios** (`test/unit/`, sin base): UoW con una sesión espía (registra `commit`/`rollback`/`close`); `crear_motor` con `Settings` armado en el test (motor perezoso: se inspecciona `pool.size()`, `pool._max_overflow`, `echo`, y se hace `dispose()`); `get_session` con una fábrica falsa; lifespan vía `async with lifespan(app)`; grupos y paginación vía `TestClient(crear_app(abiertos=[r], protegidos=[r2]))`. Mockear acá es válido: son fronteras, no la base (regla dura aplica a integración).
- **Integración** (`test/integration/`, marker `integration`):
  - `test/integration/modelos_prueba.py`: `ItemPrueba` (`id`, `nombre` con UNIQUE **DEFERRABLE INITIALLY DEFERRED** — así la violación ocurre en el `commit` y no en el `flush`, lo que permite probar "falla al confirmar" —, `precio NUMERIC(10,2)` como `Decimal`) e `ItemBorrable` (`id`, `nombre`, `borrado_en TIMESTAMPTZ NULL`). Declarados con un **`registry()` propio** (`class BasePrueba(SQLModel, registry=registry())`) para que **no** entren en `SQLModel.metadata` y el `--autogenerate` de C-03 nunca los vea. **Fallback** si la versión de SQLModel no acepta `registry=`: `MetaData()` propia vía tabla Core + mapeo imperativo; se decide en apply y se anota.
  - `test/integration/conftest.py`:
    - URL desde `get_settings().database_url` (lee entorno/`.env` como la app; **nunca** credenciales ni puerto en el código del test). Funciona con el contenedor en 5433 si `POSTGRES_PORT` lo indica.
    - Por test: esquema efímero `c02_prueba_<hex>` creado con una conexión administrativa; motor de prueba `create_async_engine(url, poolclass=NullPool, connect_args={"server_settings": {"search_path": esquema}})`; tablas creadas con `BasePrueba.metadata.create_all` **sólo en ese esquema** (la prohibición de `create_all` aplica al esquema de la app, que se maneja con Alembic; esto es andamiaje desechable de test); teardown `DROP SCHEMA ... CASCADE` + `dispose()`. Ámbito función: evita compartir estado entre tests y los problemas de `loop_scope` de fixtures asíncronos de sesión.
    - La fábrica de sesiones de prueba se obtiene con **`crear_fabrica_sesiones`** de la app (se prueba la configuración real, p. ej. `expire_on_commit=False`).
    - "Otra sesión independiente" = una segunda sesión de la misma fábrica (otra conexión, `NullPool`).
    - **Base no disponible**: un ping con `asyncio.timeout(3)`; si falla la conexión o la configuración está incompleta → `pytest.skip("PostgreSQL no disponible: levantar docker compose ...")`. Opción `--exigir-db` (`pytest_addoption`) convierte el skip en fallo; la verificación final de este change corre con `--exigir-db` y exige **0 skipped**.
- Guardas estáticas baratas (unitarias): el fuente de `repository.py` no contiene `.commit(`; el de `unit_of_work.py` no contiene `.close(`; `database.py` no crea motor a nivel de módulo (importarlo y verificar que no expone `engine`/`SessionLocal`).

## Risks / Trade-offs

- [**Fuga transaccional**: un servicio que olvida `async with uow` deja cambios con `flush` sin confirmar; se pierden al cerrar la sesión] → falla visible en tests de cada módulo (el dato no persiste); los servicios reciben el UoW tipado y la convención está en CLAUDE.md. No se agrega auto-commit en `get_session` (rompería la regla del PDF).
- [**Commit que falla en `__aexit__`** deja la sesión en estado inválido] → rollback explícito antes de re-lanzar (D5) + test con restricción diferida.
- [**`expire_on_commit=False`** puede servir datos "viejos" si otra transacción cambia la fila tras el commit] → aceptable: cada petición tiene su sesión y la descarta al terminar.
- [**Gancho que falla cerrado** rompe cualquier ruta protegida que se agregue antes de C-05] → deseado; documentado en D3 y en el docstring. Si C-05 se demora y un módulo necesita probar rutas, sus tests pueden usar `dependency_overrides[exigir_acceso]`.
- [**Tests de integración que se saltean en silencio** si Postgres no está] → mensaje explícito + `--exigir-db` obligatorio en la verificación del change.
- [**Puerto local distinto (5433)**] → todo sale de `POSTGRES_PORT` vía `Settings`; ningún puerto fijo en tests ni código.
- [**`soft_delete` con reloj de la app**] → diferencia de segundos con el reloj de la base; irrelevante para el TP. El índice único parcial (DD-03, C-03) sólo mira `IS NULL`.
- [**OFFSET con páginas profundas**] → `size ≤ 100` y volúmenes del TP; keyset fuera de alcance.
- [**`pool._max_overflow` es atributo privado**] → sólo en un test unitario; si cambia en otra versión de SQLAlchemy se ajusta el test.
- [**SQLModel y `registry=`**] → fallback documentado en D7.
- [**Contraseña en `database_url`**] → nunca se loguea la URL ni el motor (`repr(engine)` oculta la contraseña); no se imprime `settings.model_dump()` en fixtures.

## Migration Plan

Sin datos previos ni esquema (C-03 crea las tablas). Rollback = revertir `main.py` a la versión de C-01 y borrar los archivos nuevos de `app/core/` y `test/integration/`. El comportamiento de arranque de C-01 (fail-fast, carga sin base) se preserva y lo siguen verificando sus tests.

## Open Questions

- Ninguna bloqueante. Pendiente de **aprobación humana** (governance CRITICO): D3 (gancho que falla cerrado), D5 (semántica de `__aexit__`) y D7 (estrategia de esquema efímero para tests).
