# Design — C-08 `repuestos-stock`

> ⚠️ **Governance ALTO** (CHANGES.md §C-08): el change escribe stock e historial de precios, datos de negocio que C-10 y la corrección auditan (RN-13/14/15/20). **Proponer y esperar revisión: requiere aprobación humana explícita de este diseño antes de `/opsx:apply`.** Puntos que piden revisión explícita: D3 (contrato de dinero), D4 (punto único de stock y su firma para C-10), D5 (garantías de atomicidad/concurrencia), D6 (PATCH con `FOR UPDATE` y mismo precio), D11 (archivos compartidos) y los supuestos SU-C08-1..10.

## Context

- Estado tras C-01..C-05 (observado en el código):
  - `app/modules/repuestos/models.py` (C-03): `Repuesto` (`codigo` TEXT, `descripcion` TEXT, `precio` `NUMERIC(10,2)` → `Decimal`, `stock` INTEGER NOT NULL default 0, `borrado_en` TIMESTAMPTZ nulo); restricciones `ck_repuesto_precio_positivo`, `ck_repuesto_stock_no_negativo` y el índice único parcial `uq_repuesto_codigo_vigente` (`WHERE borrado_en IS NULL`). `MovimientoStock` (`cantidad` INTEGER con `ck_movimiento_stock_cantidad_distinta_de_cero`, `orden_id` nulo, `usuario_id` NOT NULL, `motivo` TEXT, `cuando` con default de app y de servidor). `HistorialPrecioRepuesto` (`ck_historial_precio_repuesto_precio_nuevo_positivo`, `ck_historial_precio_repuesto_precio_nuevo_distinto`, `usuario_id` NOT NULL). Relaciones con `lazy="raise"`. Migración 2: disparador `BEFORE UPDATE OR DELETE FOR EACH ROW` con `ERRCODE P0001` en `movimiento_stock` e `historial_precio_repuesto` (no frena `TRUNCATE`).
  - `app/core/repository.py`: `SoftDeleteRepository[T]` (`_consulta()` filtra `borrado_en IS NULL`; `get_by_id`, `list`, `count`, `add`, `update(entidad, cambios)` con validación de columnas, `soft_delete`, `get_by_id_including_deleted`); todo con `flush()`.
  - `app/core/unit_of_work.py`: `UnitOfWork` (commit al salir, rollback ante excepción, no cierra la sesión). `app/core/database.py`: `SessionDep`, sesiones con `expire_on_commit=False`.
  - `app/core/errores.py`: `restriccion_violada(IntegrityError) -> str | None` (nombre de la restricción, también para índices únicos).
  - `app/core/paginacion.py`: `PaginacionDep`, `verificar_pagina`, `Pagina[T].crear`, manejador de `PaginaFueraDeRangoError` → 422 ya registrado en `crear_app`.
  - `app/core/dependencies.py`: `requiere_rol(*roles)` devuelve el `UsuarioActual` (con `id`), depende de `exigir_acceso`; `Rol` en `app/modules/usuarios/models.py`.
  - Patrón de módulo de C-05: `unit_of_work.py` con la dependencia `get_<mod>_uow(session)` que **construye** el UoW; `service.py` con excepciones de dominio y mapa `restricción → excepción`; `router.py` delgado que traduce excepciones a HTTP; `schemas.py` con `_Entrada(extra="forbid")`.
  - `main.py`: `app = crear_app(abiertos=[router_health, router_auth])` — todavía no hay routers protegidos de negocio.
  - Tests: `test/integration/conftest.py` ya ofrece `esquema_auth` (esquema migrado por Alembic, por sesión), `motor_auth` (TRUNCATE de las 13 tablas tras cada test), `db_auth` (`AyudantesAuth`: `crear_usuario(..., roles)`, `contar`, `filas`, `ejecutar`), `app_auth` → `fabrica_http` → `http`, y `emitir_token` para autenticar con cookie.
