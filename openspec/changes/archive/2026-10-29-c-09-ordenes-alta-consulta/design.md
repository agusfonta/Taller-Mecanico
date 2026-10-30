# Design — C-09 `ordenes-alta-consulta`

> Governance **MEDIO**: implementar con checkpoints. Las decisiones marcadas **[APROBAR]** son no obvias o completan huecos de la KB; el apply NO arranca sin el visto bueno del usuario sobre ellas (lista consolidada al final, §Decisiones a aprobar).

## Context

- Modelos de C-03 en `app/modules/ordenes/models.py`: `EstadoOrden` (PK textual `codigo`), `OrdenTrabajo`, `ItemOrden` (`UNIQUE(orden_id, repuesto_id)`, CHECKs `cantidad > 0`, `precio_unitario > 0`), `HistorialEstadoOrden` (sólo agregado por disparador). Todas las relaciones con `lazy="raise"`. PKs y FKs `BIGINT`. Nombres de restricciones por convención (`uq_%(table)s_%(cols)s`, `ck_%(table)s_%(name)s`).
- Patrones ya establecidos (C-07/C-08) que este change repite sin variantes: UoW por módulo construido por una dependencia `get_*_uow` y abierto por el servicio con `async with` una vez por operación; repositorios que sólo hacen `flush()`; errores de dominio con `mensaje` traducidos en una única `_http_desde` del router; `IntegrityError` traducido por **nombre** de restricción (`restriccion_violada`); contratos `_Entrada` con `extra="forbid"` y `_Salida` con `from_attributes`; dinero `Decimal` emitido como cadena con 2 decimales (`Dinero` de `repuestos/schemas.py`); paginación con `PaginacionDep`, `verificar_pagina` y `Pagina.crear`.
- Coordinación pendiente heredada de C-07: `VehiculoRepository.get_vigente_para_baja` toma `FOR UPDATE` y su docstring pide que C-09 lea el vehículo con `FOR SHARE`.
- Contrato de `stock.mover_stock` (C-08): el UoW llamador debe exponer `repuestos` y `movimientos` (`ConStock`) y, con varios repuestos, iterar por `repuesto_id` ascendente. C-09 no mueve stock, pero deja el UoW listo para C-10.

## Goals / Non-Goals

**Goals:**
- Alta atómica de orden y las cuatro rutas de consulta, según `specs/`.
- Detalle con número de sentencias constante (evidencia C-15) y precarga explícita en el repositorio.
- Dejar a C-10 un UoW, repositorios y un detalle reutilizables sin retocarlos.

**Non-Goals:**
- Transiciones (`iniciar`, `terminar`, `cancelar`), movimientos de stock y `BackgroundTasks` (C-10).
- Seed del catálogo y de órdenes (C-11); archivos `.http` y capturas (C-12).
- Migraciones o cambios de modelos/columnas.
- Concurrencia de stock (DD-11).

## Decisions

### D1 — Estructura del módulo y UoW compuesto
`app/modules/ordenes/` agrega `schemas.py`, `repository.py`, `unit_of_work.py`, `service.py`, `router.py`. `OrdenesUoW` expone, **sobre la misma sesión**: `estados` (catálogo, sólo lectura), `ordenes`, `items`, `historial` (sólo agregado), `vehiculos` (`VehiculoRepository` de clientes) y `repuestos` + `movimientos` (repositorios de repuestos). Así cumple `ConStock` y C-10 llama `mover_stock(uow, ...)` sin otro UoW.
*Alternativa descartada*: que el servicio de órdenes use dos UoW (clientes + repuestos) → dos transacciones, rompe la atomicidad.

### D2 — Enum de estados en código
`EstadoOrdenCodigo(StrEnum)` con PENDIENTE, EN_REPARACION, TERMINADA, CANCELADA en `ordenes/models.py` junto a los modelos (o `schemas.py` si se prefiere no tocar `models.py`; ver D2-a). Es el contrato del filtro `estado` (FastAPI lo valida → 422) y el vocabulario de transiciones de C-10 (DD-02). El catálogo sigue siendo la fuente de `es_final`/`posicion`.
- **D2-a [APROBAR]**: ubicar el enum en `app/modules/ordenes/models.py` (sin cambiar columnas; sólo un `StrEnum` nuevo, como `Rol` en usuarios). Recomendado por simetría con `Rol`.

