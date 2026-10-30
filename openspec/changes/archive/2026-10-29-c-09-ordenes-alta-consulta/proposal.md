# Proposal — C-09 `ordenes-alta-consulta`

## Why

Los modelos de órdenes existen desde C-03, pero no hay API: la recepción no puede registrar el ingreso de un vehículo, nadie puede consultar órdenes ni el catálogo de estados, y C-10 (ciclo de vida), C-11 (seed) y los casos C-06, C-10, C-15 y C-17 dependen de ello. Con C-07 (vehículos) y C-08 (repuestos y stock) cerrados, es el siguiente paso del camino crítico.

## What Changes

- **Alta de orden** `POST /ordenes` (RECEPCION, ADMIN; 201/409/422): cuerpo `{vehiculo_id, falla, items[{repuesto_id, cantidad}]}` con `extra="forbid"`; ≥ 1 ítem y sin repuestos repetidos (422). La orden nace PENDIENTE y sin mecánico; el `precio_unitario` de cada ítem se copia del repuesto vigente y el `total` lo calcula el servidor; se agrega la primera línea de `historial_estado_orden` (`desde_estado = null`). Catálogo sin PENDIENTE, vehículo o repuesto inexistente o dado de baja → 409 con mensaje propio y sin ninguna fila escrita. Todo en un único `async with uow` (RN-10, RN-16, RN-19).
- **Consulta**:
  - `GET /ordenes` (ADMIN, RECEPCION, MECANICO; `estado`, `page`, `size`): el filtro `estado` es un enum declarado en el contrato (otro valor → 422). ADMIN y RECEPCION ven todas; el MECANICO ve las asignadas a él más las sin asignar (DD-18).
  - `GET /ordenes/{id}` (el personal o el dueño del vehículo; ajena → 403; inexistente → 404): detalle con ítems, subtotales e historial, resuelto con un **número fijo de consultas** independiente de la cantidad de ítems (caso C-15).
  - `GET /mis-ordenes` (cualquier autenticado; `page`, `size`): órdenes de los vehículos de la ficha del usuario (RN-17).
  - `GET /estados-orden` (cualquier autenticado): catálogo ordenado por `posicion` (caso C-17), servido por un repositorio de **sólo lectura** (RN-19).
- **Módulo `app/modules/ordenes/`** completo (schemas, repositorios, UoW, servicio, router) sobre los modelos de C-03, montado en el grupo protegido de `main.py`.
- **Extensiones puntuales** de repositorios existentes: lectura del vehículo vigente con `FOR SHARE` (coordinada con el `FOR UPDATE` de la baja de C-07) y lectura de repuestos vigentes por lote con `FOR SHARE`, ordenada por `id`.
- Sin migraciones ni cambios de modelos. Sin ningún cambio de estado posterior al alta (eso es C-10).

## Capabilities

### New Capabilities
- `alta-ordenes`: alta de una orden de trabajo con sus ítems, precios copiados, total calculado y primera línea de historial, atómica y con errores 409/422 propios.
- `consulta-ordenes`: listado filtrado y paginado por rol, detalle con número fijo de consultas y control de dueño, y "mis órdenes" del cliente.
- `estados-orden`: consulta del catálogo de estados de orden por posición, de sólo lectura desde la API.

### Modified Capabilities
<!-- Ninguna: los requisitos de vehiculos, catalogo-repuestos, stock-repuestos, paginacion, grupos-de-rutas y autorizacion se usan tal como están. -->

## Impact

- **Código nuevo**: `app/modules/ordenes/{schemas,repository,unit_of_work,service,router}.py`.
- **Código modificado**: `app/modules/clientes/repository.py` (un método `FOR SHARE`), `app/modules/repuestos/repository.py` (un método de lectura por lote `FOR SHARE`), `main.py` (una línea en `protegidos`).
- **API**: 5 rutas nuevas en el grupo protegido (`/ordenes`, `/ordenes/{id}`, `/mis-ordenes`, `/estados-orden`).
- **Tests**: unitarios de contratos y estáticos del módulo; integración contra PostgreSQL real en `test/integration/ordenes/` con su propio `conftest.py` (override de `app_auth`).
- **Dependencias aguas abajo**: C-10 reutiliza el UoW (cumple `ConStock` de `mover_stock`), los repositorios y el detalle; C-11 (seed) y C-12 (archivos `.http`, evidencia C-15) consumen estas rutas.
- Sin dependencias externas nuevas.
