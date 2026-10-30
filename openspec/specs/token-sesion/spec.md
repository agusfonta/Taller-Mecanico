# token-sesion Specification

## Purpose

Define el token de sesión (qué contiene, cómo se firma y valida) y su transporte exclusivo en una cookie HttpOnly, de modo que el navegador lo guarde sin que el código del cliente pueda leerlo y sin que viaje nunca en el cuerpo ni en la cabecera `Authorization`.

## Requirements

### Requirement: Contenido y firma del token
El token de sesión MUST ser un JWT firmado con la clave de la configuración (`JWT_SECRET_KEY`) y un algoritmo simétrico fijo. MUST contener: `sub` (id del usuario), `iat` (instante de emisión con **fracción de segundo, sin truncar**), `exp` (`iat` + `JWT_EXPIRE_MINUTES`) y los roles vigentes del usuario al momento de emitirlo. Los roles del token MUST ser sólo informativos: ninguna decisión de permiso MUST tomarse con ellos. Al validar, el sistema MUST rechazar un token con firma inválida, con otro algoritmo (incluido `none`), vencido, o al que le falte `sub`, `iat` o `exp`.

#### Scenario: Token emitido con iat fraccional
- **WHEN** un usuario inicia sesión correctamente
- **THEN** el token de la cookie trae `sub` igual a su id, `iat` con parte fraccional, `exp` = `iat` + 1800 s (con `JWT_EXPIRE_MINUTES=30`) y la lista de sus roles vigentes

#### Scenario: Token con firma inválida
- **WHEN** se llama a una ruta autenticada con un token firmado con otra clave
- **THEN** la respuesta es 401

#### Scenario: Token sin firma
- **WHEN** se llama a una ruta autenticada con un token de algoritmo `none`
- **THEN** la respuesta es 401

#### Scenario: Token vencido
- **WHEN** se llama a una ruta autenticada con un token cuyo `exp` ya pasó
- **THEN** la respuesta es 401

### Requirement: Transporte sólo en cookie HttpOnly
El token MUST viajar únicamente en la cookie `access_token`, emitida con `HttpOnly`, `SameSite=Lax`, `Path=/`, `Max-Age` igual a la duración del token en segundos, y `Secure` si y sólo si `COOKIE_SECURE` es verdadero. El token MUST NOT aparecer en ningún cuerpo de respuesta. El sistema MUST leer el token sólo de la cookie y MUST ignorar la cabecera `Authorization`.

#### Scenario: Atributos de la cookie
- **WHEN** un login correcto responde con `COOKIE_SECURE=false`
- **THEN** la cabecera `Set-Cookie` define `access_token` con `HttpOnly`, `SameSite=Lax`, `Path=/` y `Max-Age=1800`, sin `Secure`, y el cuerpo no contiene el token

#### Scenario: Cookie segura configurable
- **WHEN** un login correcto responde con `COOKIE_SECURE=true`
- **THEN** la cookie `access_token` incluye además el atributo `Secure`

#### Scenario: Token en la cabecera Authorization
- **WHEN** se llama a `GET /auth/yo` sin cookie y con `Authorization: Bearer <token válido>`
- **THEN** la respuesta es 401