### D3 — Repositorio del catálogo de sólo lectura
`EstadoOrdenRepository` **no** hereda de `BaseRepository` (que trae `add/update/delete`): clase propia con sólo `listar_por_posicion()` y `get_por_codigo(codigo)`. Garantiza RN-19 por construcción (no hay método de escritura que invocar). Un test estático verifica que no tiene `add`, `update`, `delete`.
`HistorialEstadoOrdenRepository` hereda de `BaseRepository` y sobrescribe `update`/`delete` con `NotImplementedError` (mismo patrón que `MovimientoStockRepository`).

### D4 — Contrato de alta
`OrdenAlta(_Entrada)`: `vehiculo_id: StrictInt 1..2^63-1`, `falla: str` recortado 1..500, `items: list[ItemAlta]` con `min_length=1`, `max_length=50`. `ItemAlta(_Entrada)`: `repuesto_id: StrictInt 1..2^63-1`, `cantidad: StrictInt 1..1000`. Un `model_validator` rechaza `repuesto_id` repetidos (422, RN-10 "DTO"). Los topes de ids evitan un `DataError` de asyncpg (→ 500) con enteros fuera de BIGINT.
- **D4-a [APROBAR]**: topes `falla ≤ 500` caracteres, `items ≤ 50`, `cantidad ≤ 1000`. La KB no los fija; son límites defensivos (RN-18: ninguna entrada inválida termina en 500).
- **D4-b**: repetidos → **422** en el contrato (no 409). La restricción `UNIQUE(orden_id, repuesto_id)` queda como red de seguridad: si igual se dispara, el servicio la traduce a 409 genérico por nombre (`uq_item_orden_orden_id_repuesto_id`), nunca 500.
- **D4-c**: el cuerpo no acepta `mecanico_id`: la orden nace sin mecánico (lo asigna `iniciar`, C-10). Enviarlo → 422 (`extra="forbid"`).

### D5 — Flujo del alta en un único `async with uow`
Orden de pasos dentro del bloque (el servicio recibe `usuario_id` de la sesión):
1. `estados.get_por_codigo("PENDIENTE")` → `None` → `CatalogoSinCargarError` (409). **[APROBAR] D5-a**: se exige la fila PENDIENTE (no sólo "catálogo no vacío"): cubre el vacío y un catálogo parcial con la misma regla; el mensaje es "El catálogo de estados de orden no está cargado".
2. `vehiculos.get_vigente_para_orden(vehiculo_id)` con `SELECT ... WHERE borrado_en IS NULL FOR SHARE` → `None` → `VehiculoNoDisponibleError` (409).
3. `repuestos.listar_vigentes_para_orden(ids)` — **una** sentencia `WHERE id = ANY(:ids) AND borrado_en IS NULL ORDER BY id FOR SHARE` (ids ligados, nunca concatenados). Si faltan ids → `RepuestoNoDisponibleError` (409), un único mensaje que no distingue inexistente de dado de baja.
4. Cálculo en `Decimal`: `precio_unitario = repuesto.precio` (copia); `subtotal = cantidad * precio_unitario`; `total = sum(subtotales)`. Si `total > Decimal("9999999999.99")` → `TotalFueraDeRangoError` (409), **antes** de escribir (evita `DataError` → 500).
5. `ordenes.add(OrdenTrabajo(estado=PENDIENTE, mecanico_id=None, total=total, ...))` → flush (obtiene `id`).
6. `items.add_todos([...])` — un `add_all` + un `flush` (inserción por lotes, ordenada por `repuesto_id`).
7. `historial.add(HistorialEstadoOrden(desde_estado=None, hasta_estado=PENDIENTE, usuario_id=...))`.
8. `ordenes.get_detalle(id)` (D7) para devolver la respuesta ya precargada; el UoW confirma al salir.
Cualquier excepción atraviesa el bloque → rollback de todo (RN-10/RN-18). `IntegrityError` se traduce **fuera** del bloque, por nombre de restricción (FK de vehículo/repuesto → mismo 409 de no disponible; desconocida → 409 genérico).
*Alternativa descartada*: validar existencia dejando que la FK falle → no detecta "dado de baja" (borrado lógico) y obliga a parsear errores.

