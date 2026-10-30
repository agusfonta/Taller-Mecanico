# autorizacion Specification

## Purpose

Define cómo se decide qué puede hacer un usuario autenticado: los permisos por rol se evalúan con los roles vigentes de la base en cada petición (no con los del token), y un cambio de contraseña pendiente bloquea todo lo que no sea `/auth` ni salud (RN-04, RN-06, DD-01).

## Requirements

### Requirement: Permisos por rol consultados en la base
Una ruta que exige uno o más roles MUST permitir el acceso sólo si el usuario actual tiene **al menos uno** de ellos vigente en la base en esa misma petición (asignación no revocada y con `vence_en` nulo o futuro). Si no, MUST responder 403 con un mensaje propio sin ejecutar la ruta. Los roles del token MUST NOT otorgar ni quitar permisos. La falta de sesión válida MUST responder 401 antes de evaluar roles (401 ≠ 403).

#### Scenario: Rol suficiente
- **WHEN** un usuario con rol vigente ADMIN llama a una ruta protegida que exige ADMIN
- **THEN** la ruta se ejecuta

#### Scenario: Sin el rol requerido
- **WHEN** un usuario autenticado con sólo CLIENTE llama a una ruta que exige ADMIN o RECEPCION
- **THEN** la respuesta es 403 y la ruta no se ejecuta

#### Scenario: Revocación con la sesión abierta
- **WHEN** un usuario con ADMIN inicia sesión, se revoca su ADMIN en la base y repite la llamada con la misma cookie
- **THEN** la segunda llamada responde 403

#### Scenario: Rol vencido
- **WHEN** la asignación ADMIN del usuario tiene `vence_en` en el pasado
- **THEN** la ruta que exige ADMIN responde 403

#### Scenario: Sin sesión
- **WHEN** se llama sin cookie a una ruta que exige un rol
- **THEN** la respuesta es 401, no 403

### Requirement: Bloqueo por cambio de contraseña pendiente
Mientras el usuario actual tenga `debe_cambiar_password` verdadero, toda ruta del grupo protegido MUST responder 403 con un mensaje propio que indique que debe cambiar la contraseña, sin ejecutar la ruta y antes de evaluar roles. Las rutas `/auth/*` y `/health/*` MUST seguir disponibles. Tras cambiar la contraseña, con la cookie nueva, el grupo protegido MUST dejar de bloquear.

#### Scenario: Ruta protegida con cambio pendiente
- **WHEN** un usuario con `debe_cambiar_password` verdadero y rol ADMIN vigente llama a una ruta protegida que exige ADMIN
- **THEN** la respuesta es 403 con el mensaje de cambio de contraseña pendiente

#### Scenario: Rutas de auth y salud disponibles
- **WHEN** el mismo usuario llama a `GET /auth/yo`, `POST /auth/cambiar-password` y `GET /health/live`
- **THEN** ninguna responde 403 por el cambio pendiente

#### Scenario: Desbloqueo tras el cambio
- **WHEN** el usuario cambia la contraseña y repite la llamada a la ruta protegida con la cookie nueva
- **THEN** la ruta se ejecuta
