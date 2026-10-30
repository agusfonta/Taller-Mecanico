# transiciones-orden Specification

## Purpose

Hace avanzar una orden de trabajo por su ciclo de vida (iniciar, terminar, cancelar) con permisos por actor, un orden fijo de evaluación de errores, historial por cada transición, descuento atómico del stock al terminar y serialización de transiciones concurrentes (RN-11, RN-12, RN-13, RN-14, RN-16, casos C-11, C-12, C-13).

## Requirements


### Requirement: Acceso a las rutas de transición
`POST /ordenes/{id}/iniciar`, `POST /ordenes/{id}/terminar` y `POST /ordenes/{id}/cancelar` SHALL pertenecer al grupo protegido: sin sesión MUST responder 401 y con el cambio de contraseña pendiente 403, sin ejecutar la transición. `iniciar` MUST ejecutarse sólo para usuarios con el rol MECANICO vigente en la base (un ADMIN sin MECANICO también recibe 403). `terminar` MUST ejecutarse sólo para usuarios con MECANICO o ADMIN vigente. En ambos casos el 403 por rol MUST responderse antes de validar el parámetro de ruta y antes de buscar la orden (no revela si existe). `cancelar` MUST ejecutarse para cualquier usuario autenticado; el permiso sobre la orden lo decide la regla de cancelación. Un `id` no entero MUST responder 422 sin ejecutar la transición. Ninguna de las tres rutas MUST tomar de la petición el estado destino, el mecánico ni el actor: el destino lo fija la acción y el actor sale de la sesión (un cuerpo enviado se ignora).

#### Scenario: Transición sin sesión
- **WHEN** se llama `POST /ordenes/1/iniciar`, `/terminar` o `/cancelar` sin cookie
- **THEN** la respuesta es 401 y la orden no cambia

#### Scenario: Cambio de contraseña pendiente
- **WHEN** un MECANICO con `debe_cambiar_password` verdadero llama `POST /ordenes/1/iniciar`, `/terminar` o `/cancelar`
- **THEN** la respuesta es 403 y la orden no cambia

#### Scenario: Iniciar sin rol MECANICO
- **WHEN** un usuario con sólo ADMIN o sólo RECEPCION llama `POST /ordenes/{id}/iniciar` sobre una orden PENDIENTE
- **THEN** la respuesta es 403 y la orden sigue PENDIENTE sin mecánico

#### Scenario: Rol insuficiente antes que orden inexistente
- **WHEN** un CLIENTE llama `POST /ordenes/999999/iniciar` o `POST /ordenes/999999/terminar`
- **THEN** la respuesta es 403, no 404

#### Scenario: Id no entero
- **WHEN** un MECANICO llama `POST /ordenes/abc/iniciar`
- **THEN** la respuesta es 422

### Requirement: Máquina de estados de la orden
Las únicas transiciones permitidas MUST ser: `iniciar` PENDIENTE → EN_REPARACION, `terminar` EN_REPARACION → TERMINADA y `cancelar` PENDIENTE → CANCELADA. Cualquier otra combinación de acción y estado actual (incluida la repetición de una transición ya aplicada) MUST responder 409 con un mensaje propio que no contenga texto de la base, y MUST NOT modificar la orden, el stock, los movimientos ni el historial. TERMINADA y CANCELADA no admiten ninguna transición. Si el catálogo `estado_orden` no tiene la fila del estado destino, la transición MUST responder 409 con un mensaje propio y sin cambios, nunca 500.

#### Scenario: Iniciar una orden ya iniciada
- **WHEN** un MECANICO llama `POST /ordenes/{id}/iniciar` sobre una orden EN_REPARACION asignada a él
- **THEN** la respuesta es 409 y la orden, su mecánico y su historial no cambian

#### Scenario: Terminar una orden pendiente
- **WHEN** un ADMIN llama `POST /ordenes/{id}/terminar` sobre una orden PENDIENTE
- **THEN** la respuesta es 409, el stock de sus repuestos no cambia y no hay movimientos nuevos

