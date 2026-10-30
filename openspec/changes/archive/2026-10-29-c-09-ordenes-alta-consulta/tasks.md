# Tasks — C-09 `ordenes-alta-consulta`

> Governance **MEDIO**: NO empezar sin el visto bueno del usuario sobre §"Decisiones a aprobar" de `design.md` (D2-a, D4-a, D5-a, D6-a, D8-a, D8-b, D9-a, D9-b, D10-a, D12-a, SU-C09-1/2). Checkpoint con el usuario al cerrar los grupos 4 y 6.
> Strict TDD: en cada tarea de comportamiento, primero el test en ROJO (ejecutado y fallando), luego el mínimo código en VERDE, TRIANGULAR (≥ 2 casos por comportamiento) y REFACTOR con la suite en verde tras cada paso.
> Skills: `fastapi`, `async-python-patterns`, `python-testing-patterns`, `sqlalchemy-alembic-expert-best-practices-code-review`, `postgres-patterns`. Referencias: `design.md` (D1..D13), `specs/{alta-ordenes,consulta-ordenes,estados-orden}/spec.md`.
> Reglas: dinero sólo `Decimal` (salida en cadena con 2 decimales); repositorios sólo `flush()`; el router construye el UoW (dependencia) y el servicio lo abre con `async with` UNA vez por operación; sin carga perezosa (precarga en el repositorio); `extra="forbid"` en toda entrada; SQL con parámetros ligados; integración contra PostgreSQL real (sin mocks de la base). No crear migraciones, no cambiar columnas, no tocar `app/core/*`, `test/integration/conftest.py` ni `CHANGES.md`. Nunca leer ni imprimir el `.env`. Sin build, commit ni push.

## 1. Safety net

- [x] 1.1 Ejecutar `pytest --exigir-db` en serie con PostgreSQL levantado y registrar la línea base tras C-08 ("N passed, 0 skipped"); si algo falla, DETENER y reportar como falla preexistente (no corregir).

## 2. Contratos y enum (`app/modules/ordenes/schemas.py`, `models.py`; D2, D4, D10)

- [x] 2.1 RED → GREEN: `test/unit/test_schemas_ordenes.py` — `EstadoOrdenCodigo` tiene exactamente PENDIENTE, EN_REPARACION, TERMINADA, CANCELADA (StrEnum en `ordenes/models.py`, sin tocar columnas); verificar con el test y con `test/unit/test_modelos.py` en verde.
- [x] 2.2 RED → GREEN `OrdenAlta`/`ItemAlta`: válido con 1 y con 2 ítems; `items` vacío, 51 ítems, `repuesto_id` repetido, `cantidad` 0 / -1 / 1001 / `"2"` / `1.5` / `true`, `vehiculo_id` `"1"` / 0 / 2^63, `falla` sólo espacios o de 501 caracteres, y campos extra (`precio_unitario`, `total`, `estado`, `creada_en`, `mecanico_id`, `id`) en orden o ítem → `ValidationError`; `falla` recortada.
- [x] 2.3 RED → GREEN respuestas: `ItemRespuesta.subtotal` = `cantidad * precio_unitario` exacto (`2 × 8500.00 = "17000.00"`, `3 × 0.10 = "0.30"`), importes serializados como cadena con 2 decimales en JSON; `OrdenResumen`, `OrdenDetalle` (items + historial), `EstadoOrdenRespuesta` construidos `from_attributes`.

## 3. Repositorios (`ordenes/repository.py` + extensiones; D3, D6, D7, D9)

