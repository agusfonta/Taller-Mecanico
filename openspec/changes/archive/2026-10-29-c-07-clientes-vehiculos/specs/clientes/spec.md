# Spec Delta — `clientes`

## Purpose

Permite que el personal del taller (recepción y administración) cargue fichas de clientes y consulte un cliente junto con sus vehículos vigentes, con el documento único garantizado por la base y la lectura resuelta con un número fijo de consultas (RN-01, RN-16, Ej. 3 y Ej. 8).

## ADDED Requirements

### Requirement: Acceso a las rutas de clientes
`POST /clientes` y `GET /clientes/{id}` SHALL pertenecer al grupo protegido y MUST ejecutarse sólo para usuarios con un rol vigente en la base (no el del token) RECEPCION o ADMIN. Sin sesión válida MUST responder 401; con el cambio de contraseña pendiente MUST responder 403; con sesión válida pero sin ninguno de esos roles (por ejemplo, sólo CLIENTE o sólo MECANICO) MUST responder 403 aunque el cliente pedido no exista o sea la ficha del propio usuario. El control de rol MUST evaluarse antes que la existencia del recurso.

#### Scenario: Sin sesión
- **WHEN** se llama `POST /clientes` sin cookie de sesión
- **THEN** la respuesta es 401 y no se creó ninguna fila

#### Scenario: Cliente consultando su propia ficha
- **WHEN** un usuario con sólo el rol CLIENTE pide `GET /clientes/{id}` con el id de su propia ficha
- **THEN** la respuesta es 403

#### Scenario: Rol insuficiente sobre un id inexistente
- **WHEN** un usuario con sólo el rol MECANICO pide `GET /clientes/999999`
- **THEN** la respuesta es 403, no 404

#### Scenario: Rol revocado en la base
- **WHEN** un usuario cuyo token dice RECEPCION pero cuya asignación RECEPCION está revocada en la base llama `POST /clientes`
- **THEN** la respuesta es 403

#### Scenario: Recepción y administración
- **WHEN** un usuario RECEPCION y otro ADMIN llaman `POST /clientes` con datos válidos y documentos distintos
- **THEN** ambos reciben 201

### Requirement: Contrato del alta de cliente
`POST /clientes` MUST recibir exactamente `nombre`, `documento` y `telefono`, todos textos no vacíos tras quitar espacios en los extremos y con una longitud máxima acotada. Cualquier campo extra (por ejemplo `usuario_id` o `id`) MUST responder 422 sin escribir nada. Los valores MUST guardarse sin los espacios de los extremos. Ningún dato inválido MUST terminar en 500.

#### Scenario: Campo extra
- **WHEN** se envía `POST /clientes` con `usuario_id` además de los tres campos
- **THEN** la respuesta es 422 y la cantidad de filas de `cliente` no cambió

#### Scenario: Documento vacío
- **WHEN** se envía `documento` compuesto sólo de espacios
- **THEN** la respuesta es 422

#### Scenario: Espacios en los extremos
- **WHEN** se envía `documento` igual a `"  30111222 "`
- **THEN** la ficha queda guardada con documento `30111222`

### Requirement: Alta de cliente sin usuario
Un alta válida MUST crear una única fila de `cliente` sin usuario vinculado (`usuario_id` nulo) y MUST responder 201 con `id`, `nombre`, `documento`, `telefono` y `usuario_id` (nulo). El alta MUST NOT crear usuarios, asignaciones de rol ni vehículos.

#### Scenario: Alta exitosa
- **WHEN** recepción da de alta un cliente con un documento nuevo
- **THEN** la respuesta es 201 con el id de la ficha y `usuario_id` nulo, y existe exactamente una fila nueva en `cliente`

#### Scenario: La ficha cargada por el personal no se puede apropiar
- **WHEN** después de ese alta un visitante se auto-registra con el mismo documento
- **THEN** el registro responde 409 y la ficha sigue sin usuario vinculado

### Requirement: Documento único con 409 propio
Si el documento ya pertenece a cualquier cliente del taller (cargado por el personal o auto-registrado), el alta MUST responder 409 con un mensaje propio sobre el documento, MUST NOT dejar ninguna fila nueva y MUST NOT modificar la ficha existente. La unicidad MUST garantizarla la base, sin consulta previa, y la respuesta MUST NOT contener texto de la base, nombres de restricciones ni trazas.

#### Scenario: Documento de un cliente auto-registrado
- **WHEN** recepción da de alta un cliente con el documento de un cliente que se registró por la web
- **THEN** la respuesta es 409 con un mensaje propio sobre el documento y la cantidad de filas de `cliente` no cambió

#### Scenario: Documento repetido entre altas del personal
- **WHEN** se da de alta dos veces el mismo documento
- **THEN** la primera responde 201, la segunda 409, y el cuerpo del 409 no menciona tablas, columnas ni restricciones

### Requirement: Consulta de un cliente con sus vehículos
`GET /clientes/{id}` MUST responder 200 con los datos de la ficha (`id`, `nombre`, `documento`, `telefono`, `usuario_id`) y la lista `vehiculos` con **sólo** sus vehículos no dados de baja, cada uno con `id`, `patente`, `marca`, `modelo` y `anio`, ordenados por `id`. Un cliente sin vehículos vigentes MUST devolver la lista vacía. Si el cliente no existe MUST responder 404 con un mensaje propio. Un id que no es entero MUST responder 422 sin ejecutar la consulta. La consulta MUST resolverse con la misma cantidad de sentencias SQL sea cual sea la cantidad de vehículos (sin consultas por vehículo).

#### Scenario: Cliente con vehículos vigentes y dados de baja
- **WHEN** se consulta un cliente con dos vehículos vigentes y uno dado de baja
- **THEN** la respuesta es 200 con exactamente los dos vehículos vigentes, ordenados por id

#### Scenario: Cliente inexistente
- **WHEN** ADMIN pide `GET /clientes/999999`
- **THEN** la respuesta es 404 con un mensaje propio

#### Scenario: Id no entero
- **WHEN** ADMIN pide `GET /clientes/abc`
- **THEN** la respuesta es 422

#### Scenario: Sin N+1
- **WHEN** se consulta un cliente con un vehículo y luego otro cliente con cuatro vehículos
- **THEN** ambas consultas ejecutan la misma cantidad de sentencias SQL contra las tablas `cliente` y `vehiculo`
