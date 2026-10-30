# alta-personal Specification

## Purpose

Permite que un administrador dé de alta usuarios de personal (administración, recepción, mecánicos) con un rol inicial obligatorio y una contraseña provisoria que el usuario debe cambiar en su primer ingreso, de forma atómica y dejando constancia en el historial de seguridad (US-020, DD-14).

## Requirements

### Requirement: Alta de personal sólo para administradores
`POST /usuarios` SHALL pertenecer al grupo protegido y MUST ejecutarse sólo si el usuario actual tiene el rol ADMIN vigente en la base. Sin sesión válida MUST responder 401; con el cambio de contraseña pendiente o sin ADMIN vigente MUST responder 403 sin crear ninguna fila, aunque el cuerpo sea inválido.

#### Scenario: Usuario sin rol ADMIN
- **WHEN** un usuario autenticado con sólo RECEPCION envía `POST /usuarios` con un cuerpo válido
- **THEN** la respuesta es 403 y no se creó ninguna fila en `usuario`, `asignacion_rol` ni `evento_seguridad`

#### Scenario: Sin sesión
- **WHEN** se envía `POST /usuarios` sin cookie
- **THEN** la respuesta es 401

#### Scenario: Admin con cambio de contraseña pendiente
- **WHEN** un ADMIN con `debe_cambiar_password` verdadero envía `POST /usuarios`
- **THEN** la respuesta es 403 con el mensaje de cambio de contraseña pendiente

### Requirement: Contrato del alta de personal
El cuerpo de `POST /usuarios` MUST contener exactamente `email`, `nombre`, `password` y `rol`. Cualquier campo extra (por ejemplo `activo` o `debe_cambiar_password`) MUST responder 422. `email` MUST ser un correo válido y MUST normalizarse (sin espacios en los extremos y en minúsculas) igual que en el registro. `nombre` MUST ser un texto no vacío tras quitar espacios en los extremos. `password` MUST cumplir la política de contraseña nueva (mínimo 8 caracteres y máximo 72 bytes en UTF-8). `rol` MUST ser obligatorio y MUST ser un rol de personal: `ADMIN`, `RECEPCION` o `MECANICO`; cualquier otro valor, incluido `CLIENTE`, MUST responder 422. Ninguna entrada inválida MUST terminar en 500 ni calcular un hash.

#### Scenario: Sin rol inicial
- **WHEN** un ADMIN envía `POST /usuarios` sin el campo `rol`
- **THEN** la respuesta es 422 y no se creó ninguna fila

#### Scenario: Rol CLIENTE o inexistente
- **WHEN** un ADMIN envía `POST /usuarios` con `rol` igual a `CLIENTE` o a `JEFE`
- **THEN** la respuesta es 422 y no se creó ninguna fila

#### Scenario: Campo extra
- **WHEN** un ADMIN envía `POST /usuarios` con un campo `debe_cambiar_password: false`
- **THEN** la respuesta es 422

#### Scenario: Contraseña provisoria fuera de política
- **WHEN** un ADMIN envía una contraseña de 7 caracteres o de 74 bytes en UTF-8
- **THEN** la respuesta es 422 y no se calculó ningún hash

### Requirement: Alta atómica con cambio obligatorio de contraseña
Un alta válida MUST crear, en una única transacción, el `usuario` (activo, con `debe_cambiar_password` verdadero y la contraseña provisoria hasheada), una `asignacion_rol` abierta, sin vencimiento, con el rol pedido y con `otorgada_por` igual al id del administrador que hizo el alta, y una línea en `evento_seguridad`. O quedan todas esas filas, o ninguna. El hash MUST calcularse antes de abrir la transacción. La respuesta MUST ser 201 con el id, el correo, el nombre, `debe_cambiar_password` y los roles del usuario creado, MUST NOT contener la contraseña ni el hash y MUST NOT emitir cookie ni alterar la sesión del administrador.

#### Scenario: Alta de un mecánico
- **WHEN** un ADMIN envía `POST /usuarios` con `{email: "Nuevo@Taller.com", nombre: "Nuevo", password: "provisoria1", rol: "MECANICO"}`
- **THEN** la respuesta es 201 con `email` `nuevo@taller.com`, `debe_cambiar_password` verdadero y `roles` `["MECANICO"]`, sin `Set-Cookie`, y en la base existen el usuario activo, su asignación MECANICO abierta con `otorgada_por` = id del ADMIN y una línea nueva de `evento_seguridad`

#### Scenario: Primer ingreso del personal creado
- **WHEN** el usuario recién creado inicia sesión con la contraseña provisoria y llama a una ruta del grupo protegido
- **THEN** el login responde 200 con `debe_cambiar_password` verdadero y la ruta protegida responde 403 hasta que cambie la contraseña

#### Scenario: Fallo a mitad del alta
- **WHEN** la escritura de la asignación o del evento falla después de insertar el usuario
- **THEN** no queda ninguna fila nueva en `usuario`, `asignacion_rol` ni `evento_seguridad`

### Requirement: Correo repetido en el alta de personal
Si el correo (ya normalizado) pertenece a un usuario existente, el alta MUST responder 409 con un mensaje propio sobre el correo, MUST NOT dejar ninguna fila nueva y MUST NOT modificar al usuario existente. La unicidad MUST garantizarla la base y la respuesta MUST NOT contener texto de la base, nombres de restricciones ni trazas.

#### Scenario: Correo ya registrado con otra capitalización
- **WHEN** existe `ana@taller.com` y un ADMIN da de alta `ANA@taller.com`
- **THEN** la respuesta es 409 con el mensaje "El correo ya está registrado" y las cantidades de filas de `usuario`, `asignacion_rol` y `evento_seguridad` no cambiaron

#### Scenario: Respuesta sin detalles de la base
- **WHEN** el alta de personal responde 409
- **THEN** el cuerpo no contiene `IntegrityError`, `duplicate key`, `uq_` ni nombres de tablas
