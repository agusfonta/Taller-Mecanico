# Spec Delta — alta-ordenes

## Purpose

Permite que la recepción y el administrador registren el ingreso de un vehículo como una orden de trabajo PENDIENTE con sus ítems, con precios copiados del repuesto, total calculado por el servidor y primera línea de historial, de forma atómica (RN-10, RN-16, RN-19, Flujo 5, caso C-10).

## ADDED Requirements

### Requirement: Acceso al alta de orden
`POST /ordenes` SHALL pertenecer al grupo protegido y MUST ejecutarse sólo para usuarios con un rol vigente en la base RECEPCION o ADMIN. Sin sesión MUST responder 401, con el cambio de contraseña pendiente 403 y sin esos roles 403, evaluado antes que la validación del cuerpo y que la existencia del vehículo o los repuestos.

#### Scenario: Mecánico intentando abrir una orden
- **WHEN** un usuario con sólo el rol MECANICO llama `POST /ordenes` con un cuerpo válido
- **THEN** la respuesta es 403 y no se creó ninguna fila en `orden_trabajo`, `item_orden` ni `historial_estado_orden`

#### Scenario: Cliente intentando abrir una orden para su vehículo
- **WHEN** un usuario con sólo el rol CLIENTE llama `POST /ordenes` sobre un vehículo de su ficha
- **THEN** la respuesta es 403

#### Scenario: Alta sin sesión
- **WHEN** se llama `POST /ordenes` sin cookie
- **THEN** la respuesta es 401

### Requirement: Contrato del alta de orden
`POST /ordenes` MUST recibir exactamente `vehiculo_id`, `falla` e `items`. `vehiculo_id` MUST ser un entero positivo (textos, decimales y booleanos MUST rechazarse). `falla` MUST ser un texto no vacío tras quitar espacios en los extremos y con longitud máxima acotada. `items` MUST ser una lista de entre 1 y un máximo acotado de elementos, cada uno con exactamente `repuesto_id` (entero positivo) y `cantidad` (entero estricto mayor que 0 y con máximo acotado), y MUST NOT repetir un `repuesto_id`. Los campos `precio_unitario`, `total`, `estado`, `creada_en`, `mecanico_id`, `id` o cualquier otro campo extra, en la orden o en un ítem, MUST responder 422. Toda violación del contrato MUST responder 422 sin escribir nada.

#### Scenario: Orden sin ítems
- **WHEN** se envía `items` como lista vacía
- **THEN** la respuesta es 422 y no se creó ninguna fila

#### Scenario: Repuesto repetido
- **WHEN** se envían dos ítems con el mismo `repuesto_id`
- **THEN** la respuesta es 422 y no se creó ninguna fila

#### Scenario: Precio en el cuerpo
- **WHEN** un ítem trae `precio_unitario` o la orden trae `total` o `estado`
- **THEN** la respuesta es 422

#### Scenario: Cantidad inválida
- **WHEN** un ítem trae `cantidad` 0, -1, `"2"`, `1.5` o `true`
- **THEN** la respuesta es 422

#### Scenario: Falla vacía
- **WHEN** se envía `falla` compuesta sólo por espacios
- **THEN** la respuesta es 422

### Requirement: La orden nace PENDIENTE con precios copiados y total del servidor
Un alta válida MUST crear una fila de `orden_trabajo` con `estado` PENDIENTE, `mecanico_id` nulo, la `falla` recibida y `creada_en` asignada por la base; MUST crear una fila de `item_orden` por ítem recibido con el `precio_unitario` igual al `precio` vigente del repuesto en ese momento; y MUST guardar como `total` la suma exacta (decimal, sin redondeo intermedio a punto flotante) de `cantidad × precio_unitario` de todos los ítems. Un cambio posterior del precio del repuesto MUST NOT modificar el `precio_unitario` ni el `total` de órdenes ya creadas. MUST responder 201 con el detalle de la orden definido en `consulta-ordenes`.

