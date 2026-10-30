# Spec Delta — `vehiculos`

## Purpose

Permite que el personal registre y dé de baja (lógica) vehículos de los clientes, con la patente única sólo entre los vigentes y sin perder datos de los dados de baja, y que cada usuario vea únicamente sus propios vehículos (RN-01, RN-16, RN-17, Flujo 9, caso C-19).

## ADDED Requirements

### Requirement: Acceso a las rutas de vehículos
`POST /clientes/{id}/vehiculos` y `DELETE /vehiculos/{id}` SHALL pertenecer al grupo protegido y MUST ejecutarse sólo para usuarios con un rol vigente en la base RECEPCION o ADMIN; sin sesión MUST responder 401, con el cambio de contraseña pendiente 403 y sin esos roles 403, evaluado antes que la existencia del recurso. `GET /mis-vehiculos` SHALL pertenecer al grupo protegido y MUST ejecutarse para cualquier usuario autenticado sin cambio de contraseña pendiente, tenga el rol que tenga.

#### Scenario: Cliente intentando dar de baja su propio vehículo
- **WHEN** un usuario con sólo el rol CLIENTE llama `DELETE /vehiculos/{id}` sobre un vehículo de su ficha
- **THEN** la respuesta es 403 y el vehículo sigue vigente

#### Scenario: Mecánico intentando cargar un vehículo
- **WHEN** un usuario con sólo el rol MECANICO llama `POST /clientes/{id}/vehiculos`
- **THEN** la respuesta es 403 y no se creó ninguna fila

#### Scenario: Mis vehículos sin sesión
- **WHEN** se llama `GET /mis-vehiculos` sin cookie
- **THEN** la respuesta es 401

#### Scenario: Mis vehículos con cambio de contraseña pendiente
- **WHEN** un usuario con el cambio de contraseña obligatorio pendiente llama `GET /mis-vehiculos`
- **THEN** la respuesta es 403

### Requirement: Contrato del alta de vehículo
`POST /clientes/{id}/vehiculos` MUST recibir exactamente `patente`, `marca`, `modelo` y `anio`. `marca` y `modelo` MUST ser textos no vacíos tras quitar espacios en los extremos y con longitud máxima acotada. `anio` MUST ser un número entero entre 1950 y 2100 inclusive (textos, decimales y booleanos MUST rechazarse). La `patente` MUST normalizarse quitando espacios y guiones y pasándola a mayúsculas, y el resultado MUST ser no vacío, sólo letras A–Z y dígitos, de a lo sumo 10 caracteres. Cualquier campo extra (por ejemplo `cliente_id` o `borrado_en`) o dato inválido MUST responder 422 sin escribir nada.

#### Scenario: Año fuera de rango
- **WHEN** se envía `anio` 1949 o 2101
- **THEN** la respuesta es 422 y no se creó ninguna fila

#### Scenario: Año en el borde
- **WHEN** se envía `anio` 1950 y, en otro vehículo, 2100
- **THEN** ambas altas responden 201

#### Scenario: Año como texto
- **WHEN** se envía `anio` igual a `"2020"`
- **THEN** la respuesta es 422

#### Scenario: Patente normalizada
- **WHEN** se envía la patente `" ab-123 cd "`
- **THEN** el vehículo queda guardado con patente `AB123CD` y la respuesta la muestra así

#### Scenario: Patente inválida
- **WHEN** se envía una patente con caracteres no alfanuméricos (por ejemplo `"AB*123"`) o vacía tras normalizar
- **THEN** la respuesta es 422

#### Scenario: Campo extra
- **WHEN** se envía `cliente_id` en el cuerpo
- **THEN** la respuesta es 422

### Requirement: Alta de vehículo de un cliente
Un alta válida sobre un cliente existente MUST crear una fila de `vehiculo` vigente vinculada al cliente de la ruta y MUST responder 201 con `id`, `cliente_id`, `patente`, `marca`, `modelo` y `anio`. Si el cliente de la ruta no existe MUST responder 404 con un mensaje propio y no escribir nada.

#### Scenario: Alta exitosa
- **WHEN** recepción carga un vehículo con patente nueva para un cliente existente
- **THEN** la respuesta es 201, el vehículo pertenece a ese cliente y aparece en `GET /clientes/{id}`

#### Scenario: Cliente inexistente
- **WHEN** se carga un vehículo válido para `/clientes/999999/vehiculos`
- **THEN** la respuesta es 404 y la cantidad de filas de `vehiculo` no cambió

### Requirement: Patente única entre los vehículos vigentes
Si ya existe un vehículo **no dado de baja** con la misma patente normalizada (de cualquier cliente), el alta MUST responder 409 con un mensaje propio sobre la patente y MUST NOT dejar fila nueva. Una patente que sólo pertenece a vehículos dados de baja MUST poder registrarse de nuevo, para el mismo o para otro cliente. La unicidad MUST garantizarla la base, sin consulta previa, y la respuesta MUST NOT contener texto de la base.