### D6 — Bloqueos `FOR SHARE` (coordinación con bajas y cambios de precio)
- Vehículo `FOR SHARE` vs. la baja (`FOR UPDATE` + `tiene_ordenes_abiertas`, C-07): si la baja llega primero, el alta espera y, al re-evaluar `borrado_en IS NULL`, no encuentra el vehículo → 409; si el alta llega primero, la baja espera su commit y su consulta de órdenes abiertas (sentencia nueva en READ COMMITTED) ve la orden PENDIENTE → 409. Nunca quedan ambas.
- Repuestos `FOR SHARE` en orden de `id`: la baja del repuesto (UPDATE) y el PATCH de precio (`FOR UPDATE`) esperan al alta, por lo que el `precio_unitario` copiado es el precio vigente al confirmar; el orden por `id` es el mismo que exige `mover_stock` en C-10 (sin interbloqueos entre altas y terminaciones).
- **[APROBAR] D6-a**: aceptar que un alta retiene brevemente bloqueos compartidos sobre vehículo y repuestos (una reposición o PATCH concurrente sobre esos repuestos espera milisegundos). Alternativa: sin bloqueos y aceptar la carrera (contradice el docstring de C-07).

### D7 — Detalle con número fijo de sentencias (C-15)
`OrdenRepository.get_detalle(id)`:
```
select(OrdenTrabajo).where(id == :id)
  .options(
    joinedload(OrdenTrabajo.vehiculo).joinedload(Vehiculo.cliente),   # 1 sentencia (JOIN)
    selectinload(OrdenTrabajo.items).joinedload(ItemOrden.repuesto),  # 1 sentencia (IN + JOIN)
    selectinload(OrdenTrabajo.historial),                             # 1 sentencia (IN)
  )
  .execution_options(populate_existing=True)
```
= **3 sentencias** para cualquier cantidad de ítems/historial (más las 2 constantes de la sesión: usuario y roles). `populate_existing` es necesario porque tras el alta la orden ya está en el mapa de identidad con `creada_en` (default del servidor) expirado y relaciones sin cargar: sin él, el acceso dispararía carga implícita (`lazy="raise"` / `MissingGreenlet`). El vehículo se lee **sin** filtrar `borrado_en` (una orden de un vehículo dado de baja sigue consultable). Ítems ordenados por `repuesto_id` y historial por `id` en el servicio (o con `order_by` en la relación del loader), coherentes con el orden de bloqueo de C-10.
Test: listener `before_cursor_execute` sobre `motor_auth.sync_engine` (patrón ya usado en `test_repositorios_clientes.py`) contando sentencias de `GET /ordenes/{id}` con 2 y con 4 ítems → iguales.

### D8 — Control de dueño en el detalle
`GET /ordenes/{id}` no usa `requiere_rol` (como `cancelar`, DD-09). El servicio: carga el detalle (404 si no existe); si `usuario.roles_vigentes ∩ {ADMIN, RECEPCION, MECANICO}` ≠ ∅ → permitido; si no, permitido sólo si `orden.vehiculo.cliente.usuario_id == usuario.id`; si no → `OrdenAjenaError` (403). La relación vehículo→cliente ya viene precargada (D7), sin sentencias extra.
- **[APROBAR] D8-a**: **404 antes que 403** para un no-dueño: un cliente puede distinguir "no existe" de "es ajena" (revela existencia de ids). Se acepta porque la tabla de endpoints lista ambos códigos y el detalle debe cargarse para conocer al dueño; la alternativa (403 también para inexistentes a no-personal) se puede adoptar si el usuario lo prefiere.
- **[APROBAR] D8-b**: un MECANICO ve el **detalle** de cualquier orden (también las asignadas a otro mecánico). DD-18 restringe sólo el **listado**; la tabla de endpoints dice "el personal" para el detalle.

