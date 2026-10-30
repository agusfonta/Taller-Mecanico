# registro-clientes Specification

## Purpose

Permite que un visitante se registre como cliente del taller creando, de forma atómica, su usuario, su rol CLIENTE y su ficha de cliente, sin poder elegir rol ni apropiarse de la ficha de otro cliente (RN-01, RN-02).

## Requirements

### Requirement: Contrato del registro
`POST /auth/registro` SHALL estar en el grupo abierto y recibir exactamente `email`, `password`, `nombre`, `documento` y `telefono`. Cualquier campo extra (por ejemplo `rol` o `activo`) MUST responder 422. `email` MUST ser un correo válido; `nombre`, `documento` y `telefono` MUST ser textos no vacíos tras quitar espacios en los extremos. El correo MUST normalizarse (espacios en los extremos quitados y minúsculas) antes de guardarse, de modo que dos correos que sólo difieren en mayúsculas sean el mismo.

#### Scenario: Registro con un rol en el cuerpo
- **WHEN** se envía `POST /auth/registro` con un campo `rol: "ADMIN"`
- **THEN** la respuesta es 422 y no se creó ninguna fila

#### Scenario: Correo con mayúsculas
- **WHEN** se registra `Ana@Example.COM`
- **THEN** el usuario queda guardado con `ana@example.com` y un segundo registro con `ana@example.com` responde 409

#### Scenario: Campos vacíos
- **WHEN** se registra con `documento` compuesto sólo de espacios
- **THEN** la respuesta es 422

### Requirement: Alta atómica de usuario, rol y ficha
Un registro válido MUST crear, en una única transacción, el `usuario` (activo, sin cambio de contraseña pendiente, con la contraseña hasheada), una `asignacion_rol` abierta y sin vencimiento con rol `CLIENTE`, la ficha `cliente` vinculada a ese usuario, y una línea en `evento_seguridad` cuyo actor es el correo del usuario y cuya acción describe el alta. O quedan todas esas filas, o ninguna. El hash MUST calcularse antes de abrir la transacción. La respuesta MUST ser 201 con el id del usuario, su correo, su nombre, el id de su ficha de cliente y sus roles, sin contraseña ni hash, y MUST NOT iniciar sesión (sin cookie).

#### Scenario: Registro exitoso
- **WHEN** un visitante se registra con datos válidos y correo y documento nuevos
- **THEN** la respuesta es 201 sin `Set-Cookie`, y en la base existen el usuario, su asignación CLIENTE abierta, su ficha de cliente vinculada y una línea nueva de `evento_seguridad`

#### Scenario: Login tras el registro
- **WHEN** el usuario recién registrado inicia sesión con su contraseña
- **THEN** la respuesta es 200 y `GET /auth/yo` muestra el rol vigente `CLIENTE`

### Requirement: Unicidad en el registro sin filas sueltas
Si el correo ya pertenece a un usuario, o el documento ya pertenece a cualquier cliente del taller (tenga o no usuario), el registro MUST responder 409 con un mensaje propio que indique cuál de los dos datos choca, MUST NOT dejar ninguna fila nueva en `usuario`, `asignacion_rol`, `cliente` ni `evento_seguridad`, y MUST NOT vincular ni modificar la ficha existente. La unicidad MUST garantizarla la base (no una consulta previa) y la respuesta MUST NOT contener texto de la base, nombres de restricciones ni trazas.

#### Scenario: Correo repetido
- **WHEN** se registra un correo que ya existe con un documento nuevo
- **THEN** la respuesta es 409 con un mensaje propio sobre el correo, y las cantidades de filas de las cuatro tablas no cambiaron

#### Scenario: Documento de un cliente sin usuario
- **WHEN** se registra un correo nuevo con el documento de un cliente cargado por la recepción (sin usuario)
- **THEN** la respuesta es 409 con un mensaje propio sobre el documento, la ficha existente sigue sin usuario y no quedó ningún usuario nuevo

#### Scenario: Respuesta sin detalles de la base
- **WHEN** un registro responde 409
- **THEN** el cuerpo no contiene `IntegrityError`, `duplicate key`, `uq_` ni nombres de tablas
