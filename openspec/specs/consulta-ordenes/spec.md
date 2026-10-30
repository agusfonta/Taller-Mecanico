
# consulta-ordenes Specification

## Purpose

Permite consultar órdenes de trabajo: el personal lista y filtra por estado según su rol, el personal o el dueño del vehículo ven el detalle con ítems, subtotales e historial con un número fijo de consultas, y cada usuario ve sólo las órdenes de sus propios vehículos (RN-17, RN-19, DD-18, casos C-06, C-15, C-17).


## Requirements

### Requirement: Acceso a las rutas de consulta de órdenes
`GET /ordenes`, `GET /ordenes/{id}` y `GET /mis-ordenes` SHALL pertenecer al grupo protegido: sin sesión MUST responder 401 y con el cambio de contraseña pendiente 403. `GET /ordenes` MUST ejecutarse sólo para usuarios con un rol vigente en la base ADMIN, RECEPCION o MECANICO (otro usuario → 403, evaluado antes que la validación de parámetros). `GET /ordenes/{id}` y `GET /mis-ordenes` MUST ejecutarse para cualquier usuario autenticado; el permiso sobre una orden concreta lo decide la regla de dueño.

#### Scenario: Cliente listando todas las órdenes
- **WHEN** un usuario con sólo el rol CLIENTE llama `GET /ordenes`
- **THEN** la respuesta es 403

#### Scenario: Listado sin sesión
- **WHEN** se llama `GET /ordenes` o `GET /mis-ordenes` sin cookie
- **THEN** la respuesta es 401

### Requirement: Listado de órdenes por rol
`GET /ordenes` MUST devolver el envoltorio de paginación (`items`, `total`, `page`, `size`, `pages`) con un resumen por orden (`id`, `vehiculo_id`, `mecanico_id`, `estado`, `falla`, `creada_en`, `total`) ordenado por `id` ascendente. Un usuario con ADMIN o RECEPCION vigente MUST ver todas las órdenes. Un usuario cuyo único rol de personal vigente es MECANICO MUST ver sólo las órdenes con `mecanico_id` igual a su id más las que no tienen mecánico asignado. `total` MUST contarse con los mismos filtros que `items`.

#### Scenario: Recepción ve todas
- **WHEN** existen una orden sin mecánico, una asignada a `mecanico` y otra asignada a `mecanico2`, y recepción llama `GET /ordenes`
- **THEN** la respuesta trae las tres órdenes y `total` 3

#### Scenario: Mecánico ve las suyas y las sin asignar
- **WHEN** con esas tres órdenes `mecanico2` llama `GET /ordenes`
- **THEN** la respuesta trae la orden sin mecánico y la asignada a `mecanico2`, no la de `mecanico`, y `total` 2

#### Scenario: Mecánico que además es administrador
- **WHEN** un usuario con MECANICO y ADMIN vigentes llama `GET /ordenes`
- **THEN** ve todas las órdenes

### Requirement: Filtro por estado declarado en el contrato
`GET /ordenes` MUST aceptar un parámetro opcional `estado` cuyo valor MUST ser uno de los estados declarados en el contrato de la API (PENDIENTE, EN_REPARACION, TERMINADA, CANCELADA); cualquier otro valor MUST responder 422 sin consultar órdenes. Con `estado` presente, `items` y `total` MUST incluir sólo las órdenes en ese estado, combinado con el filtro por rol. Los parámetros `page` y `size` MUST seguir las reglas comunes de paginación (página más allá de la última → 422).

#### Scenario: Estado no declarado
- **WHEN** el personal llama `GET /ordenes?estado=ARCHIVADA`
- **THEN** la respuesta es 422

#### Scenario: Filtrar por PENDIENTE
- **WHEN** hay una orden PENDIENTE y otra EN_REPARACION y recepción llama `GET /ordenes?estado=PENDIENTE`
- **THEN** la respuesta trae sólo la PENDIENTE y `total` 1

#### Scenario: Página fuera de rango con filtro
- **WHEN** hay una sola orden PENDIENTE y se pide `GET /ordenes?estado=PENDIENTE&size=1&page=2`
- **THEN** la respuesta es 422

### Requirement: Detalle de una orden
`GET /ordenes/{id}` MUST responder 200 con `id`, `vehiculo_id`, `mecanico_id`, `estado`, `falla`, `creada_en`, `total`, la lista de `items` (cada uno con `id`, `repuesto_id`, código y descripción del repuesto, `cantidad`, `precio_unitario` y `subtotal = cantidad × precio_unitario`) ordenada por `repuesto_id`, y el `historial` de estados (cada línea con `desde_estado`, `hasta_estado`, `usuario_id` y `cuando`) ordenado por `id`. Los importes MUST emitirse como cadenas con 2 decimales. Si la orden no existe MUST responder 404 con un mensaje propio. Una orden cuyo vehículo o repuestos fueron dados de baja después del alta MUST seguir consultándose.

#### Scenario: Detalle con subtotales
- **WHEN** el personal pide el detalle de una orden con 2 ítems
- **THEN** la respuesta trae los 2 ítems con su subtotal, el total y el historial

#### Scenario: Orden inexistente
- **WHEN** el personal pide `GET /ordenes/999999`
- **THEN** la respuesta es 404

#### Scenario: Id no entero
- **WHEN** se pide `GET /ordenes/abc` con sesión
- **THEN** la respuesta es 422

### Requirement: Detalle visible para el personal o el dueño
`GET /ordenes/{id}` MUST responder 200 a un usuario con algún rol vigente ADMIN, RECEPCION o MECANICO, y al usuario vinculado a la ficha del cliente dueño del vehículo de la orden. A cualquier otro usuario MUST responder 403 sin revelar datos de la orden.

#### Scenario: El cliente ve su orden
- **WHEN** el cliente vinculado a la ficha dueña del vehículo pide el detalle de esa orden
- **THEN** la respuesta es 200

#### Scenario: El cliente pide una orden ajena
- **WHEN** un cliente pide el detalle de una orden de un vehículo de otra ficha
- **THEN** la respuesta es 403 y el cuerpo no contiene datos de la orden

### Requirement: Detalle con número fijo de consultas
El detalle de una orden MUST resolverse con una cantidad de sentencias SQL que no dependa de la cantidad de ítems ni de líneas de historial, precargando en el repositorio todas las relaciones que la respuesta lee (sin carga perezosa). Con `SQL_ECHO=true` las sentencias del detalle MUST ser visibles en la consola.

#### Scenario: Dos ítems contra cuatro ítems
- **WHEN** se pide el detalle de una orden con 2 ítems y el de otra con 4 ítems
- **THEN** ambas peticiones ejecutan la misma cantidad de sentencias SQL

### Requirement: Mis órdenes
`GET /mis-ordenes` MUST devolver, con el envoltorio de paginación y el mismo resumen y orden que `GET /ordenes`, sólo las órdenes de los vehículos de la ficha de cliente vinculada al usuario de la sesión, incluidas las de vehículos dados de baja. El dueño MUST salir de la sesión, nunca de un parámetro. Un usuario sin ficha de cliente MUST recibir una página vacía con `total` 0.

#### Scenario: Cliente con órdenes propias y ajenas en el sistema
- **WHEN** existen órdenes de vehículos de Laura y de Jorge y Laura llama `GET /mis-ordenes`
- **THEN** la respuesta trae sólo las órdenes de los vehículos de Laura

#### Scenario: Personal sin ficha
- **WHEN** un usuario de recepción sin ficha de cliente llama `GET /mis-ordenes`
- **THEN** la respuesta es 200 con `items` vacío, `total` 0 y `pages` 1