#### Scenario: Alta con dos ítems
- **WHEN** recepción abre una orden con 2 unidades de un repuesto de precio 8500.00 y 1 unidad de otro de precio 1200.50
- **THEN** la respuesta es 201, el estado es PENDIENTE, los ítems muestran `precio_unitario` "8500.00" y "1200.50" con subtotales "17000.00" y "1200.50", y el total es "18200.50"

#### Scenario: Cambio de precio posterior
- **WHEN** después del alta el administrador cambia el precio de uno de los repuestos
- **THEN** el detalle de la orden sigue mostrando el `precio_unitario` y el `total` originales

#### Scenario: El total no viene del cliente
- **WHEN** se consulta la fila guardada en `orden_trabajo`
- **THEN** su `total` coincide con la suma de los subtotales calculada desde `item_orden`

### Requirement: Primera línea del historial de estados
El alta MUST agregar exactamente una fila de `historial_estado_orden` con `desde_estado` nulo, `hasta_estado` PENDIENTE y `usuario_id` igual al usuario que abrió la orden, en la misma transacción que la orden y sus ítems.

#### Scenario: Historial de la orden recién creada
- **WHEN** recepción abre una orden
- **THEN** la respuesta incluye un historial con una sola línea `desde_estado` null → `hasta_estado` PENDIENTE firmada por ese usuario

### Requirement: Vehículo y repuestos vigentes
El vehículo y cada repuesto de los ítems MUST existir y no estar dados de baja al confirmar el alta. Si el vehículo no existe o está dado de baja, o si algún repuesto no existe o está dado de baja, MUST responder 409 con un mensaje propio que no revele texto de la base y MUST NOT quedar ninguna fila de `orden_trabajo`, `item_orden` ni `historial_estado_orden` de ese intento. Una baja concurrente del vehículo MUST NOT dejar a la vez el vehículo dado de baja y una orden abierta suya creada por este alta.

#### Scenario: Repuesto inexistente
- **WHEN** recepción abre una orden con un ítem válido y otro cuyo `repuesto_id` no existe
- **THEN** la respuesta es 409 y no queda ninguna fila de la orden, de sus ítems ni de su historial

#### Scenario: Repuesto dado de baja
- **WHEN** un ítem referencia un repuesto dado de baja
- **THEN** la respuesta es 409 y no queda ninguna fila

#### Scenario: Vehículo dado de baja
- **WHEN** se abre una orden para un vehículo dado de baja
- **THEN** la respuesta es 409 y no queda ninguna fila

#### Scenario: Vehículo inexistente
- **WHEN** se abre una orden con un `vehiculo_id` que no existe
- **THEN** la respuesta es 409 y no queda ninguna fila

### Requirement: Catálogo de estados sin cargar
Si el catálogo `estado_orden` no contiene el estado PENDIENTE (en particular, si está vacío), el alta MUST responder 409 con un mensaje propio que indique que el catálogo de estados no está cargado y MUST NOT escribir ninguna fila.

#### Scenario: Catálogo vacío
- **WHEN** se abre una orden válida con la tabla `estado_orden` vacía
- **THEN** la respuesta es 409 con el mensaje del catálogo y no queda ninguna fila

### Requirement: Total dentro del rango admitido
Si el total calculado supera el máximo representable por la columna `total` (NUMERIC(12,2)), el alta MUST responder 409 con un mensaje propio, MUST NOT escribir ninguna fila y MUST NOT responder 500.

#### Scenario: Total desbordado
- **WHEN** los precios vigentes y las cantidades dan un total mayor que 9999999999.99
- **THEN** la respuesta es 409 y no queda ninguna fila

### Requirement: Alta atómica
La lectura del catálogo, del vehículo y de los repuestos y la escritura de la orden, sus ítems y su línea de historial MUST ocurrir en una sola transacción: o quedan todas las filas o ninguna. Ningún error del alta MUST responder 500 ni devolver texto interno de la base (RN-18).

#### Scenario: Falla a mitad del alta
- **WHEN** el alta falla después de insertar la orden (por ejemplo, por un repuesto inválido detectado tarde o una restricción de la base)
- **THEN** la respuesta es 409 y las tablas `orden_trabajo`, `item_orden` e `historial_estado_orden` quedan con las mismas filas que antes del intento
