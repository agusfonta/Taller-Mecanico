# entrega Specification

## Purpose

Define los artefactos con los que se entrega el trabajo práctico y se demuestran sus casos de prueba: README con los pasos desde cero, archivos `.http` por caso, `test/solo_agregado.sql`, evidencias de C-14 y C-15 y la matriz de trazabilidad, sin credenciales reales en ninguno.

## Requirements

### Requirement: README con los pasos desde cero
El repositorio SHALL incluir `README.md` en la raíz con, en este orden: crear y activar el entorno virtual; instalar dependencias desde `requirements.txt` (y `requirements-dev.txt` para correr los tests); crear `.env` a partir de `env.example`, indicando el comando para generar `JWT_SECRET_KEY` y que `POSTGRES_PASSWORD` se define a mano; levantar PostgreSQL; `alembic upgrade head`; `python seed.py`; y arrancar el servidor. El README MUST advertir que `python seed.py` borra todos los datos de la base destino, MUST indicar que `.env` no se versiona y MUST explicar cómo correr los `.http`, `test/solo_agregado.sql` y la suite `pytest`. Las contraseñas de los usuarios semilla MUST NOT aparecer en el README: SHALL indicarse que están en `CONTRASENAS_SEED` dentro de `seed.py`.

#### Scenario: Pasos en orden
- **WHEN** se lee `README.md`
- **THEN** aparecen, en este orden, entorno virtual, dependencias, `.env` con el comando para generar la clave de firma, `alembic upgrade head`, `python seed.py` y el arranque del servidor

#### Scenario: Sin contraseñas del seed
- **WHEN** se busca en `README.md` cada contraseña de `CONTRASENAS_SEED`
- **THEN** ninguna aparece y el README nombra `CONTRASENAS_SEED` en `seed.py` como su ubicación

#### Scenario: Seguir el README desde cero
- **WHEN** alguien sigue el README sobre una base PostgreSQL vacía
- **THEN** `alembic upgrade head` crea el esquema, `python seed.py` termina con código 0, el servidor arranca y `GET /health/ready` responde 200

### Requirement: Un archivo `.http` por caso de prueba
`test/` SHALL contener un archivo `.http` por cada caso C-01..C-19 salvo C-14, nombrado con el número del caso (`cNN_<tema>.http`). Cada archivo MUST poder correrse de principio a fin con la extensión REST Client contra el servidor local inmediatamente después de `python seed.py`, sin depender de otro archivo. Cada pedido MUST llevar en un comentario la respuesta esperada (código HTTP y lo relevante del cuerpo o encabezados según la KB 11). Los casos con varias sesiones simultáneas (C-07) MUST nombrar cada login con `# @name` y enviar la cookie de esa sesión explícitamente con `# @no-cookie-jar`.

#### Scenario: Cobertura de los casos
- **WHEN** se listan los archivos `test/*.http`
- **THEN** hay exactamente uno para cada caso C-01..C-13 y C-15..C-19

#### Scenario: Respuesta esperada documentada
- **WHEN** se inspecciona cada pedido de un archivo `.http`
- **THEN** cada pedido está precedido por un comentario con el código HTTP esperado

#### Scenario: Corrida tras el seed
- **WHEN** se corre `python seed.py` y luego todos los pedidos de un archivo `.http`, en orden, contra el servidor local
- **THEN** cada respuesta coincide con la esperada en su comentario

#### Scenario: Dos sesiones en el mismo archivo
- **WHEN** se corre `test/c07_*.http`
- **THEN** los pedidos del administrador y los del usuario revocado usan cada uno la cookie de su propio login, y el pedido posterior a la revocación responde 403

### Requirement: Credenciales fuera de los artefactos de prueba
Los archivos `.http`, `test/solo_agregado.sql`, el README y las evidencias MUST NOT contener contraseñas de los usuarios semilla, la clave de firma JWT, la contraseña de la base ni una cookie de sesión válida. Las contraseñas necesarias para los logins de los `.http` SHALL obtenerse en el momento de enviar el pedido, sin quedar escritas en el archivo.

#### Scenario: Recorrido de secretos
- **WHEN** se recorren los archivos de texto del repositorio salvo `seed.py` y `.env`
- **THEN** ninguno contiene literalmente una contraseña de `CONTRASENAS_SEED`

#### Scenario: Evidencias sin secretos
- **WHEN** se revisan las evidencias de C-14 y C-15
- **THEN** no muestran la contraseña de la base, la clave de firma ni el valor de la cookie `access_token`

