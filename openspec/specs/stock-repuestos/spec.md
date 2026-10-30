# stock-repuestos Specification

## Purpose

Garantiza que el stock de un repuesto sólo cambie mediante movimientos registrados (stock inicial, reposición y, desde C-10, terminación de órdenes), de forma atómica y trazable, sin quedar nunca negativo, y expone la reposición y la consulta de movimientos al ADMIN.

## Requirements

### Requirement: El stock sólo cambia por movimientos
Todo cambio del stock de un repuesto SHALL ocurrir en la misma transacción que la inserción de exactamente una fila de `movimiento_stock` cuya `cantidad` es la variación aplicada (positiva para entradas, negativa para salidas), con el `usuario_id` del usuario que actúa, un `motivo` no vacío y `orden_id` nulo salvo en salidas por órdenes. O quedan el stock nuevo y su movimiento, o ninguno de los dos. Para todo repuesto, el stock MUST ser igual a la suma de las cantidades de sus movimientos (cuando todo stock se cargó por la API). Ninguna ruta de la API MUST permitir fijar el stock directamente. Una variación de 0 MUST rechazarse sin escribir nada.

#### Scenario: Invariante tras varias operaciones
- **WHEN** un ADMIN da de alta un repuesto con `stock_inicial` 10 y luego lo repone con 5 y con 3
- **THEN** el stock es 18, hay tres movimientos (10, 5 y 3) y su suma es 18

#### Scenario: Falla al registrar el movimiento
- **WHEN** la inserción del movimiento falla después de aplicar la variación del stock en una reposición
- **THEN** la respuesta no es 2xx, el stock quedó como antes y no quedó ningún movimiento nuevo

#### Scenario: Alta con stock inicial cero
- **WHEN** un ADMIN da de alta un repuesto con `stock_inicial` 0 (o sin `stock_inicial`)
- **THEN** el repuesto queda con stock 0 y sin ningún movimiento

### Requirement: Movimiento de stock inicial
Un alta con `stock_inicial` mayor que 0 MUST registrar, en la misma transacción que el alta, un movimiento con `cantidad` igual a `stock_inicial`, `motivo` "Stock inicial", `orden_id` nulo y el `usuario_id` del ADMIN que da el alta. Si el alta falla (por ejemplo, 409 por código repetido), no MUST quedar el movimiento.

#### Scenario: Movimiento del alta
- **WHEN** el ADMIN con id 7 da de alta un repuesto con `stock_inicial` 10
- **THEN** existe exactamente un movimiento del repuesto con `cantidad` 10, `motivo` "Stock inicial", `usuario_id` 7 y `orden_id` nulo

### Requirement: Reposición de stock
`POST /repuestos/{id}/reponer` SHALL recibir exactamente `{cantidad}`, un entero JSON entre 1 y 1000000; un campo extra, una cantidad de 0, negativa, decimal, en cadena, booleana o mayor que el tope MUST responder 422 sin cambios. Sobre un repuesto vigente MUST sumar `cantidad` al stock y registrar un movimiento con esa `cantidad`, `motivo` "Reposición", `orden_id` nulo y el `usuario_id` del ADMIN, y MUST responder 200 con el repuesto actualizado (mismo formato que `GET /repuestos/{id}`). Un repuesto inexistente o dado de baja MUST responder 404 sin cambios. Si el stock resultante superara el máximo representable (2147483647), MUST responderse 409 con un mensaje propio y sin cambios, nunca 500.

#### Scenario: Reponer
- **WHEN** un ADMIN repone 5 unidades de un repuesto con stock 2
- **THEN** la respuesta es 200 con `stock` 7 y existe un movimiento nuevo con `cantidad` 5 y `motivo` "Reposición"

#### Scenario: Cantidad inválida
- **WHEN** un ADMIN envía `{"cantidad": 0}`, `{"cantidad": -3}`, `{"cantidad": 1.5}`, `{"cantidad": "5"}` o `{"cantidad": 5, "motivo": "x"}`
- **THEN** la respuesta es 422 y ni el stock ni los movimientos cambiaron

