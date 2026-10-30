# historial-seguridad Specification

## Purpose

Deja constancia en `evento_seguridad` de las acciones administrativas sobre usuarios y roles, en la misma transacción que las produce, y permite que un administrador consulte todo el historial de seguridad de forma paginada (US-022).

## Requirements

### Requirement: Eventos de las acciones administrativas
Cada alta de personal, asignación de rol y revocación de rol confirmada MUST dejar exactamente una línea en `evento_seguridad`, escrita en la misma transacción que la acción: si la acción no se confirma, la línea MUST NOT quedar, y si la línea no puede escribirse, la acción MUST NOT quedar. El `actor` MUST ser el correo del administrador que hizo la acción y la `accion` MUST describir qué se hizo, a qué usuario (por su correo) y con qué rol, incluyendo el vencimiento cuando lo haya. Ninguna línea MUST contener contraseñas ni hashes. Las peticiones rechazadas (401, 403, 404, 409, 422) MUST NOT dejar líneas.

#### Scenario: Evento del alta de personal
- **WHEN** `admin@taller.com` da de alta a `nuevo@taller.com` con rol MECANICO
- **THEN** existe una línea nueva con actor `admin@taller.com` y una acción que menciona el alta de personal, `nuevo@taller.com` y `MECANICO`, sin la contraseña provisoria

#### Scenario: Evento de asignación con vencimiento
- **WHEN** un ADMIN asigna RECEPCION con vencimiento a un usuario
- **THEN** existe una línea nueva con actor el correo del ADMIN y una acción que menciona la asignación, el correo del usuario, `RECEPCION` y el vencimiento

#### Scenario: Evento de revocación
- **WHEN** un ADMIN revoca MECANICO a un usuario
- **THEN** existe una línea nueva con actor el correo del ADMIN y una acción que menciona la revocación, el correo del usuario y `MECANICO`

#### Scenario: Acción rechazada sin evento
- **WHEN** una asignación responde 409 o una revocación responde 409 por autoprotección
- **THEN** la cantidad de filas de `evento_seguridad` no cambió

### Requirement: Consulta paginada del historial de seguridad
`GET /eventos` SHALL pertenecer al grupo protegido y MUST ejecutarse sólo si el usuario actual tiene ADMIN vigente (401 sin sesión; 403 sin ADMIN o con cambio de contraseña pendiente). MUST aceptar `page` y `size` y responder con el envoltorio común de listados (`items`, `total`, `page`, `size`, `pages`), con las mismas reglas de validación y 422 que el resto de los listados. Cada elemento MUST tener `id`, `cuando`, `actor` y `accion`. Los eventos MUST ordenarse del más reciente al más antiguo (a igual instante, el de mayor id primero). MUST incluir los eventos de todas las fuentes (registro, cambio de contraseña, acciones administrativas y carga inicial con actor `SISTEMA`).

#### Scenario: Historial con eventos de distintas fuentes
- **WHEN** un cliente se registra, cambia su contraseña y luego un ADMIN le asigna un rol, y el ADMIN pide `GET /eventos`
- **THEN** la respuesta es 200 con `total` igual a la cantidad de eventos y `items` empezando por la asignación de rol, seguida del cambio de contraseña y del registro

#### Scenario: Paginación
- **WHEN** hay 3 eventos y el ADMIN pide `GET /eventos?page=2&size=2`
- **THEN** la respuesta es 200 con un solo elemento (el más antiguo), `total` 3 y `pages` 2

#### Scenario: Página o tamaño inválidos
- **WHEN** el ADMIN pide `GET /eventos?size=500`, `GET /eventos?page=0` o una página mayor que la última
- **THEN** la respuesta es 422

#### Scenario: No administrador
- **WHEN** un usuario con sólo CLIENTE pide `GET /eventos`
- **THEN** la respuesta es 403