#### Scenario: Cancelar una orden en reparación
- **WHEN** recepción llama `POST /ordenes/{id}/cancelar` sobre una orden EN_REPARACION
- **THEN** la respuesta es 409 y la orden sigue EN_REPARACION

#### Scenario: Estados finales sin salida
- **WHEN** sobre una orden TERMINADA o CANCELADA un usuario con permiso llama `iniciar`, `terminar` o `cancelar`
- **THEN** cada respuesta es 409 y la orden no cambia

#### Scenario: Catálogo sin el estado destino
- **WHEN** la fila EN_REPARACION no está en `estado_orden` y un MECANICO inicia una orden PENDIENTE
- **THEN** la respuesta es 409 con un mensaje propio y la orden sigue PENDIENTE sin mecánico

### Requirement: Iniciar una orden
`iniciar` sobre una orden PENDIENTE sin mecánico MUST pasarla a EN_REPARACION y asignar como `mecanico_id` al usuario que la inicia, en la misma transacción que la línea de historial. Si la orden PENDIENTE ya tuviera asignado a otro mecánico, MUST responder 409 sin cambios; si la tiene asignada al mismo usuario que la inicia, MUST iniciarla. Una orden inexistente MUST responder 404.

#### Scenario: Mecánico inicia una orden pendiente
- **WHEN** `mecanico2` llama `POST /ordenes/{id}/iniciar` sobre una orden PENDIENTE sin mecánico
- **THEN** la respuesta es 200, la orden queda EN_REPARACION con `mecanico_id` igual al id de `mecanico2` y su historial termina con `PENDIENTE → EN_REPARACION` firmado por `mecanico2`

#### Scenario: Orden iniciada deja de verse para otro mecánico
- **WHEN** `mecanico2` inició una orden y luego `mecanico` llama `GET /ordenes`
- **THEN** esa orden no aparece en el listado de `mecanico`

#### Scenario: Pendiente pre-asignada a otro mecánico
- **WHEN** una orden PENDIENTE tiene `mecanico_id` de `mecanico` y `mecanico2` llama `iniciar`
- **THEN** la respuesta es 409 y la orden no cambia

#### Scenario: Iniciar una orden inexistente
- **WHEN** un MECANICO llama `POST /ordenes/999999/iniciar`
- **THEN** la respuesta es 404

### Requirement: Permiso y estado al terminar
`terminar` MUST permitirse sólo al mecánico asignado a la orden o a un usuario con ADMIN vigente. Una orden inexistente MUST responder 404. Para una orden existente, un usuario sin ese permiso MUST recibir 403 **antes** de evaluar el estado: un mecánico no asignado recibe 403 aunque la orden no esté EN_REPARACION. Con permiso, una orden que no está EN_REPARACION MUST responder 409. Un ADMIN que termina una orden MUST NOT cambiar su `mecanico_id`.

#### Scenario: Mecánico no asignado
- **WHEN** `mecanico2` llama `POST /ordenes/{id}/terminar` sobre una orden EN_REPARACION asignada a `mecanico`
- **THEN** la respuesta es 403 y la orden, el stock y el historial no cambian

#### Scenario: Permiso antes que estado al terminar
- **WHEN** `mecanico2` llama `terminar` sobre una orden TERMINADA asignada a `mecanico`
- **THEN** la respuesta es 403, no 409

#### Scenario: Administrador termina la orden de otro
- **WHEN** un ADMIN termina una orden EN_REPARACION asignada a `mecanico` con stock suficiente
- **THEN** la respuesta es 200, la orden queda TERMINADA con `mecanico_id` de `mecanico` y la línea de historial está firmada por el ADMIN

#### Scenario: Terminar una orden inexistente
- **WHEN** un ADMIN llama `POST /ordenes/999999/terminar`
- **THEN** la respuesta es 404