- [x] 3.1 RED → GREEN estático (`test/unit/test_ordenes_estatico.py`): `EstadoOrdenRepository` no expone `add`/`update`/`delete`; `HistorialEstadoOrdenRepository.update/delete` lanzan `NotImplementedError`; ningún `commit(` en `app/modules/ordenes/`; todo método público de repositorio/servicio/router es `async def`.
- [x] 3.2 RED → GREEN integración `test/integration/ordenes/test_repositorios_ordenes.py`: `EstadoOrdenRepository.listar_por_posicion()` devuelve el catálogo por `posicion` (sembrado desordenado) y `[]` vacío; `get_por_codigo` encuentra PENDIENTE y devuelve `None` para un código ausente.
- [x] 3.3 RED → GREEN `VehiculoRepository.get_vigente_para_orden` (clientes): devuelve el vigente, `None` para dado de baja o inexistente; el SQL capturado con `before_cursor_execute` contiene `FOR SHARE` y `borrado_en IS NULL` (una sola sentencia); `test/integration/test_repositorios_clientes.py` sigue en verde.
- [x] 3.4 RED → GREEN `RepuestoRepository.listar_vigentes_para_orden(ids)` (repuestos): una sola sentencia con `FOR SHARE`, ordenada por `id`, excluye dados de baja e inexistentes; ids ligados (sin concatenar); suite de `test/integration/repuestos/` en verde.
- [x] 3.5 RED → GREEN `OrdenRepository.get_detalle(id)`: precarga vehículo→cliente (JOIN), ítems→repuesto e historial; acceso a todas esas relaciones sin `MissingGreenlet`/`lazy="raise"`; `None` si no existe; vehículo dado de baja igual se carga; con `populate_existing`.
- [x] 3.6 RED → GREEN `OrdenRepository.buscar/contar` (filtro `estado` opcional y `mecanico_visible`) y `listar_de_usuario/contar_de_usuario`: triangulación con órdenes sin mecánico, de `mecanico` y de `mecanico2`, en dos estados, de dos clientes y de un vehículo dado de baja; `contar` coincide con `buscar` sin paginar; orden por `id`.
- [x] 3.7 GREEN `ItemOrdenRepository.add_todos` (un `flush`) y `OrdenesUoW` + `get_ordenes_uow` (D1) con `estados`, `ordenes`, `items`, `historial`, `vehiculos`, `repuestos`, `movimientos` sobre la misma sesión; test que verifica la sesión compartida y que `OrdenesUoW` satisface `ConStock` (llamada real a `mover_stock` dentro del UoW revertida al final).

## 4. Servicio de alta (`ordenes/service.py`; D5, D6)

- [x] 4.1 RED → GREEN `crear_orden(uow, datos, usuario_id)` feliz: orden PENDIENTE, `mecanico_id` nulo, `precio_unitario` copiado de cada repuesto, `total` decimal exacto (triangular con 1 y 2 ítems y precios con centavos), una línea de historial `null → PENDIENTE` firmada por el usuario; filas verificadas con SQL directo.
- [x] 4.2 RED → GREEN 409 sin rastro: catálogo vacío y catálogo sin PENDIENTE (`CatalogoSinCargarError`), vehículo inexistente y dado de baja (`VehiculoNoDisponibleError`), repuesto inexistente y dado de baja (`RepuestoNoDisponibleError`), total > 9999999999.99 (`TotalFueraDeRangoError`); en cada caso el conteo de `orden_trabajo`, `item_orden` e `historial_estado_orden` no cambia.
- [x] 4.3 RED → GREEN traducción de `IntegrityError` por nombre de restricción fuera del bloque (FK de vehículo/repuesto → 409 de no disponible; desconocida → `ConflictoError` genérico), sin texto de la base en el mensaje; forzar el caso con un doble que lance el `IntegrityError` tras el primer `flush` y verificar rollback total.
- [x] 4.4 RED → GREEN concurrencia D6 con dos sesiones reales: (a) baja de vehículo (`FOR UPDATE`) primero → alta espera y responde `VehiculoNoDisponibleError`; (b) alta primero → la baja ve la orden abierta y falla con `VehiculoConOrdenesAbiertasError`. Nunca quedan vehículo dado de baja + orden abierta.
- [x] 4.5 REFACTOR + checkpoint: suite de `test/integration/ordenes/` en verde; reportar al usuario el estado antes de seguir.

## 5. Servicios de consulta (`ordenes/service.py`; D8, D9)

- [x] 5.1 RED → GREEN `obtener_orden(uow, orden_id, usuario)`: personal (ADMIN, RECEPCION, MECANICO, incluido MECANICO no asignado) → detalle; dueño (usuario de la ficha del vehículo) → detalle; otro cliente → `OrdenAjenaError`; inexistente → `OrdenNoEncontradaError` (antes que el permiso, D8-a); ítems ordenados por `repuesto_id` e historial por `id`.
- [x] 5.2 RED → GREEN `listar_ordenes(uow, estado, usuario, params)`: ADMIN/RECEPCION todas; sólo MECANICO → suyas + sin asignar; MECANICO+ADMIN → todas; filtro `estado`; `verificar_pagina` con el total filtrado (página más allá → `PaginaFueraDeRangoError`).
- [x] 5.3 RED → GREEN `listar_mis_ordenes(uow, usuario_id, params)` (incluye vehículos dados de baja; sin ficha → página vacía) y `listar_estados(uow)` (por `posicion`).

## 6. Router, montaje y HTTP (`ordenes/router.py`, `main.py`; D11)

