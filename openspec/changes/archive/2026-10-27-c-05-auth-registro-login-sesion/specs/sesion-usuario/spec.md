# Spec Delta — `sesion-usuario`

## Purpose

Define cómo se identifica al usuario de cada petición a partir de su cookie, qué hace inválida una sesión (incluido un cambio de contraseña posterior a su emisión), qué devuelve `GET /auth/yo` y cómo se cambia la contraseña invalidando las sesiones anteriores (RN-06, RN-07, DD-19).

## ADDED Requirements

### Requirement: Usuario actual desde la cookie
Toda ruta que requiera autenticación MUST resolver el usuario a partir del token de la cookie `access_token` y MUST responder 401 con un mensaje propio, sin ejecutar la ruta, si: falta la cookie; el token es inválido o está vencido; el usuario de `sub` no existe o está inactivo; o el `iat` del token es anterior a `password_cambiada_en` del usuario, comparados con precisión de microsegundos (sin truncar a segundos). El mensaje del 401 MUST ser el mismo en todos esos casos y MUST NOT contener detalles del token ni trazas. Resolver el usuario MUST NOT dejar una transacción de base de datos abierta durante el resto de la petición.

#### Scenario: Sin cookie
- **WHEN** se llama a `GET /auth/yo` sin cookie
- **THEN** la respuesta es 401 con el mensaje "Se requiere iniciar sesión"

#### Scenario: Usuario desactivado con sesión abierta
- **WHEN** un usuario con sesión válida es marcado inactivo y vuelve a llamar a `GET /auth/yo` con la misma cookie
- **THEN** la respuesta es 401

#### Scenario: Usuario inexistente
- **WHEN** se llama con un token bien firmado cuyo `sub` no corresponde a ningún usuario
- **THEN** la respuesta es 401

### Requirement: Consulta de la sesión propia
`GET /auth/yo` SHALL estar en el grupo abierto, MUST exigir un usuario actual válido (401 si no) y MUST responder 200 aun con el cambio de contraseña pendiente. El cuerpo MUST incluir id, correo, nombre, `debe_cambiar_password`, los **roles vigentes consultados en la base en esa petición** (asignaciones no revocadas y sin vencer) y los roles que dice el token, sin contraseña ni hash.

#### Scenario: Roles vigentes vs. roles del token
- **WHEN** después de iniciar sesión se revoca en la base uno de los roles del usuario y se llama a `GET /auth/yo` con la misma cookie
- **THEN** los roles vigentes ya no incluyen el rol revocado y los roles del token sí

#### Scenario: Rol vencido
- **WHEN** una asignación del usuario tiene `vence_en` en el pasado
- **THEN** ese rol no figura entre los roles vigentes

#### Scenario: Yo con cambio pendiente
- **WHEN** un usuario con `debe_cambiar_password` verdadero llama a `GET /auth/yo`
- **THEN** la respuesta es 200 con `debe_cambiar_password` true

### Requirement: Cambio de contraseña
`POST /auth/cambiar-password` SHALL estar en el grupo abierto, MUST exigir un usuario actual válido (401 si no) y MUST funcionar aun con el cambio pendiente. Recibe exactamente `password_actual` y `password_nueva` (`extra` → 422; política de contraseña → 422). Si `password_actual` no coincide, MUST responder 401 con un mensaje propio sin modificar nada. Si coincide, en una única transacción MUST guardar el hash nuevo (calculado antes de abrirla), anotar `password_cambiada_en` con el instante del cambio, poner `debe_cambiar_password` en falso y agregar una línea de `evento_seguridad` (actor = correo del usuario); **después** de confirmar MUST emitir un token nuevo y responder 200 con un mensaje propio y la cookie nueva.

#### Scenario: Cambio exitoso
- **WHEN** un usuario cambia su contraseña con la actual correcta
- **THEN** la respuesta es 200 con `Set-Cookie` nuevo, el login con la contraseña vieja responde 401, el login con la nueva responde 200 y hay una línea nueva en `evento_seguridad`

#### Scenario: Contraseña actual incorrecta
- **WHEN** se pide el cambio con una `password_actual` incorrecta
- **THEN** la respuesta es 401, el hash y `password_cambiada_en` no cambiaron y no hay evento nuevo

### Requirement: Invalidación de sesiones anteriores al cambio
Tras un cambio de contraseña, todo token emitido **antes** del cambio MUST responder 401, aunque se haya emitido en el mismo segundo que el cambio; el token devuelto por el propio cambio MUST ser válido.

#### Scenario: Sesión vieja del mismo segundo
- **WHEN** un usuario inicia sesión y, sin esperar, cambia su contraseña
- **THEN** la cookie anterior responde 401 en `GET /auth/yo` y la cookie nueva responde 200

#### Scenario: Otra sesión abierta del mismo usuario
- **WHEN** un usuario tiene dos sesiones abiertas y cambia la contraseña desde una
- **THEN** la otra sesión responde 401 y la cookie devuelta por el cambio responde 200