- Requisitos observables: `specs/{catalogo-repuestos,stock-repuestos,historial-precios-repuesto}/spec.md`. Motivación: `proposal.md`.
- Restricciones: reglas duras de `CLAUDE.md`; KB 04 (tablas obligatorias), KB 05 (RN-14/15/16/18/20, reglas de contrato), KB 06 Épica 5, KB 07 Flujo 8, DD-04, DD-11, DD-20, SU-04, SU-05, SU-08, IN-01, IN-05.

### Discrepancias detectadas con `CHANGES.md` / KB

1. **IN-05 (clase `HistorialPrecio`)**: la KB resuelve "tabla `historial_precio_repuesto`; clase `HistorialPrecio`", pero C-03 ya creó la clase `HistorialPrecioRepuesto`. Se **conserva** el nombre existente (el nombre de tabla es el obligatorio y está bien); renombrar la clase tocaría C-03 sin beneficio.
2. **Códigos de `reponer`**: KB 06 lista 200/404/422. Se agrega **409** para el desborde del stock (`> 2147483647`, columna INTEGER), que de otro modo sería un 500 (RN-18 "ninguna entrada inválida termina en un 500"). Con el tope de 1 000 000 por reposición sólo se alcanza tras ~2 147 reposiciones máximas: caso límite, pero cerrado.
3. **`GET /repuestos/{id}/movimientos` y `/precios`**: KB 06 lista 200/404 sin 422; como son listados con el envoltorio común, `page` fuera de rango → 422 (regla de contrato de listados).
4. **Concurrencia (DD-11)**: la KB difiere la actualización perdida del stock. El diseño la **evita igual** sin costo extra (incremento relativo en la base, D5) y bloquea la fila en el PATCH de precio (D6) para que el historial quede encadenado. No contradice DD-11: sólo se cubre más de lo exigido; la verificación previa de stock de C-10 sigue siendo de C-10.
5. **SU-04**: "la validación explícita en el servicio da el 409 (el CHECK es la red)". El punto único traduce el `CHECK stock >= 0` a `StockInsuficienteError` (garantía bajo concurrencia); la verificación explícita previa (para un mensaje por ítem antes de escribir) queda en C-10, que puede hacerla con el stock leído en su UoW.

## Goals / Non-Goals

**Goals:**
- Un **único** punto de escritura de stock (RN-14), atómico con su movimiento, reutilizable tal cual por C-10.
- Dinero exacto de punta a punta (`NUMERIC` ↔ `Decimal` ↔ cadena JSON), sin `float` en ninguna capa.
- Ninguna entrada que termine en 500; errores de unicidad traducidos por nombre de restricción.
- Verificación contra PostgreSQL real con el esquema que produce Alembic (incluye el disparador de sólo agregado).

**Non-Goals:**
- Órdenes, salida de stock por terminación y verificación previa de stock por ítem (C-09/C-10).
- `seed.py` (C-11): carga sus repuestos y el historial 8000 → 8500 con su propio camino; puede reutilizar `mover_stock`.
- Edición de `codigo`, restauración de repuestos dados de baja, ajustes manuales de inventario (salidas que no sean de órdenes), búsqueda por código.
- Cambios en `app/core/*`, modelos o migraciones.

## Decisions

### D1 — Estructura del módulo
```
app/modules/repuestos/
  schemas.py        # contratos de entrada/salida (separados de los modelos de tabla)
  repository.py     # RepuestoRepository, MovimientoStockRepository, HistorialPrecioRepository
  unit_of_work.py   # RepuestosUoW + get_repuestos_uow + RepuestosUoWDep
  stock.py          # punto único de escritura de stock (mover_stock) + errores de stock
  service.py        # casos de uso: crear, listar, obtener, editar, dar_de_baja, reponer, movimientos, precios
  router.py         # router_repuestos (prefijo /repuestos), grupo protegido
```
- `stock.py` separado de `service.py` para que C-10 importe **sólo** el punto único y sus errores sin arrastrar los casos de uso del catálogo (y sin ciclos con `ordenes`).
- **Alternativa**: poner `mover_stock` como método de `RepuestosUoW` → obliga a C-10 a usar ese UoW o a heredar de él; descartada (ver D4).