- [x] 6.1 Crear `test/integration/ordenes/{__init__.py,conftest.py,ayudantes.py}`: `conftest.py` sobrescribe `app_auth` montando `router_ordenes` (y `router_repuestos` para el caso de cambio de precio) como `test/integration/repuestos/conftest.py`; ayudantes reusan `ayudantes_clientes.sembrar_*`, `repuestos/ayudantes.sembrar_repuesto` y `sesiones.py`; verificar con un test de humo que `GET /estados-orden` sin cookie da 401.
- [x] 6.2 RED → GREEN `POST /ordenes` (`test_alta_http.py`): 201 con detalle (precios copiados, subtotales, total, historial; caso C-10 con dos ítems); 401 sin sesión, 403 cambio pendiente, 403 MECANICO y CLIENTE antes de validar el cuerpo; 422 contrato (vacío, repetido, extra, cantidad inválida); 409 repuesto inexistente / dado de baja, vehículo dado de baja, catálogo vacío — cada 409 con mensaje propio, sin texto de la base y sin filas nuevas; cambio de precio posterior (PATCH) no altera la orden.
- [x] 6.3 RED → GREEN `GET /ordenes` (`test_listado_http.py`): recepción ve todas; `mecanico2` no ve la de `mecanico` (DD-18); `estado=ARCHIVADA` → 422; `estado=PENDIENTE` filtra y `total` coincide; `page` fuera de rango con filtro → 422; CLIENTE → 403.
- [x] 6.4 RED → GREEN `GET /ordenes/{id}` y `GET /mis-ordenes` (`test_detalle_http.py`): dueño 200, cliente ajeno 403 sin datos de la orden (caso C-06), inexistente 404, `abc` → 422; mis órdenes sólo las propias, personal sin ficha → página vacía `total` 0 `pages` 1.
- [x] 6.5 RED → GREEN `GET /estados-orden` (`test_estados_http.py`): cuatro estados por posición con `es_final` correcto (caso C-17) para un CLIENTE; vacío → `[]`; sin sesión 401; `POST /estados-orden` → 405 sin cambios en la tabla.
- [x] 6.6 GREEN montaje: agregar `router_ordenes` a `protegidos` en `main.py` (una línea); `test/unit/test_main.py` / `test_grupos_rutas.py` verifican que las 5 rutas nuevas están en el grupo protegido (403 con cambio pendiente) y que ninguna está en el abierto.
- [x] 6.7 Checkpoint: reportar al usuario el estado de los grupos 5–6 antes de la evidencia C-15.

## 7. Número fijo de consultas (caso C-15, D7)

- [x] 7.1 RED → GREEN `test_consultas_detalle.py`: con un listener `before_cursor_execute` sobre `motor_auth.sync_engine`, `GET /ordenes/{id}` de una orden con 2 ítems y de otra con 4 ítems ejecutan la MISMA cantidad de sentencias; las que tocan `orden_trabajo`/`item_orden`/`historial_estado_orden` son exactamente 3; ninguna sentencia por ítem.
- [x] 7.2 Documentar en el docstring de `OrdenRepository.get_detalle` el plan de 3 sentencias y cómo reproducir la evidencia con `SQL_ECHO=true` (para las capturas de C-12, DD-22); verificar que el docstring menciona las tres opciones de carga.

## 8. Verify (entre apply y archive)

- [x] 8.1 Ejecutar la suite completa `pytest --exigir-db` **en serie** (sin `-n`/xdist ni otras corridas en paralelo) con PostgreSQL levantado; registrar "N passed, 0 skipped, 0 failed" y compararlo con la línea base de 1.1 (sólo se suman tests).
  - Nota (cierre de brechas de verify): se agregaron 7 tests (suite: 1329 passed, 0 skipped, 0 failed) para GAP-1 (rutas POST/GET /ordenes bajo `exigir_acceso` del grupo protegido, `test/unit/test_main.py`), GAP-2 (403 por `debe_cambiar_password` en `/ordenes`, `/ordenes/{id}`, `/mis-ordenes`), GAP-3 (detalle con repuesto dado de baja) y GAP-4 (MECANICO+ADMIN ve todas el listado).
- [x] 8.2 Chequeo spec-vs-código: recorrer cada `Requirement`/`Scenario` de `specs/alta-ordenes`, `specs/consulta-ordenes` y `specs/estados-orden` y anotar el test que lo cubre (archivo::función) o marcarlo como faltante; verificar las reglas duras (sin `commit(` en repositorios, UoW abierto una vez por operación en el servicio, `extra="forbid"`, `Decimal`, sin carga perezosa, router en `protegidos`).
- [x] 8.3 Reporte de verificación al usuario: resultado de 8.1, matriz requisito→test de 8.2, desvíos respecto de `design.md` y decisiones aprobadas, y recomendación (archivar o corregir).
