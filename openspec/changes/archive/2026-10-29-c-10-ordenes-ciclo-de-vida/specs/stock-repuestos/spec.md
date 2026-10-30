# Spec Delta — stock-repuestos

## MODIFIED Requirements

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
