# Tasks — C-10 `ordenes-ciclo-de-vida`

> Governance **ALTO** (stock, concurrencia): NO empezar sin el visto bueno del usuario sobre §"Decisiones a aprobar" de `design.md` (D1-a, D2-a, D4-a..d, D5-a/b, D6-a/b, D7-a, SU-C10-1/2). Checkpoint con el usuario al cerrar los grupos 4, 5 y 7.
> Strict TDD: en cada tarea de comportamiento, primero el test en ROJO (ejecutado y fallando), luego el mínimo código en VERDE, TRIANGULAR (≥ 2 casos por comportamiento) y REFACTOR con la suite en verde tras cada paso.
> Skills: `fastapi`, `async-python-patterns`, `python-testing-patterns`, `sqlalchemy-alembic-expert-best-practices-code-review`, `postgres-patterns`. Referencias: `design.md` (D1..D11), `specs/{transiciones-orden,aviso-cliente,stock-repuestos}/spec.md`.
> Reglas: repositorios sólo `flush()`; el router construye el UoW (dependencia) y el servicio lo abre con `async with` UNA vez por operación (cada transición en un único bloque); `StockInsuficienteError` nunca se captura dentro del bloque; stock sólo vía `mover_stock` con ítems ordenados por `repuesto_id`; sin carga perezosa; `Decimal` para dinero; integración contra PostgreSQL real (sin mocks de la base). No crear migraciones ni cambiar columnas, no tocar `app/core/*`, `test/integration/conftest.py`, `main.py` ni `CHANGES.md`. Nunca leer ni imprimir el `.env`. Sin build, commit ni push. Correr pytest con `.venv/Scripts/python.exe -m pytest`.

## 1. Safety net

- [x] 1.1 Ejecutar `.venv/Scripts/python.exe -m pytest --exigir-db` en serie con PostgreSQL levantado y registrar la línea base tras C-09 ("N passed, 0 skipped"); si algo falla, DETENER y reportar como falla preexistente (no corregir).

## 2. Tabla de transiciones y errores de dominio (`ordenes/transiciones.py`, `service.py`; D1, D8)

- [x] 2.1 RED → GREEN `test/unit/test_transiciones_ordenes.py`: `destino(accion, estado)` para la matriz completa 3 acciones × 4 estados (3 válidas: INICIAR/PENDIENTE → EN_REPARACION, TERMINAR/EN_REPARACION → TERMINADA, CANCELAR/PENDIENTE → CANCELADA; 9 → `TransicionInvalidaError`) y un estado ajeno al enum (`"ARCHIVADA"`) → `TransicionInvalidaError`; función pura (sin E/S, sin `async`).
- [x] 2.2 RED → GREEN coherencia D1-a: los estados sin transiciones salientes en `TRANSICIONES` son exactamente {TERMINADA, CANCELADA}, los que el catálogo canónico marca `es_final` (usar el mismo catálogo que `sembrar_catalogo`).
- [x] 2.3 RED → GREEN errores nuevos en `service.py`: `SinPermisoSobreOrdenError` es `OrdenAjenaError` (→ 403), `TransicionInvalidaError`, `OrdenAsignadaAOtroError`, `StockInsuficienteOrdenError` son `ConflictoError` (→ 409); mensajes propios no vacíos; `TransicionInvalidaError` nombra estado y acción; `_http_desde` los traduce sin cambios (test directo de `_http_desde` con cada uno).
- [x] 2.4 GREEN constante `MOTIVO_ORDEN_TERMINADA = "Terminación de orden"` en `repuestos/stock.py` (exportada en `__all__`); suite `test/unit/test_repuestos_estatico.py` y `test/integration/repuestos/` en verde.

## 3. Repositorio: bloqueo de la orden (`ordenes/repository.py`; D2, D3)