### D9 — Listado por rol (DD-18) y mis órdenes
`OrdenRepository.buscar(estado, mecanico_visible, offset, limit)` / `contar(...)` sobre una consulta base `_filtrada` común (mismo patrón que `RepuestoRepository._filtrada`), garantizando que `total` use los mismos filtros. `mecanico_visible: int | None`: `None` → sin filtro (ADMIN/RECEPCION); id → `WHERE mecanico_id = :id OR mecanico_id IS NULL`. El servicio decide: si el usuario tiene ADMIN o RECEPCION vigente → `None`; si no (sólo MECANICO) → su id. Resumen sin relaciones (ninguna precarga necesaria), orden por `id` ascendente.
`listar_de_usuario(usuario_id, ...)`: `JOIN vehiculo JOIN cliente WHERE cliente.usuario_id = :uid`, **sin** filtrar `vehiculo.borrado_en`.
- **[APROBAR] D9-a**: `/mis-ordenes` incluye órdenes de vehículos dados de baja (sus datos se conservan, RN-16; el historial del cliente no desaparece). `/mis-vehiculos` sí los oculta.
- **[APROBAR] D9-b**: orden por `id` ascendente en `/ordenes` y `/mis-ordenes` (consistente con los demás listados); alternativa: más recientes primero.

### D10 — Respuestas
- `OrdenResumen`: `id, vehiculo_id, mecanico_id, estado, falla, creada_en, total` (Dinero).
- `OrdenDetalle(OrdenResumen)`: `items: list[ItemRespuesta]`, `historial: list[HistorialRespuesta]`.
- `ItemRespuesta`: `id, repuesto_id, codigo, descripcion` (del repuesto precargado), `cantidad, precio_unitario` (Dinero), `subtotal` (`@computed_field` Dinero = `cantidad * precio_unitario`, sin persistir).
- `EstadoOrdenRespuesta`: `codigo, descripcion, posicion, es_final`; `GET /estados-orden` devuelve `list[...]` (no paginado: el catálogo es chico y fijo).
- `POST /ordenes` responde 201 con `OrdenDetalle` (US-050: ítems, subtotal e historial).
- **[APROBAR] D10-a**: `ItemRespuesta` incluye `codigo` y `descripcion` del repuesto (útil para la UI y la evidencia; costo cero en sentencias gracias al `joinedload` de D7). Se leen aunque el repuesto esté dado de baja.

### D11 — Router y montaje
`router_ordenes = APIRouter(tags=["ordenes"])` con rutas absolutas (`/ordenes`, `/ordenes/{orden_id}`, `/mis-ordenes`, `/estados-orden`), como el router de clientes. `POST /ordenes` con `requiere_rol(RECEPCION, ADMIN)`; `GET /ordenes` con `requiere_rol(ADMIN, RECEPCION, MECANICO)`; detalle, mis órdenes y catálogo con `UsuarioActualDep` (el grupo protegido ya aplica `exigir_acceso`). `main.py`: agregar `router_ordenes` a `protegidos` (una línea). Errores de dominio → `_http_desde` único: `NoEncontradoError` → 404, `OrdenAjenaError` → 403, `ConflictoError` (catálogo, vehículo, repuesto, total, genérico) → 409.

### D12 — Compatibilidad con C-10: `iniciar` y `mecanico_id`
C-09 deja `mecanico_id` siempre nulo al crear y los filtros de D9 ya contemplan órdenes con y sin mecánico. Para C-10 se **recomienda** (no se implementa aquí):
- **[APROBAR] D12-a (recomendada)**: `iniciar` sobre una orden PENDIENTE **asigna siempre** `mecanico_id = actor` (RN-11 "el mecánico queda asignado"); como el alta nunca pre-asigna, en la práctica toda orden PENDIENTE tiene `mecanico_id` nulo y no hay conflicto de reasignación. Si existiera una PENDIENTE pre-asignada a otro mecánico (sólo posible por seed/SQL), `iniciar` por un tercero → 409.
- Alternativa: permitir pre-asignar en el alta (`mecanico_id` en el cuerpo) → contradice US-050 (el cuerpo es `vehiculo_id, falla, items`).
El seed (C-11) carga la orden #2 EN_REPARACION con `mecanico_id` de `mecanico@example.com`, coherente con esta regla.

