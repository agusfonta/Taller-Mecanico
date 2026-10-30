# salud Specification

## Purpose

Permite a quien opera la API distinguir un proceso vivo (que no conviene reiniciar) de un proceso listo para atender peticiones (que además alcanza PostgreSQL), sin requerir sesión y sin exponer detalles internos.

## Requirements


### Requirement: Chequeo de vida sin tocar la base
La aplicación SHALL exponer `GET /health/live`, que MUST responder 200 con un cuerpo JSON propio mientras el proceso atienda peticiones. La respuesta MUST NOT depender de la base de datos: la ruta MUST NOT abrir sesiones ni conexiones a PostgreSQL.

#### Scenario: Proceso vivo con la base disponible
- **WHEN** se llama a `GET /health/live` con PostgreSQL disponible
- **THEN** la respuesta es 200 con un cuerpo JSON que indica que el proceso está vivo

#### Scenario: Proceso vivo con la base caída
- **WHEN** se llama a `GET /health/live` con PostgreSQL sin responder
- **THEN** la respuesta es 200, igual que con la base disponible, y no se intentó ninguna conexión a la base

### Requirement: Chequeo de disponibilidad contra la base
La aplicación SHALL exponer `GET /health/ready`, que MUST ejecutar una consulta trivial (`SELECT 1`) contra PostgreSQL. Si la base contesta, MUST responder 200 con un cuerpo JSON que indica que el servicio está listo. Si la base no contesta, rechaza la conexión, la consulta falla o no se completa dentro del tiempo máximo, MUST responder 503 con un cuerpo JSON que indica que el servicio no está listo. El chequeo MUST NOT modificar datos ni depender de que existan tablas de la aplicación.

#### Scenario: Base disponible
- **WHEN** se llama a `GET /health/ready` con PostgreSQL disponible (aun sin migraciones aplicadas)
- **THEN** la respuesta es 200 con un cuerpo JSON que indica que el servicio está listo

#### Scenario: Base que rechaza la conexión
- **WHEN** se llama a `GET /health/ready` y no hay servidor PostgreSQL escuchando en el host y puerto configurados
- **THEN** la respuesta es 503 con un cuerpo JSON que indica que el servicio no está listo

#### Scenario: Base que no contesta a tiempo
- **WHEN** se llama a `GET /health/ready` y la base no completa la consulta dentro del tiempo máximo
- **THEN** la respuesta es 503 y llega a lo sumo 3 segundos después de la petición, sin esperar al tiempo de conexión por defecto del driver

#### Scenario: Recuperación sin reiniciar
- **WHEN** `GET /health/ready` respondió 503 por base caída y luego la base vuelve a estar disponible
- **THEN** una nueva llamada responde 200 sin reiniciar el proceso

### Requirement: Respuestas de salud sin detalles internos
Las respuestas de `GET /health/live` y `GET /health/ready`, incluido el 503, MUST NOT contener trazas, texto de excepciones, nombres de clases de error, la URL de conexión, el host, el puerto, el usuario ni la contraseña de la base. El cuerpo MUST limitarse a un estado propio y fijo.

#### Scenario: 503 sin filtrar el motivo
- **WHEN** `GET /health/ready` responde 503 porque la conexión a la base falló con un error que menciona host y puerto
- **THEN** el cuerpo contiene sólo el estado propio "no listo" y no incluye el host, el puerto, el usuario, la contraseña ni el mensaje del error

### Requirement: Salud accesible sin sesión
Las rutas de salud MUST pertenecer al grupo abierto de rutas: cualquier cliente MUST poder llamarlas sin sesión ni cookie, y MUST NOT pasar por el control de acceso del grupo protegido, ni hoy (control que rechaza todo) ni cuando exista autenticación (incluido el bloqueo por cambio obligatorio de contraseña).

#### Scenario: Llamada sin sesión mientras el grupo protegido rechaza todo
- **WHEN** se llama a `GET /health/live` y a `GET /health/ready` sin cookie, con el control del grupo protegido rechazando toda petición
- **THEN** ninguna de las dos responde 401 ni 403, y el control del grupo protegido no se ejecuta
