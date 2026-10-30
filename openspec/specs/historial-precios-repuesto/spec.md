# historial-precios-repuesto Specification

## Purpose

Deja trazabilidad inmutable de cada cambio de precio de un repuesto (precio anterior, precio nuevo, quién y cuándo), escrita en la misma transacción que el cambio, y la expone sólo al ADMIN (RN-20).

## Requirements

### Requirement: Línea de historial por cada cambio de precio
Un `PATCH /repuestos/{id}` que envía un `precio` distinto (como valor decimal) del precio vigente SHALL actualizar el precio y MUST insertar, en la misma transacción, exactamente una fila de `historial_precio_repuesto` con `precio_anterior` igual al precio previo, `precio_nuevo` igual al nuevo y el `usuario_id` del ADMIN que actúa. O quedan el precio nuevo y su línea, o ninguno de los dos. Dos cambios de precio concurrentes sobre el mismo repuesto MUST quedar encadenados: el `precio_anterior` de cada línea MUST ser el precio que dejó el cambio confirmado antes.

#### Scenario: Cambio de precio
- **WHEN** un ADMIN cambia el precio de un repuesto de `8000.00` a `8500`
- **THEN** la respuesta es 200 con `precio` `"8500.00"` y existe una línea nueva con `precio_anterior` 8000.00 y `precio_nuevo` 8500.00

#### Scenario: Falla al registrar la línea
- **WHEN** la inserción de la línea de historial falla durante un cambio de precio
- **THEN** la respuesta no es 2xx y el precio del repuesto quedó como antes

#### Scenario: Dos cambios sucesivos
- **WHEN** un ADMIN cambia el precio de 8000 a 8500 y luego a 9000
- **THEN** hay dos líneas: 8000.00 → 8500.00 y 8500.00 → 9000.00

### Requirement: Sin línea cuando el precio no cambia
Un `PATCH /repuestos/{id}` que no envía `precio`, o que envía un precio numéricamente igual al vigente (por ejemplo `8000`, `"8000.0"` o `8000.00` frente a `8000.00`), MUST NOT insertar ninguna línea de historial y MUST responder 200 aplicando el resto de los campos enviados.

#### Scenario: PATCH sólo de descripción
- **WHEN** un ADMIN cambia el precio y luego envía un PATCH sólo con `descripcion`
- **THEN** el historial del repuesto tiene una sola línea

#### Scenario: Mismo precio con otra escritura
- **WHEN** el precio vigente es `8000.00` y un ADMIN envía `{"precio": "8000.0", "descripcion": "Filtro nuevo"}`
- **THEN** la respuesta es 200 con la descripción cambiada y el historial no tiene líneas nuevas

### Requirement: Historial de sólo agregado
Las líneas de historial de precios MUST NOT poder modificarse ni borrarse (la base rechaza UPDATE y DELETE sobre `historial_precio_repuesto`), y ninguna ruta de la API MUST ofrecer modificarlas.

#### Scenario: Modificar una línea creada por la API
- **WHEN** tras un cambio de precio se intenta `DELETE FROM historial_precio_repuesto` sobre esa línea directamente en la base
- **THEN** la base rechaza la sentencia y la línea sigue existiendo

### Requirement: Consulta del historial de precios
`GET /repuestos/{id}/precios` SHALL devolver, sólo a ADMIN, las líneas de historial del repuesto en orden cronológico (por `id` ascendente) con el envoltorio común de paginación; cada elemento MUST incluir `id`, `repuesto_id`, `usuario_id`, `precio_anterior` y `precio_nuevo` (cadenas con 2 decimales) y `cuando`. Un repuesto inexistente o dado de baja MUST responder 404. RECEPCION y MECANICO MUST recibir 403.

#### Scenario: Historial tras un cambio
- **WHEN** un ADMIN consulta `GET /repuestos/{id}/precios` después de cambiar el precio de 8000 a 8500
- **THEN** la respuesta es 200 con `total` 1 y un elemento con `precio_anterior` `"8000.00"` y `precio_nuevo` `"8500.00"`

#### Scenario: Recepción consulta precios
- **WHEN** un usuario con rol RECEPCION pide `GET /repuestos/{id}/precios`
- **THEN** la respuesta es 403

#### Scenario: Repuesto sin cambios de precio
- **WHEN** un ADMIN consulta el historial de un repuesto cuyo precio nunca cambió
- **THEN** la respuesta es 200 con `items` vacío, `total` 0 y `pages` 1
