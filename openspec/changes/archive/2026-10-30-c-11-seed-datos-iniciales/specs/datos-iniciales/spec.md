# Spec Delta — datos-iniciales

## Purpose

Deja la base en un estado inicial conocido y reproducible con `python seed.py` (después de `alembic upgrade head`): catálogo de estados, usuarios por rol, clientes, vehículos, repuestos con stock trazado, dos órdenes y sus historiales, sobre los que se demuestran los casos de prueba de la KB 11 (en particular C-11 y C-12).

## ADDED Requirements

### Requirement: Ejecución y reemplazo atómico del contenido
`seed.py` SHALL ejecutarse desde la raíz del proyecto con `python seed.py`, leyendo la conexión sólo de la configuración del entorno (las mismas variables `POSTGRES_*` de la aplicación). En una única transacción MUST vaciar las 13 tablas de negocio de la KB 04 (reiniciando sus secuencias de identidad) y cargar el contenido inicial completo; MUST NOT tocar la tabla de versión de migraciones. Si cualquier paso falla, MUST revertir todo, dejando la base exactamente como estaba antes de ejecutarlo, y MUST terminar con código de salida distinto de 0 y un mensaje legible sin traza ni credenciales. Si termina bien MUST salir con código 0.

#### Scenario: Ejecución sobre una base migrada
- **WHEN** se corre `python seed.py` sobre una base con `alembic upgrade head` aplicado y con datos previos cualesquiera
- **THEN** sale con código 0 y las 13 tablas contienen exactamente el contenido inicial de esta especificación

#### Scenario: Falla a mitad de la carga
- **WHEN** la carga falla después de vaciar las tablas (por ejemplo, una restricción violada)
- **THEN** la transacción se revierte, los datos previos siguen intactos y el código de salida es distinto de 0

#### Scenario: Base sin migrar
- **WHEN** se corre `python seed.py` sobre una base sin las tablas de la migración
- **THEN** sale con código distinto de 0 y un mensaje que indica correr `alembic upgrade head`, sin traza

### Requirement: Idempotencia
Ejecutar `seed.py` N veces seguidas MUST dejar el mismo estado que ejecutarlo una vez: mismas filas, mismos identificadores y mismos valores (salvo marcas de tiempo y los hashes de contraseña, que se recalculan con sal nueva y siguen verificando la misma contraseña).

#### Scenario: Dos ejecuciones seguidas
- **WHEN** se corre `seed.py`, se modifica la base por la API (por ejemplo, se termina una orden o se registra un cliente) y se vuelve a correr `seed.py`
- **THEN** el contenido de las 13 tablas (sin marcas de tiempo ni hashes) es idéntico al de la primera ejecución, incluidos los identificadores

### Requirement: Catálogo de estados primero
El catálogo `estado_orden` MUST cargarse antes que cualquier orden o historial de estado, con exactamente cuatro filas: PENDIENTE (posición 1, no final), EN_REPARACION (2, no final), TERMINADA (3, final) y CANCELADA (4, final), cada una con una descripción no vacía.

#### Scenario: Catálogo cargado
- **WHEN** termina `seed.py`
- **THEN** `GET /estados-orden` devuelve los cuatro estados en ese orden con `es_final` verdadero sólo en TERMINADA y CANCELADA

### Requirement: Usuarios y roles iniciales
`seed.py` MUST crear exactamente estos usuarios activos, cada uno con una única asignación de rol abierta, sin vencimiento y sin otorgante:

| id | email | rol | cambio de contraseña obligatorio |
|---|---|---|---|
| 1 | `admin@example.com` | ADMIN | no |
| 2 | `admin2@example.com` | ADMIN | no |
| 3 | `recepcion@example.com` | RECEPCION | no |
| 4 | `mecanico@example.com` | MECANICO | no |
| 5 | `mecanico2@example.com` | MECANICO | no |
| 6 | `cliente@example.com` | CLIENTE | no |
| 7 | `nuevo@example.com` | MECANICO | sí |

