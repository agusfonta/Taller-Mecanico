# catalogo-repuestos Specification

## Purpose

Define el catálogo de repuestos del taller: alta, consulta, búsqueda paginada, edición de descripción y precio y baja lógica, con el contrato de dinero exacto y los permisos por rol (el ADMIN mantiene el catálogo; recepción y mecánicos lo consultan).

## Requirements

### Requirement: Permisos sobre el catálogo
Todas las rutas `/repuestos` SHALL pertenecer al grupo protegido (401 sin sesión válida, 403 con cambio de contraseña pendiente). `GET /repuestos` y `GET /repuestos/{id}` MUST permitirse a usuarios con rol vigente ADMIN, RECEPCION o MECANICO. `POST /repuestos`, `PATCH /repuestos/{id}`, `DELETE /repuestos/{id}`, `POST /repuestos/{id}/reponer`, `GET /repuestos/{id}/movimientos` y `GET /repuestos/{id}/precios` MUST permitirse sólo a ADMIN. Un usuario sin un rol permitido MUST recibir 403 sin que la operación modifique ni lea datos del catálogo. El permiso (403) MUST evaluarse antes que la existencia del repuesto (404) y que la validación de un cuerpo JSON bien formado (422).

#### Scenario: 403 antes que 422
- **WHEN** un usuario con rol MECANICO envía `PATCH /repuestos/{id}` con `{"stock": 999}`
- **THEN** la respuesta es 403

#### Scenario: Recepción consulta el catálogo
- **WHEN** un usuario con rol RECEPCION pide `GET /repuestos`
- **THEN** la respuesta es 200 con el listado

#### Scenario: Cliente no consulta el catálogo
- **WHEN** un usuario con sólo rol CLIENTE pide `GET /repuestos` o `GET /repuestos/{id}`
- **THEN** la respuesta es 403

#### Scenario: Mecánico no da de alta
- **WHEN** un usuario con rol MECANICO envía `POST /repuestos` con un cuerpo válido
- **THEN** la respuesta es 403 y no se creó ninguna fila en `repuesto` ni en `movimiento_stock`

#### Scenario: Sin sesión
- **WHEN** se pide `GET /repuestos` sin cookie de sesión
- **THEN** la respuesta es 401

#### Scenario: 403 antes que 404
- **WHEN** un usuario con rol RECEPCION envía `PATCH /repuestos/999999` (inexistente)
- **THEN** la respuesta es 403

### Requirement: Contrato de dinero
Todo precio SHALL manejarse como decimal exacto, nunca como número de punto flotante. En la entrada, un precio MUST aceptarse como número JSON o como cadena numérica, MUST ser mayor que 0, MUST tener como máximo 2 decimales y MUST ser como máximo 99999999.99; un valor booleano, nulo, no numérico, `NaN`, infinito, con más de 2 decimales, cero, negativo o mayor que el tope MUST responderse con 422. En la salida, todo precio MUST serializarse como cadena con exactamente 2 decimales (por ejemplo `"8500.00"`).

#### Scenario: Precio como número y como cadena
- **WHEN** se da de alta un repuesto con `precio: 8500.5` y otro con `precio: "1200"`
- **THEN** ambas respuestas son 201 y muestran `precio` `"8500.50"` y `"1200.00"` respectivamente

#### Scenario: Precio con tres decimales
- **WHEN** se envía `precio: 10.005`
- **THEN** la respuesta es 422 y no se creó ninguna fila

#### Scenario: Precio no positivo o fuera de rango
- **WHEN** se envía `precio` igual a `0`, `-1`, `100000000` o `true`
- **THEN** la respuesta es 422 y nunca 500

### Requirement: Alta de repuesto
`POST /repuestos` SHALL recibir exactamente `codigo`, `descripcion`, `precio` y, opcionalmente, `stock_inicial`. Cualquier campo extra (por ejemplo `stock` o `id`) MUST responder 422. `codigo` MUST ser un texto de 1 a 50 caracteres tras quitar los espacios de los extremos y MUST guardarse en mayúsculas; `descripcion` MUST ser un texto de 1 a 200 caracteres tras quitar los espacios de los extremos; `stock_inicial` MUST ser un entero JSON entre 0 y 1000000 (por defecto 0; cadenas, booleanos o decimales → 422). Un alta válida MUST responder 201 con `id`, `codigo`, `descripcion`, `precio` y `stock` (igual a `stock_inicial`), y MUST NOT exponer `borrado_en`. Si existe otro repuesto **vigente** con el mismo código, MUST responderse 409 con un mensaje propio, sin texto de la base y sin filas sueltas; la unicidad MUST garantizarla la base, no una consulta previa.

#### Scenario: Alta con stock inicial
- **WHEN** un ADMIN envía `POST /repuestos` con `codigo: " fil-001 "`, `descripcion: "Filtro de aceite"`, `precio: 8000` y `stock_inicial: 10`
- **THEN** la respuesta es 201 con `codigo` `"FIL-001"`, `precio` `"8000.00"` y `stock` 10