### D13 — Tests
- Unitarios (`test/unit/test_schemas_ordenes.py`, `test/unit/test_ordenes_estatico.py`): contrato de alta, subtotal/serialización Decimal, repositorio de catálogo sin métodos de escritura, servicio/router `async def`, sin `commit(` en repositorios.
- Integración (`test/integration/ordenes/`) con `conftest.py` propio que sobrescribe `app_auth` montando `router_ordenes` (patrón de `test/integration/repuestos/conftest.py`) y ayudantes de siembra con SQL ligado (reusar `ayudantes_clientes.sembrar_*` y `repuestos/ayudantes.sembrar_repuesto`). PostgreSQL real, sin mocks de la base. Incluye: total/precios copiados, rollback total ante cada 409, catálogo vacío, repetidos 422, DD-18, filtro estado, 403 dueño ajeno, número constante de sentencias (2 vs 4 ítems), baja concurrente de vehículo serializada (dos sesiones).

## Risks / Trade-offs

- [`populate_existing` olvidado tras el alta → carga implícita y 500] → `get_detalle` siempre lo usa; test HTTP del 201 verifica `creada_en` e ítems.
- [Desborde de `NUMERIC(12,2)` en `total` → `DataError`/500] → validación previa en el servicio (D5 paso 4) + topes del contrato (D4-a); test con precio máximo.
- [Ids fuera de BIGINT en el cuerpo → `DataError`/500] → topes en el contrato (D4).
- [Bloqueos compartidos retrasan reposiciones/PATCH concurrentes] → transacción corta (sin bcrypt ni IO externo dentro); aceptado (D6-a).
- [Enum y catálogo desalineados (DD-02)] → el alta exige PENDIENTE en el catálogo; C-11 carga los cuatro; un test compara los valores del enum con el catálogo sembrado.
- [El conteo de sentencias se vuelve frágil si cambian las dependencias de auth] → el test compara 2 vs 4 ítems (igualdad), no un número absoluto; el número absoluto (3 del detalle) se afirma sólo filtrando sentencias que tocan `orden_trabajo`/`item_orden`/`historial_estado_orden`.
- [404 antes que 403 revela existencia de ids a clientes] → aceptado (D8-a), reversible sin tocar el esquema.

## Migration Plan

Sin migraciones. Despliegue: código nuevo + una línea en `main.py`. Rollback: quitar `router_ordenes` de `protegidos` (las tablas ya existen desde C-03).

## Decisiones a aprobar (resumen)

1. **D2-a** — `EstadoOrdenCodigo(StrEnum)` en `ordenes/models.py` (sin tocar columnas).
2. **D4-a** — Topes: `falla ≤ 500`, `items ≤ 50`, `cantidad ≤ 1000`.
3. **D5-a** — Alta exige la fila PENDIENTE en el catálogo (vacío o parcial → 409 con mensaje propio).
4. **D6-a** — `FOR SHARE` sobre vehículo y repuestos (ordenados por `id`) durante el alta.
5. **D8-a** — Detalle: 404 antes que 403 para no-personal.
6. **D8-b** — MECANICO ve el detalle de cualquier orden (DD-18 sólo aplica al listado).
7. **D9-a** — `/mis-ordenes` incluye órdenes de vehículos dados de baja.
8. **D9-b** — Listados por `id` ascendente.
9. **D10-a** — Ítems del detalle con `codigo` y `descripcion` del repuesto.
10. **D12-a** — Para C-10: `iniciar` asigna siempre al mecánico que inicia; el alta nunca pre-asigna (DD-18 pendiente).
11. **SU-C09-1** — Repuesto inexistente y dado de baja comparten mensaje 409 ("Algún repuesto no existe o fue dado de baja"); ídem vehículo.
12. **SU-C09-2** — `historial_estado_orden.usuario_id` del alta = usuario que abre la orden.