### Requirement: Script de sólo agregado para C-14
`test/solo_agregado.sql` SHALL contener, para correr con `psql` sobre una base migrada y cargada con el seed, un UPDATE y un DELETE sobre cada una de `historial_estado_orden`, `movimiento_stock` e `historial_precio_repuesto` (seis sentencias) que afectan filas existentes del seed, y un INSERT de una orden de trabajo con un estado que no está en `estado_orden`. Cada sentencia MUST ejecutarse en forma independiente de modo que el rechazo de una no impida intentar la siguiente, y cada una MUST llevar en un comentario el rechazo esperado. El script MUST NOT dejar cambios en la base.

#### Scenario: Seis rechazos del disparador
- **WHEN** se corre `test/solo_agregado.sql` con `psql` después de `python seed.py`
- **THEN** las seis sentencias UPDATE/DELETE fallan con el mensaje del disparador de sólo agregado que nombra la tabla y la operación

#### Scenario: Rechazo por clave foránea
- **WHEN** se ejecuta el INSERT de la orden con estado fuera del catálogo
- **THEN** falla por la clave foránea de `orden_trabajo.estado` y no se crea ninguna orden

#### Scenario: Base intacta
- **WHEN** termina el script
- **THEN** los conteos de las tres tablas y de `orden_trabajo` son los mismos que antes de correrlo

### Requirement: Evidencias de C-14 y C-15
El repositorio SHALL incluir en `docs/evidencias/` una captura PNG de `psql` con los seis rechazos del disparador y el de la clave foránea (C-14), y una captura PNG de la consola del servidor con `SQL_ECHO=true` que muestre las consultas del detalle de una orden de 2 ítems y de otra de 4 con la misma cantidad de consultas (C-15). Cada captura MUST mostrar el comando o pedido y su resultado, y SHALL acompañarse de un fragmento de texto equivalente.

#### Scenario: Evidencia C-14
- **WHEN** se abre la evidencia de C-14
- **THEN** se ven el comando `psql` y siete errores: seis del disparador y uno de clave foránea

#### Scenario: Evidencia C-15
- **WHEN** se abre la evidencia de C-15
- **THEN** se ven los dos `GET /ordenes/{id}` (2 y 4 ítems) y, para cada uno, el mismo número de sentencias SQL

### Requirement: Ninguna entrada inválida termina en 500
Antes de la entrega, toda ruta de la API MUST responder con un código 4xx y un mensaje propio ante una entrada inválida (parámetro de ruta o de consulta de tipo incorrecto o fuera del rango representable por la base, cuerpo con campos extra, tipos incorrectos, JSON mal formado o valores fuera de rango), y MUST NOT devolver 500, el texto de un `IntegrityError` u otro error de la base, ni una traza. En particular, un identificador de ruta entero mayor que el máximo de un `BIGINT` (9223372036854775807) o menor que su mínimo MUST responder 422 sin consultar la base; los ids dentro de rango que no existen conservan su respuesta actual (404 o la que fije cada spec).

#### Scenario: Id de ruta fuera de rango
- **WHEN** un usuario con sesión pide `GET /ordenes/99999999999999999999`
- **THEN** la respuesta es 422 y no 500

#### Scenario: Barrido de entradas inválidas
- **WHEN** se envía a cada endpoint de la tabla de la KB 06 un cuerpo con un campo extra, un tipo incorrecto o JSON mal formado, y un id de ruta no entero o fuera de rango
- **THEN** ninguna respuesta es 500 y ningún cuerpo contiene texto de la base ni una traza

### Requirement: Matriz de trazabilidad de los casos
La entrega SHALL incluir una matriz que, para cada caso C-01..C-19, indique el artefacto manual que lo demuestra (`.http` o SQL), los tests automáticos que lo cubren y el resultado observado en la verificación de punta a punta sobre una base recién migrada y cargada con el seed. Un caso cuyo resultado observado difiera del esperado MUST NOT figurar como aprobado.

#### Scenario: Matriz completa
- **WHEN** se lee la matriz
- **THEN** hay una fila por cada caso C-01..C-19, con artefacto manual, al menos un test automático y el resultado observado

#### Scenario: Resultado distinto del esperado
- **WHEN** un caso no da el resultado esperado durante la verificación
- **THEN** figura como fallido con lo observado, y la entrega no se da por cerrada hasta corregirlo