### Requirement: Terminar descuenta el stock de forma atómica
Al terminar, por cada ítem de la orden MUST descontarse del stock de su repuesto la cantidad del ítem y registrarse exactamente un movimiento de stock con `cantidad` negativa igual a la del ítem, `orden_id` de la orden, `usuario_id` del actor y un `motivo` fijo no vacío; además la orden MUST quedar TERMINADA y agregarse una línea de historial. Todas esas escrituras MUST confirmarse juntas o ninguna. El descuento MUST aplicarse también a ítems cuyo repuesto fue dado de baja después de crear la orden. El stock de cada repuesto MUST seguir siendo igual a la suma de sus movimientos.

#### Scenario: Reponer y terminar la orden con bujías (caso C-12)
- **WHEN** una orden EN_REPARACION asignada a `mecanico` pide 4 bujías y 1 filtro, el ADMIN repone 2 bujías (stock 4) y `mecanico` la termina
- **THEN** la respuesta es 200 con la orden TERMINADA, el stock de bujías queda en 0, el del filtro baja en 1, hay un movimiento de -4 y otro de -1, ambos con el `orden_id`, y una línea de historial `EN_REPARACION → TERMINADA`

#### Scenario: Ítem de un repuesto dado de baja
- **WHEN** un repuesto de la orden se dio de baja mientras la orden estaba EN_REPARACION y el mecánico asignado la termina con stock suficiente
- **THEN** la respuesta es 200 y su stock se descuenta con su movimiento

### Requirement: Stock insuficiente al terminar
Si el stock de cualquiera de los repuestos de la orden no alcanza para su ítem, `terminar` MUST responder 409 con un mensaje propio que identifique el repuesto sin texto de la base, y MUST NOT dejar ninguna escritura: el estado, el stock de **todos** los repuestos (también los ya descontados en esa operación), los movimientos y el historial MUST quedar como estaban.

#### Scenario: Terminar la orden con más bujías que stock (caso C-11)
- **WHEN** una orden EN_REPARACION asignada a `mecanico` pide 1 filtro (stock 10) y 4 bujías (stock 2), y `mecanico` la termina
- **THEN** la respuesta es 409, la orden sigue EN_REPARACION, el filtro sigue en 10, las bujías en 2, no hay movimientos nuevos y el historial no cambia

#### Scenario: Reintento tras el 409
- **WHEN** tras ese 409 el ADMIN repone las bujías faltantes y el mecánico vuelve a terminar
- **THEN** la respuesta es 200 y hay exactamente un movimiento de salida por ítem

### Requirement: Cancelar una orden
`cancelar` MUST permitirse a usuarios con RECEPCION o ADMIN vigente y al dueño del vehículo de la orden (el usuario vinculado a la ficha del cliente), aunque no tenga rol de personal. Una orden inexistente MUST responder 404. Para una orden existente, cualquier otro usuario (otro cliente, o un MECANICO que no es dueño) MUST recibir 403 **antes** de evaluar el estado. Con permiso, una orden que no está PENDIENTE MUST responder 409. La cancelación MUST NOT tocar el stock ni los movimientos.

#### Scenario: El dueño cancela su orden pendiente (caso C-13)
- **WHEN** el cliente dueño del vehículo llama `POST /ordenes/{id}/cancelar` sobre su orden PENDIENTE
- **THEN** la respuesta es 200, la orden queda CANCELADA y su historial termina con `PENDIENTE → CANCELADA` firmado por el cliente

#### Scenario: Cliente cancela una orden ajena
- **WHEN** otro cliente llama `cancelar` sobre esa orden PENDIENTE
- **THEN** la respuesta es 403 y la orden sigue PENDIENTE

#### Scenario: Permiso antes que estado al cancelar
- **WHEN** otro cliente llama `cancelar` sobre una orden TERMINADA ajena
- **THEN** la respuesta es 403, no 409

