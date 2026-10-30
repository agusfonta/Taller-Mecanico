# roles-usuario Specification

## Purpose

Permite que un administrador consulte, asigne (con vencimiento opcional) y revoque los roles de un usuario conservando el historial completo, con una única asignación abierta por rol y sin que el sistema pueda quedarse sin administradores vigentes (US-021, RN-03, RN-04, RN-05).

## Requirements

### Requirement: Gestión de roles sólo para administradores
`GET /usuarios/{id}/roles`, `POST /usuarios/{id}/roles` y `DELETE /usuarios/{id}/roles/{rol}` SHALL pertenecer al grupo protegido y MUST ejecutarse sólo si el usuario actual tiene ADMIN vigente en la base en esa petición. Sin sesión válida MUST responder 401; sin ADMIN vigente o con cambio de contraseña pendiente MUST responder 403 sin leer ni modificar asignaciones. Un `id` no entero o un `rol` fuera del vocabulario (`ADMIN`, `RECEPCION`, `MECANICO`, `CLIENTE`) en la ruta MUST responder 422.

#### Scenario: Mecánico intenta asignar un rol
- **WHEN** un usuario con sólo MECANICO envía `POST /usuarios/{id}/roles`
- **THEN** la respuesta es 403 y la tabla `asignacion_rol` no cambió

#### Scenario: Parámetros de ruta inválidos
- **WHEN** un ADMIN llama a `GET /usuarios/abc/roles` o a `DELETE /usuarios/1/roles/JEFE`
- **THEN** la respuesta es 422

### Requirement: Consulta del historial de roles
`GET /usuarios/{id}/roles` MUST responder 200 con el id del usuario, sus roles vigentes en ese instante (ordenados por nombre) y la lista completa de sus asignaciones, incluidas las vencidas y las revocadas, cada una con su rol, `desde`, `vence_en`, `revocada_en`, `otorgada_por` y si está vigente. Si el usuario no existe MUST responder 404 con un mensaje propio.

#### Scenario: Historial con asignaciones de todo tipo
- **WHEN** un usuario tiene una asignación MECANICO vigente, una RECEPCION revocada y una ADMIN vencida, y un ADMIN consulta sus roles
- **THEN** la respuesta es 200, los roles vigentes son `["MECANICO"]` y la lista contiene las tres asignaciones con su estado

#### Scenario: Usuario inexistente
- **WHEN** un ADMIN consulta los roles de un id que no existe
- **THEN** la respuesta es 404 con un mensaje propio

### Requirement: Asignación de rol con vencimiento opcional
`POST /usuarios/{id}/roles` MUST recibir exactamente `rol` (obligatorio, del vocabulario de roles) y `vence_en` (opcional). Un campo extra MUST responder 422. Si `vence_en` viene, MUST incluir zona horaria y MUST ser posterior al instante de la petición; si no tiene zona o no está en el futuro MUST responder 422 (no 409). Si el usuario no existe MUST responder 404. Una asignación válida MUST crear una `asignacion_rol` abierta con el rol, el vencimiento pedido y `otorgada_por` igual al id del administrador, y una línea en `evento_seguridad`, en la misma transacción; MUST responder 201 con la asignación creada.

#### Scenario: Asignar un rol sin vencimiento
- **WHEN** un ADMIN asigna RECEPCION a un usuario que no la tiene
- **THEN** la respuesta es 201 con la asignación abierta, sin `vence_en`, con `otorgada_por` = id del ADMIN, y queda una línea nueva en `evento_seguridad`

#### Scenario: Vencimiento futuro con zona
- **WHEN** un ADMIN asigna MECANICO con `vence_en` dentro de un día con zona `-03:00`
- **THEN** la respuesta es 201 y el usuario tiene MECANICO vigente hasta ese instante

#### Scenario: Vencimiento sin zona horaria
- **WHEN** un ADMIN asigna un rol con `vence_en` `2030-01-01T10:00:00` (sin zona)
- **THEN** la respuesta es 422 y no se creó ninguna asignación

#### Scenario: Vencimiento en el pasado
- **WHEN** un ADMIN asigna un rol con `vence_en` anterior al instante actual, con zona
- **THEN** la respuesta es 422 y no se creó ninguna asignación

#### Scenario: Usuario inexistente
- **WHEN** un ADMIN asigna un rol con un cuerpo válido a un id que no existe
- **THEN** la respuesta es 404 y no se creó ninguna fila

