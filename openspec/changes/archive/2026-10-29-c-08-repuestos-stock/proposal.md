# Proposal — C-08 `repuestos-stock`

## Why

Tras C-05 la API sabe quién es cada usuario y qué rol tiene, pero el inventario no existe: no hay forma de cargar repuestos, consultar el catálogo, reponer stock ni ver la trazabilidad de precios y movimientos. Sin catálogo no hay órdenes (C-09 copia el precio del repuesto y rechaza repuestos dados de baja) ni terminación (C-10 descuenta stock), y el seed (C-11) necesita los repuestos con su movimiento "Stock inicial". Es uno de los dos eslabones (con C-07) que abren GATE 5 del camino crítico y concentra los casos C-12 (reponer), C-16 (búsqueda, paginación con filtro, PATCH de stock → 422) y C-18 (historial de precios) de la evaluación, más RN-14, RN-15, RN-16 y RN-20.

## What Changes

- **Módulo `app/modules/repuestos/`** (schemas, repository, unit_of_work, stock, service, router) sobre los modelos `Repuesto`, `MovimientoStock` y `HistorialPrecioRepuesto` que dejó C-03 (sin tocar tablas ni migraciones).
- **Router `/repuestos`** en el **grupo protegido**:
  - `POST /repuestos` (ADMIN; 201/409/422): alta con `codigo`, `descripcion`, `precio` y `stock_inicial`; si `stock_inicial > 0` deja un `movimiento_stock` "Stock inicial" con el usuario que actúa, en la **misma** transacción; código vigente repetido → 409 por nombre de restricción (`uq_repuesto_codigo_vigente`).
  - `GET /repuestos` (ADMIN, RECEPCION, MECANICO; 200/422): búsqueda `q` por descripción (parámetros ligados, comodines de `LIKE` escapados), paginado con el envoltorio común; los dados de baja no aparecen.
  - `GET /repuestos/{id}` (ADMIN, RECEPCION, MECANICO; 200/404).
  - `PATCH /repuestos/{id}` (ADMIN; 200/404/422): **sólo** `descripcion` y `precio` (`extra="forbid"`: `stock` o `codigo` → 422); un cambio de precio escribe `historial_precio_repuesto` (anterior/nuevo) en la **misma** transacción; mismo precio → no escribe línea.
  - `DELETE /repuestos/{id}` (ADMIN; 204/404): borrado lógico; el código queda libre.
  - `POST /repuestos/{id}/reponer` (ADMIN; 200/404/422/409): cuerpo `{cantidad}` entero > 0 (DD-20), movimiento positivo con motivo "Reposición", responde el repuesto actualizado.
  - `GET /repuestos/{id}/movimientos` y `GET /repuestos/{id}/precios` (ADMIN; 200/404/422; RECEPCION y MECANICO → 403), paginados.
- **Punto único de escritura de stock** (`app/modules/repuestos/stock.py`, RN-14): `mover_stock(...)` — incremento relativo y atómico en la base + movimiento en la misma transacción; el `CHECK stock >= 0` traducido a `StockInsuficienteError`. Lo usan alta y reposición y lo reutilizará C-10 al terminar órdenes (firma fijada ahora; la lógica de órdenes queda fuera).
- **Dinero como `Decimal`** de punta a punta: entrada con 2 decimales como máximo y tope de `NUMERIC(10,2)`; salida JSON como **cadena** con 2 decimales (`"8500.00"`), nunca `float`.
- **`main.py`**: registra `router_repuestos` en el grupo protegido (archivo compartido con C-06/C-07).
- **Tests** (Strict TDD): unitarios de contratos y estáticos (sin `commit()`, `stock` sólo por el punto único) e integración HTTP contra **PostgreSQL real** con el esquema migrado por Alembic (incluye disparador de sólo agregado, atomicidad e invariante "stock = suma de movimientos").

## Capabilities

### New Capabilities
- `catalogo-repuestos`: alta (con 409 por código vigente), consulta, búsqueda paginada, edición de descripción y precio, baja lógica de repuestos, contrato de dinero y permisos de lectura/escritura.
- `stock-repuestos`: el stock sólo cambia por movimientos (stock inicial, reposición y, en C-10, terminación de órdenes) a través de un punto único atómico; reposición; trazabilidad de movimientos.
- `historial-precios-repuesto`: cada cambio de precio deja una línea anterior/nuevo en la misma transacción, un PATCH sin cambio de precio no deja línea, y la consulta del historial es sólo para ADMIN.

### Modified Capabilities
- (ninguna) — `grupos-de-rutas`, `autorizacion`, `paginacion`, `repositorios` y `solo-agregado` se **usan** tal como están; sus requisitos no cambian.

## Impact

- **Código nuevo**: `app/modules/repuestos/{schemas,repository,unit_of_work,stock,service,router}.py`; tests en `test/unit/` (contratos, estáticos) y `test/integration/repuestos/` (con su propio `conftest.py` que extiende la app de prueba, sin modificar el `conftest.py` compartido).
- **Código modificado**: `main.py` (una línea: `router_repuestos` en `protegidos`). **Archivo compartido** con C-06 y C-07: ver design.md §Archivos compartidos para secuenciar el apply.
- **Sin cambios** en `app/core/*` (sólo se reutilizan `restriccion_violada`, `SoftDeleteRepository`, `UnitOfWork`, paginación y `requiere_rol`), ni en modelos ni migraciones.
- **APIs**: 8 rutas nuevas bajo `/repuestos` en el grupo protegido.
- **Dependencias**: ninguna nueva.
- **Desbloquea**: C-09 (junto con C-07), C-10 (punto único de stock) y C-11 (alta de repuestos con "Stock inicial", historial de precios del seed).
- **Fuera de alcance**: órdenes y su terminación (C-09/C-10), `seed.py` (C-11), archivos `.http` (C-12), concurrencia de la verificación previa de stock de C-10 (DD-11).
- **Governance**: **ALTO** — el diseño (en especial D3, D4, D6 y los supuestos SU-C08-*) debe revisarse y aprobarse antes de `/opsx:apply`.