#### Scenario: Reponer un repuesto dado de baja
- **WHEN** un ADMIN repone un repuesto dado de baja o inexistente
- **THEN** la respuesta es 404 y no quedó ningún movimiento nuevo

#### Scenario: Recepción no repone
- **WHEN** un usuario con rol RECEPCION envía `POST /repuestos/{id}/reponer`
- **THEN** la respuesta es 403 y el stock no cambió

#### Scenario: Desborde del stock
- **WHEN** un repuesto tiene stock 2147483000 y un ADMIN repone 1000
- **THEN** la respuesta es 409 con un mensaje propio y el stock no cambió

### Requirement: Reposiciones concurrentes sin pérdida
Dos variaciones de stock concurrentes sobre el mismo repuesto MUST aplicarse ambas: el stock final MUST reflejar la suma de todas las variaciones confirmadas (sin actualizaciones perdidas del stock).

#### Scenario: Dos reposiciones simultáneas
- **WHEN** dos ADMIN reponen 5 unidades del mismo repuesto con stock 0 al mismo tiempo
- **THEN** ambas respuestas son 200, el stock final es 10 y hay dos movimientos de 5

### Requirement: Stock nunca negativo
Una salida de stock que dejara el stock por debajo de 0 MUST rechazarse como conflicto de dominio (stock insuficiente) sin aplicar la variación ni registrar el movimiento; la base de datos MUST rechazar cualquier stock negativo como última garantía, aun bajo concurrencia. La única ruta que produce salidas es la terminación de órdenes (`POST /ordenes/{id}/terminar`): cada salida lleva el `orden_id` de la orden y, si cualquier ítem no alcanza, la terminación MUST responder 409 sin dejar ninguna salida ni movimiento de esa operación.

#### Scenario: Salida mayor que el stock
- **WHEN** se aplica, mediante el punto único de escritura de stock, una salida de 4 unidades sobre un repuesto con stock 2
- **THEN** la operación falla con el error de stock insuficiente, el stock sigue en 2 y no quedó ningún movimiento nuevo

#### Scenario: Salidas concurrentes que juntas no alcanzan
- **WHEN** dos transacciones concurrentes aplican cada una una salida de 2 unidades sobre un repuesto con stock 3
- **THEN** exactamente una se confirma, la otra falla con stock insuficiente, y el stock final es 1

#### Scenario: Dos órdenes que compiten por el mismo repuesto
- **WHEN** dos órdenes EN_REPARACION piden 2 unidades cada una de un repuesto con stock 3 y sus mecánicos asignados las terminan a la vez
- **THEN** exactamente una responde 200, la otra 409 sin cambios, y el stock final es 1 con un único movimiento de -2

### Requirement: Movimientos de sólo agregado
Los movimientos registrados por la API MUST NOT poder modificarse ni borrarse (la base rechaza UPDATE y DELETE sobre `movimiento_stock`), y ninguna ruta de la API MUST ofrecer modificarlos.

#### Scenario: Modificar un movimiento creado por la API
- **WHEN** tras una reposición se intenta `UPDATE movimiento_stock SET cantidad = 999` sobre ese movimiento directamente en la base
- **THEN** la base rechaza la sentencia y el movimiento conserva su cantidad

### Requirement: Consulta de movimientos
`GET /repuestos/{id}/movimientos` SHALL devolver, sólo a ADMIN, los movimientos del repuesto en orden cronológico (por `id` ascendente) con el envoltorio común de paginación; cada elemento MUST incluir `id`, `repuesto_id`, `orden_id`, `usuario_id`, `cantidad`, `motivo` y `cuando`. Un repuesto inexistente o dado de baja MUST responder 404. RECEPCION y MECANICO MUST recibir 403.

#### Scenario: Movimientos tras alta y reposición
- **WHEN** un ADMIN consulta los movimientos de un repuesto dado de alta con `stock_inicial` 10 y repuesto con 5
- **THEN** la respuesta es 200 con `total` 2 y los elementos "Stock inicial" (10) y "Reposición" (5) en ese orden

#### Scenario: Recepción consulta movimientos
- **WHEN** un usuario con rol RECEPCION pide `GET /repuestos/{id}/movimientos`
- **THEN** la respuesta es 403