### Requirement: Una sola asignación abierta por rol
Un usuario MUST tener a lo sumo una asignación abierta (no revocada) por rol, garantizado por la base. Asignar un rol que el usuario ya tiene abierto y vigente MUST responder 409 con un mensaje propio, sin filas nuevas, aunque dos asignaciones iguales lleguen a la vez. Si la asignación abierta de ese rol está vencida, la asignación MUST cerrarla (escribiendo `revocada_en`) y abrir una nueva en la misma transacción, conservando la fila anterior.

#### Scenario: Rol ya vigente
- **WHEN** un ADMIN asigna MECANICO a un usuario que ya tiene MECANICO abierto y vigente
- **THEN** la respuesta es 409 con un mensaje propio y la cantidad de filas de `asignacion_rol` no cambió

#### Scenario: Reasignar un rol vencido
- **WHEN** un usuario tiene MECANICO abierto con `vence_en` en el pasado y un ADMIN le asigna MECANICO otra vez
- **THEN** la respuesta es 201, la fila anterior conserva sus datos y ahora tiene `revocada_en`, y existe una única asignación MECANICO abierta (la nueva)

#### Scenario: Asignaciones simultáneas del mismo rol
- **WHEN** dos peticiones asignan a la vez el mismo rol al mismo usuario que no lo tenía
- **THEN** una responde 201 y la otra 409, y queda una sola asignación abierta de ese rol

#### Scenario: Conflicto sin detalles de la base
- **WHEN** una asignación responde 409
- **THEN** el cuerpo no contiene `IntegrityError`, `duplicate key`, `uq_` ni nombres de tablas

### Requirement: Revocación sin borrado y efecto inmediato
`DELETE /usuarios/{id}/roles/{rol}` MUST escribir `revocada_en` en la asignación abierta de ese rol (esté o no vencida) y MUST NOT borrar la fila; MUST registrar una línea en `evento_seguridad` en la misma transacción y responder 200 con la asignación revocada. Si el usuario no existe, o no tiene una asignación abierta de ese rol (incluido repetir la revocación), MUST responder 404 con un mensaje propio. A partir de la petición siguiente, el usuario afectado MUST perder los permisos de ese rol aunque use la misma cookie, y `GET /auth/yo` MUST mostrar el rol ausente de los roles vigentes y todavía presente en los roles del token.

#### Scenario: Revocación con la sesión abierta
- **WHEN** un usuario con RECEPCION inicia sesión, llama con éxito a una ruta que exige RECEPCION, un ADMIN le revoca RECEPCION y el usuario repite la llamada con la misma cookie
- **THEN** la revocación responde 200, la segunda llamada del usuario responde 403, `GET /auth/yo` muestra RECEPCION sólo en los roles del token, y la fila revocada sigue en `asignacion_rol` con `revocada_en`

#### Scenario: Revocar dos veces
- **WHEN** un ADMIN revoca MECANICO a un usuario y repite la misma revocación
- **THEN** la primera responde 200 y la segunda 404, y existe una sola fila MECANICO con `revocada_en`

#### Scenario: Rol nunca asignado
- **WHEN** un ADMIN revoca CLIENTE a un usuario que nunca lo tuvo
- **THEN** la respuesta es 404 y no se escribió ningún evento

### Requirement: Autoprotección de administradores
Un administrador MUST NOT poder revocarse su propio rol ADMIN: esa petición MUST responder 409 con un mensaje propio, sin cambios. Ninguna revocación de ADMIN MUST dejar el sistema sin al menos un usuario activo con ADMIN vigente: si la dejaría, MUST responder 409 con un mensaje propio, sin cambios, también cuando dos revocaciones de ADMIN se procesan a la vez. Un administrador MAY revocarse sus otros roles y MAY revocar el ADMIN de otro administrador mientras quede al menos uno.

#### Scenario: El admin se revoca su ADMIN
- **WHEN** un ADMIN envía `DELETE /usuarios/{su propio id}/roles/ADMIN`
- **THEN** la respuesta es 409 con un mensaje propio, su asignación ADMIN sigue abierta y puede seguir usando rutas de ADMIN

#### Scenario: Revocar a otro admin habiendo dos
- **WHEN** existen dos ADMIN vigentes y uno revoca el ADMIN del otro
- **THEN** la respuesta es 200 y el revocado recibe 403 en su siguiente llamada a una ruta de ADMIN

#### Scenario: Revocaciones cruzadas simultáneas
- **WHEN** existen exactamente dos ADMIN vigentes y cada uno revoca a la vez el ADMIN del otro
- **THEN** una revocación responde 200 y la otra 409, y queda exactamente un ADMIN vigente

#### Scenario: El admin se revoca otro rol propio
- **WHEN** un ADMIN que además tiene MECANICO revoca su propio MECANICO
- **THEN** la respuesta es 200
