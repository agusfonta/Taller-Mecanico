# Spec Delta — `contrasenas`

## Purpose

Garantiza que las contraseñas se guarden y verifiquen con bcrypt sin frenar el servidor, con un costo configurable, una política de longitud que nunca termina en un 500, y un hash ficticio listo desde el arranque para que el login no revele qué cuentas existen.

## ADDED Requirements

### Requirement: Política de contraseña
Toda contraseña **nueva** (registro y contraseña nueva del cambio) MUST tener al menos 8 caracteres. Todo campo de entrada que termina en bcrypt (contraseña de registro, de login, actual y nueva del cambio) MUST aceptar como máximo **72 bytes** en UTF-8 (bytes, no caracteres) y MUST rechazar el carácter nulo. Una entrada que no cumpla MUST responder 422 con un mensaje propio, sin llegar a calcular ningún hash y sin terminar en 500. Las contraseñas de login y la actual del cambio MUST NOT exigir el mínimo de 8 caracteres (sólo no vacías).

#### Scenario: Contraseña nueva demasiado corta
- **WHEN** se registra un usuario con una contraseña de 7 caracteres
- **THEN** la respuesta es 422 y no se creó ninguna fila

#### Scenario: Límite de 72 bytes con caracteres multibyte
- **WHEN** se envía una contraseña de 37 caracteres "ñ" (74 bytes) en registro, login o cambio de contraseña
- **THEN** la respuesta es 422 y no 500

#### Scenario: Exactamente 72 bytes
- **WHEN** se registra un usuario con una contraseña de 36 caracteres "ñ" (72 bytes)
- **THEN** el registro se acepta y luego el login con esa misma contraseña responde 200

#### Scenario: Carácter nulo
- **WHEN** se envía una contraseña que contiene el carácter nulo
- **THEN** la respuesta es 422

### Requirement: Hash fuera del bucle de eventos y bajo un tope de concurrencia
Todo cálculo o verificación de bcrypt MUST ejecutarse fuera del bucle de eventos y MUST pasar por un tope de concurrencia configurable (`BCRYPT_MAX_CONCURRENCY`): nunca corren a la vez más cálculos que ese tope. El costo MUST tomarse de la configuración (`BCRYPT_ROUNDS`), nunca fijo en el código. Mientras se calcula un hash, el servidor MUST seguir atendiendo otras peticiones. Ningún hash MUST calcularse con una transacción de base de datos abierta en la petición.

#### Scenario: El servidor sigue respondiendo durante un hash
- **WHEN** hay un registro o login en curso calculando bcrypt
- **THEN** una petición a `GET /health/live` concurrente responde sin esperar a que termine el hash

#### Scenario: Tope de concurrencia respetado
- **WHEN** se lanzan concurrentemente más verificaciones que el tope configurado
- **THEN** en ningún momento corren a la vez más verificaciones que el tope, y todas terminan

#### Scenario: Costo configurable
- **WHEN** la configuración fija `BCRYPT_ROUNDS=4`
- **THEN** los hashes generados declaran costo 4

### Requirement: Hash ficticio calculado en el arranque
Durante el arranque de la aplicación (lifespan), y una sola vez por proceso, el sistema MUST calcular un hash bcrypt ficticio con el costo configurado, a partir de un valor aleatorio que no viaja en ninguna respuesta ni queda en el código. El login de un correo inexistente MUST verificar contra ese hash. Ningún login MUST calcular el hash ficticio en el momento de la petición.

#### Scenario: Hash ficticio disponible tras el arranque
- **WHEN** la aplicación terminó de arrancar
- **THEN** existe un hash ficticio con el costo configurado, y dos arranques distintos producen hashes distintos

#### Scenario: Login con correo inexistente usa el hash ficticio
- **WHEN** se inicia sesión con un correo que no existe
- **THEN** se realiza exactamente una verificación bcrypt, contra el hash ficticio, y ninguna generación de hash nuevo

### Requirement: Contraseñas nunca expuestas
Ninguna respuesta de la API MUST incluir la contraseña ni `password_hash`. Ningún registro de log MUST contener contraseñas, hashes ni tokens.

#### Scenario: Respuestas sin hash
- **WHEN** se registra un usuario y luego se consulta `GET /auth/yo`
- **THEN** ninguno de los cuerpos contiene `password_hash`, la contraseña enviada ni un hash bcrypt