### D2 — Contratos (`schemas.py`) y permisos
- `_Entrada(BaseModel)` con `ConfigDict(extra="forbid")` (mismo patrón que `usuarios/schemas.py`; no se importa de allí para no acoplar módulos).
- `RepuestoAlta`: `codigo: Codigo` (strip, 1..50, `upper()`), `descripcion: Descripcion` (strip, 1..200), `precio: Precio` (D3), `stock_inicial: Annotated[StrictInt, Field(ge=0, le=1_000_000)] = 0`.
- `RepuestoEdicion`: `descripcion: Descripcion | None = None`, `precio: Precio | None = None`, con un validador `model_validator(mode="after")` que rechaza `None` **explícito** (`model_fields_set`) → 422; el servicio usa `model_dump(exclude_unset=True)`.
- `Reposicion`: `cantidad: Annotated[StrictInt, Field(ge=1, le=1_000_000)]`. `StrictInt` rechaza `"5"`, `true` y `1.5` (el modo laxo de Pydantic aceptaría `"5"` y `True`).
- Búsqueda: `q: Annotated[str | None, Query(min_length=1, max_length=100)] = None`, recortada en el router; vacía tras recortar → 422.
- Salidas: `RepuestoRespuesta {id, codigo, descripcion, precio, stock}` (sin `borrado_en`), `MovimientoRespuesta {id, repuesto_id, orden_id, usuario_id, cantidad, motivo, cuando}`, `PrecioHistorialRespuesta {id, repuesto_id, usuario_id, precio_anterior, precio_nuevo, cuando}`; construidas con `model_validate(entidad, from_attributes=True)` (sólo columnas: ninguna relación, sin carga perezosa).
- Permisos como alias en el router: `LectorCatalogo = Annotated[UsuarioActual, Depends(requiere_rol(Rol.ADMIN, Rol.RECEPCION, Rol.MECANICO))]` y `AdminDep = Annotated[UsuarioActual, Depends(requiere_rol(Rol.ADMIN))]`. El handler recibe el `UsuarioActual` y pasa `usuario.id` al servicio (autor de movimientos e historial). El 403 se resuelve en las dependencias, antes de que el handler busque el repuesto (404) y antes de que FastAPI levante la validación de un cuerpo JSON bien formado (422). Un cuerpo **mal formado** (JSON roto) da 422 antes que 403: FastAPI decodifica el cuerpo antes de resolver dependencias (límite aceptado).

### D3 — Contrato de dinero: `Decimal` en todas las capas, cadena en JSON
```python
Precio = Annotated[
    Decimal,
    BeforeValidator(_rechazar_booleanos),           # True/False → error (Decimal laxo los aceptaría)
    Field(gt=0, max_digits=10, decimal_places=2, allow_inf_nan=False),
    AfterValidator(lambda d: d.quantize(Decimal("0.01"))),
]
Dinero = Annotated[Decimal, PlainSerializer(lambda d: f"{d:.2f}", return_type=str, when_used="json")]
```
- **Entrada**: número JSON o cadena numérica. Pydantic convierte un número JSON a `Decimal` desde su representación textual (no hay aritmética binaria). `max_digits=10, decimal_places=2` replica `NUMERIC(10,2)`: más de 2 decimales o más de 8 enteros → 422 antes de llegar a la base (si no, sería un `DataError` → 500). `quantize` deja todo precio con escala 2.
- **Salida**: **cadena** con 2 decimales (`"8500.00"`). Es el comportamiento por defecto de Pydantic v2 para `Decimal`; el serializador explícito fija el formato (sin notación científica, siempre 2 decimales aunque la entidad venga sin recargar de la base). El esquema OpenAPI lo documenta como `string`.
- **Comparación de precios** (D6): siempre `Decimal == Decimal` (`Decimal("8000") == Decimal("8000.00")` es verdadero).
- **Alternativas**: salida como número JSON → el cliente (JavaScript) lo parsea a `float` y pierde exactitud; además Pydantic necesitaría convertir a `float` para emitirlo: viola la regla dura. Entrada sólo como cadena → más estricto pero incómodo para los `.http` y el seed; descartada. Precio en centavos enteros → contradice `NUMERIC(10,2)` de la KB.