#### Scenario: Cancelar una orden terminada
- **WHEN** recepción o el dueño llaman `cancelar` sobre una orden TERMINADA
- **THEN** la respuesta es 409 y la orden sigue TERMINADA

#### Scenario: Mecánico sin ser dueño
- **WHEN** un usuario con sólo MECANICO llama `cancelar` sobre una orden PENDIENTE de la que no es dueño
- **THEN** la respuesta es 403

### Requirement: Historial de cada transición
Cada transición confirmada MUST agregar exactamente una línea a `historial_estado_orden` con `desde_estado` igual al estado anterior, `hasta_estado` igual al nuevo, `usuario_id` del actor y `cuando` asignado por la base, en la misma transacción que el cambio de estado. Una transición rechazada (403, 404 o 409) MUST NOT agregar líneas.

#### Scenario: Ciclo completo
- **WHEN** una orden se crea, un mecánico la inicia y luego la termina
- **THEN** su historial tiene, por `id`, `null → PENDIENTE`, `PENDIENTE → EN_REPARACION` y `EN_REPARACION → TERMINADA`, firmadas por recepción, el mecánico y el mecánico

#### Scenario: Transición rechazada sin historial
- **WHEN** una transición responde 403, 404 o 409
- **THEN** la cantidad de líneas de historial de la orden no cambia

### Requirement: Respuesta de una transición
Una transición confirmada MUST responder 200 con el detalle de la orden en el mismo formato que `GET /ordenes/{id}` (ítems con subtotales, total, `mecanico_id`, estado nuevo e historial completo, incluida la línea recién agregada).

#### Scenario: Detalle tras iniciar
- **WHEN** un MECANICO inicia una orden con dos ítems
- **THEN** el cuerpo trae `estado` EN_REPARACION, su `mecanico_id`, los dos ítems con subtotal y dos líneas de historial

### Requirement: Transiciones concurrentes sobre la misma orden
Dos transiciones simultáneas sobre la misma orden MUST serializarse: la segunda MUST decidir con el estado que dejó la primera. Nunca MUST quedar una orden con dos líneas de historial que partan del mismo estado, ni un stock descontado dos veces por la misma orden.

#### Scenario: Dos mecánicos inician a la vez
- **WHEN** `mecanico` y `mecanico2` llaman `iniciar` al mismo tiempo sobre la misma orden PENDIENTE
- **THEN** una respuesta es 200 y la otra 409, la orden queda asignada a quien obtuvo 200 y hay una sola línea `PENDIENTE → EN_REPARACION`

#### Scenario: Dos terminaciones simultáneas
- **WHEN** el mecánico asignado y un ADMIN terminan a la vez la misma orden EN_REPARACION con stock suficiente
- **THEN** una respuesta es 200 y la otra 409, y cada repuesto tiene un único movimiento de salida para esa orden

#### Scenario: Iniciar y cancelar a la vez
- **WHEN** un MECANICO inicia y recepción cancela al mismo tiempo la misma orden PENDIENTE
- **THEN** exactamente una responde 200 y la otra 409, y la orden queda en el estado de la que respondió 200

### Requirement: Cerrar la orden libera el vehículo
Una vez que una orden queda TERMINADA o CANCELADA (estados finales del catálogo), esa orden MUST dejar de impedir la baja de su vehículo; mientras esté PENDIENTE o EN_REPARACION la MUST seguir impidiendo.

#### Scenario: Baja tras cancelar
- **WHEN** la única orden de un vehículo estaba PENDIENTE, se cancela y luego un ADMIN llama `DELETE /vehiculos/{id}`
- **THEN** la baja responde 204

#### Scenario: Baja con la orden en reparación
- **WHEN** la única orden del vehículo está EN_REPARACION y se llama `DELETE /vehiculos/{id}`
- **THEN** la respuesta es 409; tras terminarla, la baja responde 204
