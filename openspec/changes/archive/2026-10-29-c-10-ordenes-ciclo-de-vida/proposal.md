# Proposal — C-10 `ordenes-ciclo-de-vida`

## Why

Después de C-09 una orden de trabajo nace PENDIENTE y se puede consultar, pero no avanza: ningún mecánico puede tomarla, nadie puede terminarla (y por lo tanto el stock nunca se descuenta) y ni la recepción ni el dueño pueden cancelarla. C-10 cierra el ciclo de vida (RN-11, RN-12, RN-13, US-051/052/053) y es la única operación multi-escritura de stock del sistema: el caso C-11 (terminar la orden #2 con 4 bujías y stock 2 → 409 sin dejar rastro) y C-12/C-13 dependen de él, y C-12 (`verificacion-y-entrega`) lo necesita para la corrida end-to-end.

## What Changes

- `POST /ordenes/{id}/iniciar` (sólo MECANICO, IN-02): PENDIENTE → EN_REPARACION; asigna **siempre** `mecanico_id` al mecánico que la inicia (DD-18 / D12-a de C-09); responde 200 con el detalle de la orden.
- `POST /ordenes/{id}/terminar` (mecánico asignado o ADMIN): EN_REPARACION → TERMINADA en **un único** `async with uow`: por cada ítem, ordenado por `repuesto_id`, una salida de stock vía `mover_stock` con `orden_id`; cambio de estado y línea de `historial_estado_orden`. Stock insuficiente en cualquier ítem → 409 y rollback total (estado, stock, movimientos, historial). Permiso (403) antes que estado (409).
- `POST /ordenes/{id}/cancelar` (RECEPCION, ADMIN o dueño del vehículo, sin `requiere_rol`, DD-09): PENDIENTE → CANCELADA; ajena 403; en cualquier otro estado 409; 403 evaluado antes que 409.
- Máquina de estados declarada en código sobre `EstadoOrdenCodigo` (DD-02): cualquier transición no listada → 409. Toda transición confirmada agrega exactamente una línea de historial firmada por el actor.
- Concurrencia: la orden se bloquea con `SELECT … FOR UPDATE` antes de decidir; dos transiciones simultáneas sobre la misma orden se serializan y la segunda responde 409 (o la que corresponda al nuevo estado).
- Aviso simulado al cliente (DD-10, DD-21): `BackgroundTasks` agenda `await asyncio.sleep(0.5)` + `logger.info` con texto fijo **sólo** cuando `terminar` confirmó; corre después de enviar la respuesta.
- Las tres rutas se montan en el grupo protegido (cambio de contraseña pendiente → 403).
- Sin migraciones ni cambios de columnas; sin rutas nuevas fuera de `/ordenes/{id}/*`.

## Capabilities

### New Capabilities
- `transiciones-orden`: máquina de estados de la orden (iniciar, terminar, cancelar), quién puede ejecutar cada transición, orden de evaluación 401/403/404/409, historial por transición, asignación del mecánico, descuento atómico de stock al terminar y serialización de transiciones concurrentes.
- `aviso-cliente`: aviso simulado al cliente tras terminar una orden, en segundo plano, sólo si hubo commit, con formato de log estable.

### Modified Capabilities
- `stock-repuestos`: el requisito "Stock nunca negativo" deja de decir que no hay ninguna ruta que produzca salidas; ahora la terminación de órdenes produce salidas (una por ítem, con `orden_id`) y el stock insuficiente se traduce en 409 sin escrituras.

## Impact

- **Código**: `app/modules/ordenes/` (`transiciones.py` nuevo con la tabla de transiciones pura, `avisos.py` nuevo, `service.py`, `repository.py`, `router.py`); `app/modules/repuestos/stock.py` (sólo una constante de motivo nueva, sin cambiar `mover_stock`).
- **API**: tres rutas nuevas `POST /ordenes/{id}/{iniciar|terminar|cancelar}` (200/403/404/409; 401 sin sesión; 422 id no entero).
- **Datos**: escribe `orden_trabajo.estado`/`mecanico_id`, `historial_estado_orden`, `repuesto.stock` y `movimiento_stock` (estas dos sólo vía `mover_stock`). Sin migraciones.
- **Interacción**: `DELETE /vehiculos/{id}` (C-07) vuelve a permitirse cuando todas las órdenes del vehículo quedan TERMINADA/CANCELADA (catálogo `es_final`); el listado del MECANICO (DD-18) deja de mostrar a otros mecánicos la orden que alguien inició.
- **Tests**: `test/unit/` (tabla de transiciones, estático, montaje en `test_main.py`: el test que hoy cuenta cinco rutas de órdenes pasa a ocho) y `test/integration/ordenes/` con PostgreSQL real, incluido el escenario C-11 reproducido con ayudantes (el seed es C-11/pendiente).
- **Fuera de alcance**: seed (C-11), archivos `.http` y evidencias (C-12), reasignar mecánico, reabrir órdenes, cancelar EN_REPARACION, colas reales para el aviso.