- [x] 3.1 RED → GREEN `test/integration/ordenes/test_repositorios_ordenes.py`: `OrdenRepository.bloquear(id)` devuelve la orden (sin relaciones), `None` si no existe; el SQL capturado con `before_cursor_execute` es UNA sentencia sobre `orden_trabajo` con `FOR UPDATE` y el id ligado.
- [x] 3.2 RED → GREEN con dos sesiones reales (`test/integration/sesiones.py`): mientras la sesión A tiene la orden bloqueada y cambia su estado sin confirmar, `bloquear` en la sesión B espera; tras el commit de A, B lee el estado nuevo (`populate_existing`), no el del mapa de identidad.
- [x] 3.3 REFACTOR + estático (`test/unit/test_ordenes_estatico.py`): `bloquear` es `async def`; sigue sin haber `commit(` en `app/modules/ordenes/`.

## 4. Servicio `iniciar_orden` (D4)

- [x] 4.1 Ayudantes: agregar a `test/integration/ordenes/ayudantes.py` `stock_de(db, repuesto_id)`, `movimientos_de_orden(db, orden_id)` y `escenario_c11(db)` (bujía stock 2 y filtro stock 10; orden EN_REPARACION asignada a `mecanico` con 4 bujías y 1 filtro, con su historial previo) y `conteos_ciclo(db)` (`orden_trabajo`, `historial_estado_orden`, `movimiento_stock` + stocks); verificar con un test de humo que el escenario queda como dice la KB 04.
- [x] 4.2 RED → GREEN `test/integration/ordenes/test_servicio_transiciones.py::iniciar`: PENDIENTE sin mecánico → EN_REPARACION con `mecanico_id` = actor y una línea `PENDIENTE → EN_REPARACION` firmada por el actor (triangular con `mecanico` y `mecanico2`); el detalle devuelto trae el historial nuevo.
- [x] 4.3 RED → GREEN rechazos sin escrituras: inexistente → `OrdenNoEncontradaError`; EN_REPARACION / TERMINADA / CANCELADA → `TransicionInvalidaError`; PENDIENTE pre-asignada a otro → `OrdenAsignadaAOtroError`, pre-asignada al mismo → se inicia (SU-C10-1); catálogo sin EN_REPARACION → `CatalogoSinCargarError`; en cada caso `conteos_ciclo` y la fila de la orden no cambian.
- [x] 4.4 RED → GREEN traducción de `IntegrityError` fuera del bloque (D4-d): forzar la FK de `hasta_estado` con un doble que lance tras el primer `flush` → `CatalogoSinCargarError`; restricción desconocida → `ConflictoError` genérico; sin texto de la base en el mensaje; rollback total.
- [x] 4.5 RED → GREEN concurrencia: `mecanico` y `mecanico2` inician a la vez (dos sesiones, `asyncio.gather`) → uno éxito y otro `TransicionInvalidaError`; una sola línea `PENDIENTE → EN_REPARACION`; `mecanico_id` del ganador.
- [x] 4.6 Checkpoint: suite de `test/integration/ordenes/` en verde; reportar al usuario antes de `terminar`.

## 5. Servicio `terminar_orden` (D4, D5, D6)