Cada usuario MUST tener una contraseña fija y ficticia de al menos 8 caracteres y como máximo 72 bytes, distinta entre usuarios, que permita iniciar sesión por `POST /auth/login`. Esas contraseñas MUST estar definidas únicamente en `seed.py` (no en variables de entorno, `env.example` ni otro archivo del repositorio) y MUST NOT imprimirse en la salida. Sólo su hash bcrypt, con el costo configurado en `BCRYPT_ROUNDS`, se guarda en la base.

#### Scenario: Login de cada usuario semilla
- **WHEN** cada uno de los siete usuarios inicia sesión con su contraseña de seed
- **THEN** la respuesta es 200 y `GET /auth/yo` muestra el rol de la tabla

#### Scenario: Usuario con cambio obligatorio
- **WHEN** `nuevo@example.com` inicia sesión y llama a una ruta protegida fuera de `/auth`
- **THEN** la respuesta es 403 (punto de partida del caso C-09)

#### Scenario: Contraseñas fuera de la salida
- **WHEN** se corre `seed.py`
- **THEN** la salida no contiene ninguna contraseña ni hash

### Requirement: Clientes y vehículos iniciales
`seed.py` MUST crear el cliente Laura (id 1) vinculado al usuario `cliente@example.com` con dos vehículos vigentes (ids 1 y 2), y el cliente Jorge (id 2) sin usuario con un vehículo vigente (id 3). Los documentos MUST ser distintos y las patentes MUST guardarse normalizadas (mayúsculas, sin espacios ni guiones) y ser distintas entre sí.

#### Scenario: Vehículos del cliente
- **WHEN** `cliente@example.com` consulta sus vehículos
- **THEN** recibe exactamente los dos vehículos de Laura

#### Scenario: Jorge sin usuario
- **WHEN** se consulta la fila de Jorge
- **THEN** su `usuario_id` es nulo y tiene exactamente un vehículo vigente

### Requirement: Repuestos y stock inicial trazado
`seed.py` MUST crear, en este orden y con estos ids, los repuestos vigentes: 1 `FIL-001` filtro de aceite (stock 10, precio 8500.00), 2 `FRE-010` pastillas de freno (stock 4), 3 `BUJ-001` bujía (stock 2) y 4 `ACE-530` aceite por litro (stock 20), con precios `NUMERIC` positivos. El stock de cada repuesto MUST quedar respaldado por exactamente un movimiento de stock con motivo "Stock inicial", cantidad igual al stock, sin orden y con autor `admin@example.com`, de modo que la suma de movimientos de cada repuesto coincida con su stock. Sólo la descripción de `FRE-010` MUST contener la palabra "freno".

#### Scenario: Stock coherente con los movimientos
- **WHEN** termina `seed.py`
- **THEN** para cada repuesto la suma de sus movimientos es igual a su stock y hay exactamente cuatro movimientos, todos "Stock inicial"

#### Scenario: Búsqueda por "freno"
- **WHEN** un administrador busca repuestos con `q=freno&size=1`
- **THEN** la respuesta tiene `total` 1 y `pages` 1 (punto de partida del caso C-16)

### Requirement: Historial de precio inicial
`seed.py` MUST registrar exactamente una línea de historial de precios: la del filtro de aceite (`FIL-001`) de 8000.00 a 8500.00, con autor `admin@example.com`; el precio vigente del filtro MUST ser 8500.00.

#### Scenario: Historial del filtro
- **WHEN** un administrador consulta `GET /repuestos/1/precios`
- **THEN** recibe una única línea con precio anterior 8000.00 y precio nuevo 8500.00

### Requirement: Órdenes iniciales
`seed.py` MUST crear exactamente dos órdenes:

- Orden 1: PENDIENTE, sobre el primer vehículo de Laura (vehículo 1), sin mecánico asignado, con al menos un ítem; historial con una línea `NULL → PENDIENTE` de autor `recepcion@example.com`.
- Orden 2: EN_REPARACION, sobre el vehículo de Jorge (vehículo 3), asignada a `mecanico@example.com`, con un ítem de 1 `FIL-001` y otro de 4 `BUJ-001` (más bujías que su stock de 2); historial `NULL → PENDIENTE` (autor `recepcion@example.com`) y `PENDIENTE → EN_REPARACION` (autor `mecanico@example.com`).

Cada ítem MUST copiar como precio unitario el precio vigente del repuesto y el total de cada orden MUST ser la suma exacta (decimal) de cantidad por precio unitario. Ninguna orden inicial MUST tener movimientos de stock asociados.

#### Scenario: Terminar la orden 2 sin stock (caso C-11)
- **WHEN** `mecanico@example.com` inicia sesión con su contraseña de seed y llama `POST /ordenes/2/terminar`
- **THEN** la respuesta es 409 con un mensaje que nombra `BUJ-001`, y el estado de la orden, el stock de los repuestos, los movimientos de stock y el historial de estado quedan idénticos a los dejados por el seed

#### Scenario: Reponer y terminar la orden 2 (caso C-12)
- **WHEN** `admin@example.com` repone al menos 2 bujías y luego `mecanico@example.com` llama `POST /ordenes/2/terminar`
- **THEN** la respuesta es 200, la orden queda TERMINADA, el stock del filtro baja en 1 y el de la bujía en 4, aparecen dos movimientos con la orden 2 y una línea de historial `EN_REPARACION → TERMINADA`

#### Scenario: Visibilidad inicial de las órdenes
- **WHEN** `cliente@example.com` pide la orden 1 y la orden 2, y `mecanico2@example.com` lista las órdenes
- **THEN** el cliente recibe 200 para la 1 y 403 para la 2 (caso C-06), y el listado de `mecanico2` no incluye la orden 2 (DD-18)

### Requirement: Evento de seguridad de la carga
`seed.py` MUST dejar exactamente una línea en el historial de seguridad, con actor `SISTEMA` y acción "Carga de los datos iniciales", y ninguna fila en `intento_acceso`.

#### Scenario: Historial de seguridad tras el seed
- **WHEN** un administrador consulta el historial de seguridad justo después del seed
- **THEN** ve una única línea con actor `SISTEMA` y acción "Carga de los datos iniciales"

### Requirement: Garantías de la base intactas
`seed.py` MUST cargar los datos sin desactivar, borrar ni recrear disparadores, restricciones o índices, y sin ejecutar UPDATE ni DELETE sobre las tablas de sólo agregado (`historial_estado_orden`, `movimiento_stock`, `historial_precio_repuesto`). Tras el seed, UPDATE y DELETE sobre esas tablas MUST seguir rechazándose.

#### Scenario: Sólo agregado después del seed
- **WHEN** después de `seed.py` se intenta un UPDATE o un DELETE sobre cualquiera de las tres tablas de sólo agregado
- **THEN** el disparador lo rechaza

### Requirement: Guarda de destino
Antes de vaciar, `seed.py` MUST informar el destino (host, puerto y base, nunca la contraseña). Si el host de la configuración no es local (`localhost`, `127.0.0.1` o `::1`), MUST negarse a ejecutar, sin modificar nada y con código de salida distinto de 0, salvo que se lo invoque con una bandera explícita de confirmación (`--permitir-remoto`).

#### Scenario: Host remoto sin bandera
- **WHEN** `POSTGRES_HOST` apunta a un host no local y se corre `python seed.py`
- **THEN** no se abre ninguna transacción de escritura, la base no cambia y el código de salida es distinto de 0 con un mensaje que menciona la bandera

#### Scenario: Host remoto con bandera
- **WHEN** `POSTGRES_HOST` apunta a un host no local y se corre `python seed.py --permitir-remoto`
- **THEN** el seed se ejecuta normalmente