### D4 — Punto único de escritura de stock (`stock.py`), firma estable para C-10
```python
class ConStock(Protocol):
    repuestos: RepuestoRepository
    movimientos: MovimientoStockRepository

class StockInsuficienteError(Exception): repuesto_id: int
class StockFueraDeRangoError(Exception): repuesto_id: int
class RepuestoNoEncontradoError(Exception): repuesto_id: int

MOTIVO_STOCK_INICIAL = "Stock inicial"
MOTIVO_REPOSICION = "Reposición"
STOCK_MAXIMO = 2_147_483_647

async def mover_stock(
    uow: ConStock, *, repuesto_id: int, cantidad: int, motivo: str,
    usuario_id: int, orden_id: int | None = None,
) -> int:   # devuelve el stock resultante
```
- **Contrato**: se llama **dentro** de un `async with uow` abierto por el servicio que la usa (nunca confirma ni abre transacción); `cantidad != 0` y `motivo` no vacío (si no, `ValueError`: error de programación, no de usuario); entradas `> 0`, salidas `< 0` (SU-05); no filtra borrados lógicos (decisión del llamador: la reposición exige vigente; C-10 debe poder descontar un repuesto dado de baja de una orden ya abierta, ver SU-C08-9).
- **Pasos**: (1) `nuevo = await uow.repuestos.sumar_stock(repuesto_id, cantidad)` (D5); (2) `await uow.movimientos.add(MovimientoStock(repuesto_id=..., orden_id=..., usuario_id=..., cantidad=..., motivo=...))`; (3) devolver `nuevo`. Si (2) falla, la excepción atraviesa el bloque y el UoW revierte también (1).
- **Errores**: `IntegrityError` con `restriccion_violada(...) == "ck_repuesto_stock_no_negativo"` → `StockInsuficienteError`; otras `IntegrityError` se relanzan. La transacción queda abortada en PostgreSQL: el llamador **debe** dejar propagar la excepción fuera del `async with` (el UoW revierte todo, que es lo que pide RN-13 en C-10).
- **C-10** compone su `OrdenesUoW` con atributos `repuestos` y `movimientos` (las mismas clases de repositorio sobre la misma sesión) y llama `mover_stock(uow, repuesto_id=item.repuesto_id, cantidad=-item.cantidad, motivo="Terminación de orden", usuario_id=actor.id, orden_id=orden.id)` por ítem, **ordenando los ítems por `repuesto_id`** para que dos terminaciones concurrentes tomen los bloqueos de fila en el mismo orden (evita interbloqueos).
- **Alternativas**: método del `RepuestosUoW` → acopla C-10 a ese UoW; servicio con su propio UoW → prohibido (un servicio no construye su UoW) y rompería la atomicidad de la terminación; disparador en la base que mantenga `stock` desde `movimiento_stock` → robusto pero oculta la lógica de RN-14 en SQL, exige una migración nueva (fuera de alcance: "sin tocar tablas") y complica el 409 por ítem.