#### Scenario: Patente vigente repetida en otro cliente
- **WHEN** se carga para el cliente B una patente que ya tiene un vehículo vigente del cliente A
- **THEN** la respuesta es 409 con un mensaje propio y la cantidad de filas de `vehiculo` no cambió

#### Scenario: Patente repetida con otra escritura
- **WHEN** existe el vehículo vigente `AB123CD` y se carga `ab 123 cd`
- **THEN** la respuesta es 409

#### Scenario: Re-registro tras la baja (C-19)
- **WHEN** se da de baja un vehículo sin órdenes (204) y se carga la misma patente para otro cliente
- **THEN** la respuesta es 201; y una segunda carga de esa patente mientras el nuevo vehículo sigue vigente responde 409

### Requirement: Baja lógica de vehículo
`DELETE /vehiculos/{id}` sobre un vehículo vigente sin órdenes abiertas MUST registrar el instante de la baja en `borrado_en`, MUST NOT eliminar la fila ni sus órdenes, y MUST responder 204 sin cuerpo. Un vehículo dado de baja MUST dejar de aparecer en `GET /clientes/{id}` y en `GET /mis-vehiculos`. Si el vehículo no existe o ya estaba dado de baja MUST responder 404 con un mensaje propio.

#### Scenario: Baja exitosa
- **WHEN** recepción da de baja un vehículo sin órdenes
- **THEN** la respuesta es 204, la fila sigue en la base con `borrado_en` no nulo y el vehículo ya no aparece en el detalle de su cliente

#### Scenario: Baja repetida
- **WHEN** se llama dos veces `DELETE /vehiculos/{id}` sobre el mismo vehículo
- **THEN** la primera responde 204 y la segunda 404

#### Scenario: Vehículo inexistente
- **WHEN** se llama `DELETE /vehiculos/999999`
- **THEN** la respuesta es 404

### Requirement: No se da de baja un vehículo con órdenes abiertas
Una orden está abierta cuando su estado es una fila del catálogo `estado_orden` con `es_final` falso; la decisión MUST tomarse con el catálogo y no con una lista fija de estados en el código. Si el vehículo tiene al menos una orden abierta, la baja MUST responder 409 con un mensaje propio y MUST NOT modificar el vehículo. Las órdenes en estados finales MUST NOT impedir la baja. Una baja y el alta de una orden para el mismo vehículo que ocurren a la vez MUST NOT dejar una orden abierta sobre un vehículo dado de baja.

#### Scenario: Orden pendiente
- **WHEN** se da de baja un vehículo con una orden en un estado no final (por ejemplo PENDIENTE o EN_REPARACION)
- **THEN** la respuesta es 409 con un mensaje propio y `borrado_en` sigue nulo

#### Scenario: Sólo órdenes finales
- **WHEN** se da de baja un vehículo cuyas órdenes están todas en estados finales (por ejemplo TERMINADA y CANCELADA)
- **THEN** la respuesta es 204 y sus órdenes se conservan

#### Scenario: El catálogo decide
- **WHEN** el catálogo marca como final un estado de nombre arbitrario y el vehículo sólo tiene órdenes en ese estado
- **THEN** la baja responde 204

### Requirement: Mis vehículos
`GET /mis-vehiculos` MUST responder 200 con una lista JSON de los vehículos **vigentes** de la ficha de cliente vinculada al usuario de la sesión, cada uno con `id`, `cliente_id`, `patente`, `marca`, `modelo` y `anio`, ordenados por `id`. MUST NOT incluir vehículos de otros clientes ni dados de baja. Un usuario sin ficha de cliente vinculada (por ejemplo, personal) MUST recibir 200 con la lista vacía. La ruta MUST NOT aceptar parámetros que elijan el cliente.

#### Scenario: Aislamiento entre clientes
- **WHEN** dos clientes con vehículos piden cada uno `GET /mis-vehiculos`
- **THEN** cada uno recibe sólo sus vehículos y ninguno ve los del otro

#### Scenario: Vehículo dado de baja
- **WHEN** un cliente tiene dos vehículos y uno se da de baja
- **THEN** `GET /mis-vehiculos` devuelve sólo el vigente

#### Scenario: Personal sin ficha
- **WHEN** un ADMIN sin ficha de cliente pide `GET /mis-vehiculos`
- **THEN** la respuesta es 200 con la lista vacía

#### Scenario: Ficha cargada por el personal
- **WHEN** existe un cliente sin usuario con vehículos y un usuario CLIENTE distinto pide `GET /mis-vehiculos`
- **THEN** la lista del usuario no incluye esos vehículos