- [x] 5.1 RED → GREEN feliz: con stock suficiente (triangular con 1 y 2 ítems), la orden queda TERMINADA, cada repuesto baja exactamente su cantidad, hay un movimiento por ítem con cantidad negativa, `orden_id`, `usuario_id` del actor y motivo `MOTIVO_ORDEN_TERMINADA`, una línea `EN_REPARACION → TERMINADA`; stock = suma de movimientos para cada repuesto; `mecanico_id` intacto cuando termina un ADMIN.
- [x] 5.2 RED → GREEN orden de descuento: con ítems insertados en orden inverso de `repuesto_id`, los `UPDATE repuesto` capturados con `before_cursor_execute` salen en `repuesto_id` ascendente; el servicio llama a `mover_stock` (test estático: `terminar_orden` no llama `sumar_stock` ni escribe `stock` directamente).
- [x] 5.3 RED → GREEN caso C-11 con `escenario_c11`: `StockInsuficienteOrdenError` con mensaje que nombra el `codigo` de la bujía (D5-b); estado EN_REPARACION, filtro sigue en 10 (aunque se procese antes), bujías en 2, sin movimientos ni historial nuevos; luego reponer 2 bujías vía `mover_stock`/reposición y terminar → éxito con un movimiento por ítem (caso C-12).
- [x] 5.4 RED → GREEN permisos y estado: mecánico no asignado → `SinPermisoSobreOrdenError` aun si la orden está TERMINADA o PENDIENTE (403 antes que 409); ADMIN y asignado sobre PENDIENTE/TERMINADA/CANCELADA → `TransicionInvalidaError`; inexistente → `OrdenNoEncontradaError` antes que el permiso; sin escrituras en cada rechazo.
- [x] 5.5 RED → GREEN ítem con repuesto dado de baja después del alta (D6-b): se descuenta y se registra su movimiento.
- [x] 5.6 RED → GREEN concurrencia: (a) asignado y ADMIN terminan a la vez la misma orden → una éxito, otra `TransicionInvalidaError`, un único movimiento por repuesto; (b) dos órdenes con 2 unidades cada una de un repuesto con stock 3 → una éxito, otra `StockInsuficienteOrdenError`, stock final 1; (c) dos órdenes que comparten dos repuestos con ítems cargados en orden opuesto terminan a la vez sin interbloqueo (timeout del test acotado).
- [x] 5.7 Checkpoint: suite de `test/integration/ordenes/` y `test/integration/repuestos/` en verde; reportar al usuario (gobernanza ALTO) antes de seguir.

## 6. Servicio `cancelar_orden` (D4)

- [x] 6.1 RED → GREEN: RECEPCION, ADMIN y el dueño (cliente vinculado a la ficha) cancelan una PENDIENTE → CANCELADA con línea `PENDIENTE → CANCELADA` firmada por el actor y sin movimientos de stock.
- [x] 6.2 RED → GREEN rechazos: otro cliente y MECANICO no dueño → `SinPermisoSobreOrdenError` aun sobre TERMINADA (403 antes que 409, D4-c); con permiso sobre EN_REPARACION/TERMINADA/CANCELADA → `TransicionInvalidaError`; inexistente → `OrdenNoEncontradaError`; sin escrituras.
- [x] 6.3 RED → GREEN concurrencia: `iniciar` y `cancelar` simultáneos sobre la misma PENDIENTE → exactamente uno éxito, el otro `TransicionInvalidaError`, una sola línea de historial nueva.

## 7. Aviso al cliente (`ordenes/avisos.py`; D7)

- [x] 7.1 RED → GREEN `test/unit/test_avisos_ordenes.py`: `avisar_cliente(5, 2)` hace `await asyncio.sleep(DEMORA_AVISO)` con `DEMORA_AVISO == 0.5` (sleep parcheado/espiado, nunca `time.sleep`) y luego un único `INFO` exacto `Aviso a cliente 5: orden 2 terminada` en el logger `app.modules.ordenes.avisos` (triangular con otros ids); una excepción interna se registra con `logger.exception` y no se propaga.
- [x] 7.2 Checkpoint corto: reportar al usuario el formato del log antes de cablearlo en el router.

## 8. Router, montaje y HTTP (`ordenes/router.py`; D9, D4-a/b, D7)