### D5 — Atomicidad y concurrencia del stock: incremento relativo en la base
```python
async def sumar_stock(self, repuesto_id: int, delta: int) -> int | None:
    sentencia = (
        update(Repuesto)
        .where(Repuesto.id == repuesto_id, cast(Repuesto.stock, BigInteger) + delta <= STOCK_MAXIMO)
        .values(stock=Repuesto.stock + delta)
        .returning(Repuesto.stock)
        .execution_options(synchronize_session="fetch")
    )
```
- `UPDATE ... SET stock = stock + :delta` con parámetros ligados es atómico a nivel de fila: PostgreSQL toma el bloqueo de la fila y, si otra transacción la tenía, **reevalúa** con el valor confirmado. Dos reposiciones concurrentes suman ambas (spec "Reposiciones concurrentes sin pérdida"), sin `SELECT ... FOR UPDATE` previo.
- La guarda `stock::bigint + delta <= 2147483647` evita el `integer out of range` (`DataError` → 500): si `RETURNING` no devuelve fila, `mover_stock` distingue con `get_by_id_including_deleted` entre inexistente (`RepuestoNoEncontradoError`) y desborde (`StockFueraDeRangoError`).
- El límite inferior lo pone el `CHECK stock >= 0` de la base: bajo concurrencia, la segunda salida que dejaría el stock negativo falla con `IntegrityError` aunque ambas hayan leído stock suficiente antes. Es la "red de seguridad" de SU-04 y no depende de que C-10 haga bien su verificación previa.
- `synchronize_session="fetch"` mantiene coherente el `Repuesto` que el servicio ya tenga en el mapa de identidad (la respuesta de `reponer` muestra el stock nuevo sin una lectura extra).
- **Qué se garantiza**: (a) stock y movimiento juntos o ninguno (misma transacción, mismo UoW); (b) ninguna variación concurrente se pierde; (c) el stock nunca es negativo ni desborda; (d) `stock == Σ movimientos.cantidad` si todo stock entró por la API (el seed debe usar `mover_stock` o cargar el movimiento "Stock inicial" a la par). **Qué no**: (e) la verificación previa de C-10 puede leer un stock que cambia antes de su `UPDATE` (la base igual rechaza el negativo: el usuario recibe 409 por la red de seguridad en vez de por la verificación); (f) orden de llegada entre peticiones concurrentes (no hay colas ni prioridades).
- **Alternativas**: leer, calcular en Python y escribir el valor absoluto (`BaseRepository.update`) → actualización perdida bajo concurrencia, justo lo que DD-11 acepta pero aquí no cuesta nada evitar; `SELECT ... FOR UPDATE` + escritura absoluta → correcto pero una ida y vuelta más y depende de que todo llamador recuerde bloquear; aislamiento `SERIALIZABLE` → reintentos que el UoW no maneja.

### D6 — PATCH: precio con bloqueo de fila e historial en la misma transacción
- El servicio abre el UoW, lee con `repuestos.get_by_id_para_actualizar(id)` (`_consulta().where(id).with_for_update()` + `populate_existing`; filtra borrados → 404), y con `cambios = datos.model_dump(exclude_unset=True)`:
  - si `"precio"` está en `cambios` y `cambios["precio"] == repuesto.precio` → se **quita** `precio` de `cambios` (no hay escritura ni línea; el `CHECK precio_nuevo <> precio_anterior` nunca se dispara por un PATCH idempotente);
  - si cambia → `precios.add(HistorialPrecioRepuesto(repuesto_id, usuario_id, precio_anterior=repuesto.precio, precio_nuevo=nuevo))` y luego `repuestos.update(repuesto, cambios)`;
  - `cambios` vacío → responde el repuesto tal cual (200, sin escrituras).
- El `FOR UPDATE` serializa dos cambios de precio concurrentes del mismo repuesto: el segundo espera y lee el precio que dejó el primero, así el historial queda encadenado (`anterior` de cada línea = `nuevo` de la previa). Costo: una cláusula; el bloqueo dura sólo la transacción del PATCH.
- `RepuestoRepository.update` **rechaza** la clave `stock` (`ValueError`) además de la validación genérica de columnas: RN-14 queda garantizada también contra un uso interno erróneo (test unitario). `codigo` tampoco llega (contrato), pero no se bloquea en el repositorio.
- **Alternativas**: disparador `AFTER UPDATE OF precio` que escriba el historial → requiere migración y no conoce el `usuario_id` sin variables de sesión; escribir siempre la línea y dejar que el CHECK falle → 500/409 en un PATCH idempotente, contradice RN-20 ("sin cambio no deja línea"); responder 422 a "mismo precio" → hostil para clientes que reenvían el objeto completo.

