# Spec Delta — configuracion

## Purpose

Define cómo la aplicación obtiene su configuración desde el entorno: qué variables existen, cuáles son secretos obligatorios sin valor por defecto, qué valores por defecto tienen las demás y cómo se deriva la URL de conexión a PostgreSQL, sin que ningún secreto quede en el repositorio.

## ADDED Requirements

### Requirement: Secretos obligatorios sin valor por defecto
El sistema MUST exigir `JWT_SECRET_KEY` y `POSTGRES_PASSWORD` desde el entorno (o un archivo `.env`) y SHALL negarse a cargar la configuración si alguna falta o está vacía. Ninguna de las dos variables MUST tener un valor por defecto en el código.

#### Scenario: Falta la clave de firma JWT
- **WHEN** se carga la configuración con todas las variables salvo `JWT_SECRET_KEY`
- **THEN** la carga falla con un error de validación que nombra `JWT_SECRET_KEY`

#### Scenario: Falta la contraseña de la base
- **WHEN** se carga la configuración con todas las variables salvo `POSTGRES_PASSWORD`
- **THEN** la carga falla con un error de validación que nombra `POSTGRES_PASSWORD`

#### Scenario: Secreto presente pero vacío
- **WHEN** `JWT_SECRET_KEY` o `POSTGRES_PASSWORD` se definen como cadena vacía
- **THEN** la carga falla con un error de validación sobre esa variable

#### Scenario: Clave de firma demasiado corta
- **WHEN** `JWT_SECRET_KEY` tiene menos de 32 caracteres
- **THEN** la carga falla con un error de validación sobre `JWT_SECRET_KEY`

### Requirement: Variables de entorno reconocidas
El sistema SHALL reconocer exactamente estas variables: `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_HOST`, `POSTGRES_PORT`, `SQL_ECHO`, `JWT_SECRET_KEY`, `JWT_EXPIRE_MINUTES`, `BCRYPT_ROUNDS`, `BCRYPT_MAX_CONCURRENCY`, `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `COOKIE_SECURE`. Variables de entorno ajenas a esta lista MUST ser ignoradas sin error.

#### Scenario: Valores tomados del entorno
- **WHEN** el entorno define `POSTGRES_HOST=db`, `POSTGRES_PORT=6543`, `JWT_EXPIRE_MINUTES=15` y `BCRYPT_ROUNDS=4` junto con los secretos
- **THEN** la configuración cargada refleja esos cuatro valores

#### Scenario: Variable ajena en el entorno
- **WHEN** el entorno contiene además una variable no reconocida (por ejemplo `PATH` u `OTRA_COSA=1`)
- **THEN** la configuración se carga sin error

### Requirement: Valores por defecto de rendimiento y seguridad
Las variables no secretas SHALL tener valor por defecto cuando no se definen: `JWT_EXPIRE_MINUTES=30`, `BCRYPT_ROUNDS=12`, `BCRYPT_MAX_CONCURRENCY=4`, `DB_POOL_SIZE=5`, `DB_MAX_OVERFLOW=10`, `SQL_ECHO=false`, `COOKIE_SECURE=false`, `POSTGRES_HOST=localhost`, `POSTGRES_PORT=5432`, `POSTGRES_USER=taller`, `POSTGRES_DB=taller_db`. La duración del token SHALL estar disponible también en segundos.

#### Scenario: Sólo los secretos definidos
- **WHEN** se carga la configuración definiendo únicamente `JWT_SECRET_KEY` y `POSTGRES_PASSWORD`
- **THEN** los demás valores son los por defecto listados en el requisito

#### Scenario: Duración del token en segundos
- **WHEN** `JWT_EXPIRE_MINUTES` vale 30
- **THEN** la duración del token en segundos es 1800

#### Scenario: Duración del token personalizada
- **WHEN** `JWT_EXPIRE_MINUTES` vale 15
- **THEN** la duración del token en segundos es 900

### Requirement: Rangos válidos de los parámetros numéricos
El sistema MUST rechazar valores fuera de rango: `BCRYPT_ROUNDS` entre 4 y 31, `BCRYPT_MAX_CONCURRENCY` ≥ 1, `DB_POOL_SIZE` ≥ 1, `DB_MAX_OVERFLOW` ≥ 0, `JWT_EXPIRE_MINUTES` ≥ 1, `POSTGRES_PORT` entre 1 y 65535.

#### Scenario: Costo de bcrypt fuera de rango
- **WHEN** `BCRYPT_ROUNDS` vale 3 o 32
- **THEN** la carga falla con un error de validación sobre `BCRYPT_ROUNDS`

#### Scenario: Pool en cero
- **WHEN** `DB_POOL_SIZE` vale 0
- **THEN** la carga falla con un error de validación sobre `DB_POOL_SIZE`

#### Scenario: Valor no numérico
- **WHEN** `POSTGRES_PORT` vale `abc`
- **THEN** la carga falla con un error de validación sobre `POSTGRES_PORT`

### Requirement: URL de conexión calculada
El sistema SHALL derivar la URL de conexión asincrónica a PostgreSQL a partir de las variables `POSTGRES_*`, con el formato `postgresql+asyncpg://<usuario>:<contraseña>@<host>:<puerto>/<base>`, escapando los caracteres especiales de usuario y contraseña. La URL no SHALL poder definirse directamente por una variable propia.

#### Scenario: URL con valores simples
- **WHEN** `POSTGRES_USER=taller`, `POSTGRES_PASSWORD=secreto`, `POSTGRES_HOST=localhost`, `POSTGRES_PORT=5432`, `POSTGRES_DB=taller_db`
- **THEN** la URL es `postgresql+asyncpg://taller:secreto@localhost:5432/taller_db`

#### Scenario: Contraseña con caracteres especiales
- **WHEN** `POSTGRES_PASSWORD` contiene `@`, `:` o `/` (por ejemplo `p@ss:w/rd`)
- **THEN** la URL contiene la contraseña escapada (`p%40ss%3Aw%2Frd`) y apunta al host y base configurados

### Requirement: Los secretos no se exponen al representar la configuración
La representación textual de la configuración (por ejemplo al imprimirla o registrarla en logs) MUST NOT contener el valor de `JWT_SECRET_KEY`, de `POSTGRES_PASSWORD` ni la URL de conexión con la contraseña.

#### Scenario: Imprimir la configuración
- **WHEN** se obtiene la representación textual de una configuración cargada
- **THEN** no aparece el valor de la clave de firma ni el de la contraseña de la base

### Requirement: Archivos de configuración versionados sin secretos
El repositorio SHALL incluir `env.example` con todas las variables reconocidas y MUST dejar sin valor `JWT_SECRET_KEY` y `POSTGRES_PASSWORD`. `alembic.ini` MUST NOT contener una URL de conexión ni credenciales. `.env` MUST estar excluido del control de versiones. No SHALL existir variables para contraseñas de usuarios semilla.

#### Scenario: env.example completo y sin secretos
- **WHEN** se inspecciona `env.example`
- **THEN** contiene una entrada por cada variable reconocida, `JWT_SECRET_KEY` y `POSTGRES_PASSWORD` sin valor, y ninguna variable `SEED_*`

#### Scenario: alembic.ini sin credenciales
- **WHEN** se inspecciona `alembic.ini`
- **THEN** no hay una `sqlalchemy.url` con valor

#### Scenario: .env ignorado
- **WHEN** se inspecciona `.gitignore`
- **THEN** incluye `.env`