- [x] 8.1 Actualizar `test/integration/ordenes/conftest.py` para montar también `router_clientes` en `protegidos` (para los tests de baja de vehículo); verificar que la suite de órdenes existente sigue en verde.
- [x] 8.2 RED → GREEN `test/integration/ordenes/test_iniciar_http.py`: 200 con `OrdenDetalle` (estado, `mecanico_id`, ítems con subtotal, historial con 2 líneas); 401 sin cookie; 403 cambio pendiente; 403 ADMIN-sin-MECANICO, RECEPCION y CLIENTE (también sobre id inexistente → 403, no 404); 422 `abc`; 404 inexistente; 409 ya iniciada / pre-asignada a otro, cada 409 con mensaje propio sin texto de la base y sin filas nuevas; tras iniciar, `mecanico` ya no ve en `GET /ordenes` la orden iniciada por `mecanico2`.
- [x] 8.3 RED → GREEN `test/integration/ordenes/test_terminar_http.py`: 200 (C-12 tras reponer vía `POST /repuestos/{id}/reponer`); 409 caso C-11 con estado/stock/movimientos/historial intactos verificados por SQL y por `GET /repuestos/{id}/movimientos`; 403 mecánico no asignado (también sobre TERMINADA); 403 CLIENTE/RECEPCION antes de 404; 404 inexistente; 409 PENDIENTE; 401; 403 cambio pendiente; 422 `abc`.
- [x] 8.4 RED → GREEN aviso por HTTP (`caplog`, `DEMORA_AVISO` parcheada a 0): exactamente un aviso con `cliente_id` y `orden_id` correctos tras 200 de `terminar` (incluido un cliente sin usuario, D7-a); ninguno tras 409 (C-11), 403, 404, ni tras `iniciar`/`cancelar`. Test directo del handler con una instancia de `BackgroundTasks`: al retornar la tarea está agendada (`avisar_cliente` con esos argumentos) y aún no se ejecutó.
- [x] 8.5 RED → GREEN `test/integration/ordenes/test_cancelar_http.py` (caso C-13): dueño cancela su PENDIENTE 200; cliente ajeno 403; ajena TERMINADA 403 (no 409); recepción/dueño sobre TERMINADA 409; MECANICO no dueño 403; 404; 401; 403 cambio pendiente; 422 `abc`; sin movimientos de stock.
- [x] 8.6 RED → GREEN interacción con la baja de vehículo (D10): con la única orden PENDIENTE, `DELETE /vehiculos/{id}` → 409; tras cancelarla → 204. Con la orden EN_REPARACION → 409; tras terminarla → 204.
- [x] 8.7 RED → GREEN pertenencia a grupos (patrón de la brecha GAP-1/GAP-2 de C-09) en `test/unit/test_main.py`: el test que contaba cinco rutas de órdenes pasa a ocho; las tres rutas nuevas están en el grupo protegido con `exigir_acceso`, en ningún grupo abierto, y declaran `requiere_rol` según D9 (iniciar MECANICO; terminar MECANICO|ADMIN; cancelar ninguno).
- [x] 8.8 Checkpoint: reportar al usuario el estado de los grupos 6–8.

## 9. Verify (entre apply y archive)

- [x] 9.1 Ejecutar la suite completa `.venv/Scripts/python.exe -m pytest --exigir-db` **en serie** (sin `-n`/xdist ni ninguna otra corrida en paralelo) con PostgreSQL levantado; registrar "N passed, 0 skipped, 0 failed" y compararlo con la línea base de 1.1 (sólo se suman tests).
- [x] 9.2 Chequeo spec-vs-código requisito por requisito: recorrer cada `Requirement`/`Scenario` de `specs/transiciones-orden`, `specs/aviso-cliente` y `specs/stock-repuestos` (requisito modificado) y anotar el test que lo cubre (archivo::función) o marcarlo como faltante; cerrar cada faltante con un test antes de seguir.
- [x] 9.3 Auditoría de reglas duras: sin `commit(` en repositorios; cada transición abre el UoW una sola vez en el servicio y el router sólo lo construye por dependencia; ningún `except StockInsuficienteError` dentro del `async with`; stock sólo vía `mover_stock` en `repuesto_id` ascendente; sin carga perezosa (todo acceso a relaciones tras `get_detalle`); el aviso se agenda sólo tras el retorno del servicio; mensajes sin texto de la base; ningún handler bloqueante; sin cambios en migraciones, `app/core/*`, `main.py`.
- [x] 9.4 Reporte de verificación al usuario: resultado de 9.1, matriz requisito→test de 9.2, hallazgos de 9.3, desvíos respecto de `design.md` y decisiones aprobadas, y recomendación (archivar o corregir).