### D7 — Alta, baja y errores
- **Alta**: dentro de un único `async with uow`: `repuestos.add(Repuesto(codigo, descripcion, precio, stock=0))` y, si `stock_inicial > 0`, `mover_stock(uow, repuesto_id=r.id, cantidad=stock_inicial, motivo=MOTIVO_STOCK_INICIAL, usuario_id=actor)`. El repuesto nace en 0 y el stock entra **sólo** por el punto único (RN-14 sin excepciones). Unicidad: sin consulta previa; `IntegrityError` capturado **fuera** del `async with` (como C-05) y traducido por nombre con un mapa `{"uq_repuesto_codigo_vigente": CodigoDuplicadoError}`; cualquier otro → `ConflictoError` genérico (409, mensaje propio). Ningún texto de la base llega al cliente (RN-18).
- **Baja**: `get_by_id` (filtra borrados) → 404 si falta; `soft_delete` → 204. Los movimientos e historial no se tocan (sólo agregado). Con stock > 0 se permite (SU-C08-8).
- **Excepciones → HTTP** (en el router): `RepuestoNoEncontradoError` → 404 "Repuesto no encontrado"; `CodigoDuplicadoError` → 409 "Ya existe un repuesto vigente con ese código"; `StockFueraDeRangoError` → 409 "La reposición supera el stock máximo admitido"; `StockInsuficienteError` → 409 "Stock insuficiente" (no alcanzable por rutas de C-08; lo usa C-10). Las excepciones viven en el módulo (`service.py`/`stock.py`); `app/core/errores.py` sólo se **reutiliza**.
- **Alternativa**: promover `ConflictoError` a `app/core/errores.py` para todos los módulos → útil, pero toca un archivo compartido que C-06/C-07 pueden estar modificando en paralelo; se deja como refactor posterior (ver D11).