#### Scenario: Código vigente repetido
- **WHEN** existe un repuesto vigente con código `FIL-001` y un ADMIN da de alta otro con código `fil-001`
- **THEN** la respuesta es 409 con un mensaje propio y no quedó ni un repuesto ni un movimiento nuevos

#### Scenario: Código de un repuesto dado de baja
- **WHEN** el repuesto con código `FIL-001` fue dado de baja y un ADMIN da de alta otro con ese código
- **THEN** la respuesta es 201

#### Scenario: Stock en lugar de stock inicial
- **WHEN** se envía `POST /repuestos` con un campo `stock: 5`
- **THEN** la respuesta es 422

#### Scenario: Campos vacíos o inválidos
- **WHEN** se envía `descripcion` compuesta sólo de espacios, o `stock_inicial: -1`, o `stock_inicial: "5"`
- **THEN** la respuesta es 422

### Requirement: Consulta y búsqueda paginada
`GET /repuestos` SHALL devolver sólo los repuestos vigentes (no dados de baja) con el envoltorio común de paginación (`page`, `size`, página más allá de la última → 422), ordenados por `id` ascendente. El parámetro opcional `q` (1 a 100 caracteres tras quitar espacios de los extremos) MUST filtrar por descripción que contenga `q` sin distinguir mayúsculas, tratando `q` como texto literal: los caracteres `%`, `_` y `\` no actúan como comodines y ningún valor de `q` MUST alterar la consulta. `total` MUST contar con el mismo filtro. `GET /repuestos/{id}` MUST devolver el repuesto vigente o 404 con un mensaje propio si no existe o está dado de baja.

#### Scenario: Búsqueda con intento de inyección
- **WHEN** se pide `GET /repuestos?q=' OR '1'='1`
- **THEN** la respuesta es 200 con `items` vacío y `total` 0

#### Scenario: Búsqueda con filtro y paginación
- **WHEN** hay un solo repuesto vigente cuya descripción contiene "freno" y se pide `GET /repuestos?q=FRENO&size=1`
- **THEN** la respuesta es 200 con `total` 1 y `pages` 1; y `GET /repuestos?q=freno&size=1&page=2` responde 422

#### Scenario: Comodín literal
- **WHEN** ningún repuesto tiene `%` en la descripción y se pide `GET /repuestos?q=%`
- **THEN** la respuesta es 200 con `total` 0

#### Scenario: Tamaño de página fuera de rango
- **WHEN** se pide `GET /repuestos?size=500`
- **THEN** la respuesta es 422

#### Scenario: Repuesto dado de baja no aparece
- **WHEN** un repuesto fue dado de baja
- **THEN** no figura en `GET /repuestos`, no cuenta en `total` y `GET /repuestos/{id}` responde 404

### Requirement: Edición parcial de descripción y precio
`PATCH /repuestos/{id}` SHALL aceptar sólo `descripcion` y `precio`, con las mismas reglas que en el alta, y MUST aplicar únicamente los campos enviados. Cualquier otro campo (en particular `stock` o `codigo`) MUST responder 422 sin cambios. Un campo enviado con valor nulo MUST responder 422. Un cuerpo vacío MUST responder 200 con el repuesto sin cambios. El repuesto inexistente o dado de baja MUST responder 404. La respuesta MUST ser 200 con el repuesto actualizado.

#### Scenario: PATCH del stock
- **WHEN** un ADMIN envía `PATCH /repuestos/{id}` con `{"stock": 999}`
- **THEN** la respuesta es 422 y el stock del repuesto no cambió

#### Scenario: PATCH parcial
- **WHEN** un ADMIN envía `PATCH /repuestos/{id}` con sólo `descripcion`
- **THEN** la respuesta es 200, cambió la descripción y el precio y el stock quedaron iguales

#### Scenario: PATCH de un repuesto dado de baja
- **WHEN** un ADMIN envía `PATCH /repuestos/{id}` sobre un repuesto dado de baja
- **THEN** la respuesta es 404

### Requirement: Baja lógica
`DELETE /repuestos/{id}` SHALL marcar el repuesto como dado de baja (fecha de baja) sin borrar su fila, sus movimientos ni su historial de precios, y MUST responder 204 sin cuerpo. Un repuesto inexistente o ya dado de baja MUST responder 404. Tras la baja, el código queda disponible para un repuesto nuevo.

#### Scenario: Baja exitosa
- **WHEN** un ADMIN envía `DELETE /repuestos/{id}` sobre un repuesto vigente con movimientos
- **THEN** la respuesta es 204, la fila sigue en `repuesto` con fecha de baja y sus movimientos siguen en `movimiento_stock`

#### Scenario: Baja repetida
- **WHEN** un ADMIN envía `DELETE /repuestos/{id}` dos veces
- **THEN** la segunda respuesta es 404
