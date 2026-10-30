# inicio-sesion Specification

## Purpose

Define cómo un usuario inicia y cierra sesión: el orden del login (límite de intentos antes que la verificación), la protección contra fuerza bruta y contra la enumeración de cuentas, el registro de cada intento que sobrevive al rechazo, y la emisión y el borrado de la cookie de sesión (RN-08, RN-09).

## Requirements

### Requirement: Contrato del login
`POST /auth/login` SHALL estar en el grupo abierto y recibir exactamente `email` y `password`; un campo extra, un correo con formato inválido o una contraseña vacía o de más de 72 bytes MUST responder 422 sin contar como intento. El correo MUST normalizarse igual que en el registro (sin espacios en los extremos, en minúsculas) antes de buscar el usuario, contar intentos y anotarlos.

#### Scenario: Correo con mayúsculas en el login
- **WHEN** un usuario registrado como `ana@example.com` inicia sesión con `ANA@example.com` y su contraseña
- **THEN** la respuesta es 200

#### Scenario: Campo extra en el login
- **WHEN** se envía `POST /auth/login` con un campo adicional
- **THEN** la respuesta es 422 y no se anotó ningún intento en `intento_acceso`

### Requirement: Login correcto
Si el correo corresponde a un usuario activo y la contraseña coincide, el login MUST responder 200 con el cuerpo `{"mensaje": "Sesión iniciada", "debe_cambiar_password": <bool del usuario>, "expira_en_segundos": <duración del token en segundos>}`, MUST establecer la cookie de sesión y MUST NOT incluir el token en el cuerpo. Un usuario con el cambio de contraseña pendiente MUST poder iniciar sesión normalmente (el cuerpo lo informa con `debe_cambiar_password: true`).

#### Scenario: Login correcto
- **WHEN** un usuario activo inicia sesión con su contraseña
- **THEN** la respuesta es 200 con `mensaje` "Sesión iniciada", `debe_cambiar_password` false y `expira_en_segundos` 1800, y con `Set-Cookie` de `access_token`

#### Scenario: Login con cambio pendiente
- **WHEN** un usuario con `debe_cambiar_password` verdadero inicia sesión con su contraseña
- **THEN** la respuesta es 200 con `debe_cambiar_password` true y la cookie de sesión

### Requirement: Respuesta uniforme ante credenciales inválidas
Si el correo no existe, la contraseña no coincide o el usuario está inactivo, el login MUST responder 401 con **el mismo cuerpo** (mismo mensaje propio) y las mismas cabeceras relevantes en los tres casos, sin cookie. En los tres casos MUST realizarse exactamente una verificación bcrypt (contra el hash ficticio si el correo no existe), de modo que el tiempo de respuesta sea parecido exista o no el correo.

#### Scenario: Correo existente con clave mala vs. correo inexistente
- **WHEN** se intenta el login con un correo existente y clave incorrecta, y luego con un correo inexistente
- **THEN** ambas respuestas son 401 con cuerpos idénticos y sin `Set-Cookie`

#### Scenario: Tiempo parecido
- **WHEN** se miden varios logins fallidos con correo existente y varios con correo inexistente, con el mismo costo de bcrypt
- **THEN** las medianas de ambos tiempos difieren en menos de la mitad del tiempo de una verificación bcrypt

#### Scenario: Usuario inactivo
- **WHEN** un usuario inactivo inicia sesión con su contraseña correcta
- **THEN** la respuesta es 401 con el mismo cuerpo que una clave incorrecta y sin cookie

### Requirement: Límite de intentos fallidos
Antes de verificar la contraseña, el login MUST contar los intentos fallidos con el mismo correo (normalizado) desde la misma dirección IP en los últimos **60 segundos**, considerando sólo los posteriores al último login correcto de ese mismo correo desde esa misma dirección. Si son **5 o más**, MUST responder 429 con un mensaje propio y la cabecera `Retry-After` (segundos enteros ≥ 1 hasta que el intento fallido que bloquea salga de la ventana), **sin calcular ni verificar ningún hash** y sin cookie. Los intentos fallidos anteriores a un login correcto MUST seguir en la tabla pero dejar de contar. Otro correo, u otra dirección, MUST NOT verse afectado.

#### Scenario: Sexto intento bloqueado
- **WHEN** se hacen seis intentos fallidos seguidos con el mismo correo desde la misma IP
- **THEN** los cinco primeros responden 401, el sexto responde 429 con `Retry-After` entre 1 y 60, sin verificación bcrypt, y `intento_acceso` contiene los cinco fallos

#### Scenario: Ventana vencida
- **WHEN** los cinco fallos tienen más de 60 segundos de antigüedad
- **THEN** un nuevo intento se verifica normalmente (401 o 200 según la contraseña)

#### Scenario: Login correcto reinicia la cuenta
- **WHEN** hay cuatro fallos recientes, luego un login correcto y luego cuatro fallos más (mismo correo e IP)
- **THEN** ninguno de esos intentos responde 429 y los ocho fallos siguen en `intento_acceso`

#### Scenario: Otro correo u otra IP no se bloquean
- **WHEN** un correo está bloqueado desde una IP
- **THEN** el mismo correo desde otra IP, y otro correo desde la misma IP, se verifican normalmente

### Requirement: Anotación de cada intento en transacción propia
Cada intento de login que llega a verificarse (correcto o fallido) MUST anotarse en `intento_acceso` con su instante, el correo normalizado, la IP y si tuvo éxito, usando una sesión y una transacción **propias**, independientes de la transacción de la petición, que se confirman siempre: la fila MUST quedar aunque la petición termine en 401 o en error. Los intentos rechazados por el límite (429) y los rechazados por contrato (422) MUST NOT anotarse.

#### Scenario: Fallo anotado aunque la respuesta sea 401
- **WHEN** un login responde 401
- **THEN** existe en `intento_acceso` una fila confirmada con ese correo, esa IP y `exito` falso

#### Scenario: Éxito anotado
- **WHEN** un login responde 200
- **THEN** existe en `intento_acceso` una fila confirmada con `exito` verdadero

### Requirement: Cierre de sesión idempotente
`POST /auth/logout` SHALL estar en el grupo abierto, MUST NOT exigir sesión y MUST responder siempre 200 con un mensaje propio, indicando al navegador que borre la cookie `access_token` (mismo nombre, `Path=/`, `Max-Age=0`). Llamarlo sin cookie, con una cookie inválida o varias veces seguidas MUST dar el mismo resultado.

#### Scenario: Logout con sesión
- **WHEN** un usuario con sesión llama a `POST /auth/logout`
- **THEN** la respuesta es 200 con `Set-Cookie` que borra `access_token`, y un `GET /auth/yo` posterior sin cookie responde 401

#### Scenario: Logout sin sesión
- **WHEN** se llama a `POST /auth/logout` sin cookie, dos veces
- **THEN** ambas respuestas son 200 con el mismo cuerpo