### D8 — Listados, búsqueda y trazabilidad
- `RepuestoRepository.buscar(q, offset, limit)` y `contar(q)` sobre `_consulta()` (vigentes) + `descripcion ILIKE :patron ESCAPE '\'`, con `patron = f"%{escapar_like(q)}%"` (escapa `\`, `%`, `_`) como **parámetro ligado**; orden `id` ASC. El servicio: `total = contar` → `verificar_pagina` → `buscar` → `Pagina.crear`, todo en el mismo `async with uow`.
- `MovimientoStockRepository.listar_por_repuesto(repuesto_id, offset, limit)` / `contar_por_repuesto(repuesto_id)` y lo mismo en `HistorialPrecioRepository`; orden `id` ASC (cronológico de inserción, desempata `cuando` iguales). Antes de listar, el servicio verifica que el repuesto esté vigente (`get_by_id` → 404, SU-C08-7).
- Índices: `ix_movimiento_stock_repuesto_id` e `ix_historial_precio_repuesto_repuesto_id` (C-03) cubren los filtros. La búsqueda `ILIKE '%q%'` hace un recorrido secuencial; aceptable con el catálogo del TP (un índice trigram `pg_trgm` requeriría migración: fuera de alcance).

### D9 — Unit of Work del módulo
```python
class RepuestosUoW(UnitOfWork):
    def __init__(self, session):
        super().__init__(session)
        self.repuestos = RepuestoRepository(session)        # SoftDeleteRepository[Repuesto]
        self.movimientos = MovimientoStockRepository(session)  # BaseRepository[MovimientoStock], sólo add + lecturas
        self.precios = HistorialPrecioRepository(session)      # BaseRepository[HistorialPrecioRepuesto], sólo add + lecturas
def get_repuestos_uow(session: SessionDep) -> RepuestosUoW
RepuestosUoWDep = Annotated[RepuestosUoW, Depends(get_repuestos_uow)]
```
- `RepuestosUoW` satisface `ConStock` por estructura. Los repositorios de sólo agregado sobrescriben `update`/`delete` para lanzar `NotImplementedError` (defensa en profundidad del disparador; test unitario).
- Ningún repositorio llama `commit()` (test estático sobre los archivos nuevos, como `test_repository_estatico.py`).

### D10 — Estrategia de pruebas
- **Unitarias** (`test/unit/test_schemas_repuestos.py`, `test/unit/test_repuestos_estatico.py`): contratos (D2/D3: precios válidos/ inválidos, `extra`, `None` explícito, `StrictInt`, serialización `"8500.00"`), `escapar_like`, `RepuestoRepository.update` rechaza `stock`, repos de sólo agregado sin `update`/`delete`, ningún `commit(` en el módulo, y **un único** lugar del código de `app/` que escribe `stock` (búsqueda estática de `stock=`/`.stock =`/`"stock"` en asignaciones fuera de `repository.sumar_stock`).
- **Integración** en `test/integration/repuestos/` (subdirectorio con `__init__.py` y **su propio `conftest.py`**): reutiliza `settings_auth`, `motor_auth`, `db_auth`, `fabrica_http` y `http` del `conftest.py` compartido y **sobrescribe** `app_auth` en el subdirectorio para armar `crear_app(abiertos=[router_health, router_auth], protegidos=[router_repuestos])` con el mismo `app.state` (motor del esquema migrado, bcrypt de 4 rondas, hash ficticio). Así `http`/`fabrica_http` sirven las rutas de repuestos **sin modificar** el `conftest.py` compartido. Ayudantes locales: `cookie_de(uid, roles)` con `emitir_token`, `sembrar_repuesto(...)` por SQL ligado, `movimientos_de(id)`, `historial_de(id)`.
  - HTTP por ruta: permisos (matriz ADMIN/RECEPCION/MECANICO/CLIENTE/sin sesión, 403 antes que 404/422), 201/409/422 del alta, búsqueda (`' OR '1'='1`, `%`, `q=FRENO&size=1`, `page=2` → 422, `size=500` → 422), PATCH (stock → 422, parcial, mismo precio, historial), baja (204, 404 repetida, código reutilizable), reponer (200/404/422/409 desborde), movimientos y precios (orden, 403, 404).
  - Atomicidad: `monkeypatch` de `MovimientoStockRepository.add` / `HistorialPrecioRepository.add` para que lancen tras el `UPDATE` → stock/precio intactos y sin filas (el transporte ASGI propaga la excepción: `pytest.raises`).
  - Concurrencia contra la base real, con dos sesiones de `crear_fabrica_sesiones(motor_auth)`: dos `reponer` simultáneos (`asyncio.gather`, dos clientes HTTP) → stock 10; dos `mover_stock(-2)` sobre stock 3 en dos UoW → uno `StockInsuficienteError`, stock final 1; salida de 4 sobre stock 2 → error, sin movimiento.
  - Sólo agregado: tras `reponer`/PATCH de precio, `UPDATE movimiento_stock` y `DELETE FROM historial_precio_repuesto` vía `db_auth.ejecutar` → `DBAPIError` (P0001) y las filas intactas.
  - Invariante: tras alta + reposiciones, `stock == SUM(cantidad)`.
- Se ejecutan con `pytest --exigir-db` (PostgreSQL real, nunca mocks de la base).

### D11 — Archivos compartidos y secuenciación con C-06 / C-07
| Archivo | Cambio de C-08 | Choque posible | Regla para el apply |
|---|---|---|---|
| `main.py` | `from app.modules.repuestos.router import router_repuestos` y `protegidos=[router_repuestos]` en `crear_app(...)` | C-06 (`router_usuarios`) y C-07 (`router_clientes`/vehículos) editan **la misma línea** | Aplicar en serie o fusionar a mano: la lista final es la unión `protegidos=[router_usuarios, router_clientes, router_vehiculos, router_repuestos]` (orden irrelevante). Es la **única** edición de C-08 fuera de su módulo. |
| `app/core/*` | ninguno (sólo lectura) | — | Si C-06/C-07 promueven `ConflictoError` u otro helper a `app/core/errores.py`, C-08 puede adoptarlo después sin cambiar comportamiento. |
| `test/integration/conftest.py` | ninguno | C-06/C-07 pueden agregar fixtures | C-08 usa un `conftest.py` propio en `test/integration/repuestos/`. Si otro change agrega al compartido un ayudante genérico "app de prueba con routers protegidos", migrar el override a ese ayudante es opcional. |
| `app/modules/usuarios/models.py` (`Rol`), `app/core/dependencies.py` | sólo importación | — | — |

## Risks / Trade-offs

- [**Salida en cadena para dinero**: un cliente que espera número debe convertir] → documentado en OpenAPI (`string`); la exactitud lo justifica (D3). Los `.http` de C-12 deben mostrar `"8500.00"`.
- [**Interbloqueo en C-10** si dos terminaciones descuentan los mismos repuestos en distinto orden] → la firma de D4 documenta que C-10 debe iterar por `repuesto_id` ascendente; PostgreSQL detecta el interbloqueo y aborta una (sería un 500 si no se maneja): riesgo trasladado a C-10.
- [**Transacción abortada tras `StockInsuficienteError`**: si un llamador captura la excepción **dentro** del `async with` y sigue usando la sesión, toda sentencia falla] → contrato explícito en el docstring de `mover_stock` y test de C-10; dentro de C-08 nadie la captura dentro del bloque.
- [**El seed (C-11) puede romper el invariante** si inserta `repuesto.stock` sin su movimiento] → la KB ya exige "cada stock cargado como movimiento 'Stock inicial'"; C-11 debe usar `mover_stock` o insertar ambos.
- [**`ILIKE '%q%'` sin índice**] → recorrido secuencial; irrelevante con decenas de repuestos (D8).
- [**`FOR UPDATE` en PATCH** retiene la fila mientras dura la transacción] → transacción corta (sin I/O externo dentro); impacto nulo en el TP.
- [**Override de `app_auth` en el subdirectorio** duplica ~6 líneas de armado del `app.state`] → aceptado para no editar el `conftest.py` compartido en paralelo con C-06/C-07 (D11).
- [**Normalización de `codigo` a mayúsculas** cambia lo que envía el cliente] → hace que el índice único parcial (exacto) trate `fil-001` y `FIL-001` como el mismo código; el seed usa mayúsculas (SU-C08-2).
- [**JSON mal formado da 422 antes que 403**] → comportamiento de FastAPI; no filtra información del recurso.

## Supuestos (requieren visto bueno)

- **SU-C08-1**: `precio` se acepta como número JSON o cadena numérica, `> 0`, ≤ 2 decimales, ≤ 99 999 999.99; se devuelve **siempre** como cadena con 2 decimales (`"8500.00"`), también en `/precios`.
- **SU-C08-2**: `codigo` se recorta y se guarda en **mayúsculas**, 1..50 caracteres; `descripcion` se recorta, 1..200 caracteres. `codigo` no se edita nunca (fuera del PATCH, SU-08).
- **SU-C08-3**: `stock_inicial` es opcional (default 0), entero estricto 0..1 000 000; con 0 no se registra movimiento (el `CHECK cantidad <> 0` no admite uno de 0).
- **SU-C08-4**: `reponer.cantidad` entero estricto 1..1 000 000; desborde del stock → 409 (no listado en la KB, ver Discrepancia 2). Motivo fijo "Reposición"; el de alta, "Stock inicial".
- **SU-C08-5**: PATCH con el mismo precio (comparación decimal) no escribe precio ni historial y responde 200; PATCH con cuerpo vacío responde 200 sin cambios; un campo con `null` → 422.
- **SU-C08-6**: `q` busca sólo en `descripcion`, sin distinguir mayúsculas, como texto literal (comodines escapados), 1..100 caracteres.
- **SU-C08-7**: un repuesto dado de baja responde **404** en `GET /{id}`, PATCH, DELETE, `reponer`, `/movimientos` y `/precios` (deja de aparecer, RN-16); su trazabilidad se conserva en la base.
- **SU-C08-8**: se puede dar de baja un repuesto con stock > 0 o referenciado por ítems de órdenes; la baja no mueve stock.
- **SU-C08-9**: `mover_stock` no filtra repuestos dados de baja (C-10 debe poder terminar una orden abierta cuyo repuesto se dio de baja después de crearla); la reposición sí exige repuesto vigente.
- **SU-C08-10**: `/movimientos` y `/precios` se devuelven paginados con el envoltorio común, en orden cronológico ascendente (por `id`).

## Migration Plan

Sin migraciones de esquema ni datos (usa las tablas de C-03 tal cual). Despliegue: agregar el módulo y registrar `router_repuestos` en el grupo protegido de `main.py`. Rollback: quitar la línea de `main.py` y el directorio del módulo; las filas creadas quedan (son datos de negocio válidos).

## Open Questions

- Ninguna bloqueante. Pendiente de **aprobación humana** (governance ALTO) de D3, D4, D5, D6, D11 y de los supuestos SU-C08-1..10. El texto del motivo de salida que use C-10 ("Terminación de orden" sugerido) lo fija C-10.
