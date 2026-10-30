# Spec Delta — sesion-base-datos

## Purpose

Define el ciclo de vida de los recursos de acceso a PostgreSQL (motor y fábrica de sesiones): cuándo se crean, dónde viven, cómo se configura el pool, cómo cada petición obtiene su sesión y cómo se liberan al apagar, sin crear recursos al importar módulos (EA-08).

## ADDED Requirements

### Requirement: Recursos de base creados en el arranque, no al importar
El motor de base de datos y la fábrica de sesiones MUST crearse durante el arranque de la aplicación (lifespan) y SHALL quedar disponibles en el estado de la aplicación. Importar cualquier módulo de la aplicación (incluido el punto de entrada) MUST NOT crear motor, pool ni conexiones.

#### Scenario: Importar no crea recursos
- **WHEN** se importa el punto de entrada y el módulo de base de datos con la configuración completa y sin base de datos disponible
- **THEN** la importación termina con éxito y el estado de la aplicación no contiene motor ni fábrica de sesiones

#### Scenario: Arranque publica motor y fábrica
- **WHEN** la aplicación completa su arranque
- **THEN** el estado de la aplicación contiene un motor asincrónico y una fábrica de sesiones ligada a ese motor

#### Scenario: Arranque sin base disponible
- **WHEN** la aplicación arranca con la configuración completa y PostgreSQL no responde
- **THEN** el arranque termina con éxito (el motor no abre conexiones hasta que se usan); los fallos de conexión aparecen recién al usar una sesión

### Requirement: Liberación de recursos al apagar
Al apagarse la aplicación, el sistema MUST liberar el pool de conexiones del motor creado en el arranque, incluso si el apagado se produce tras un error en la aplicación.

#### Scenario: Apagado libera el motor
- **WHEN** la aplicación termina su ciclo de vida
- **THEN** el pool del motor se libera exactamente una vez

### Requirement: Pool configurable desde la configuración
El motor MUST tomar la URL de conexión, el tamaño del pool, las conexiones extra permitidas sobre el pool y la visibilidad de consultas en consola exclusivamente de la configuración (`DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `SQL_ECHO` y las `POSTGRES_*`). Ningún valor de conexión ni credencial MUST estar fijado en el código.

#### Scenario: Valores por defecto
- **WHEN** se crea el motor con la configuración por defecto
- **THEN** el pool tiene tamaño 5, admite 10 conexiones extra y no muestra consultas en consola

#### Scenario: Valores del entorno
- **WHEN** se crea el motor con `DB_POOL_SIZE=2`, `DB_MAX_OVERFLOW=0` y `SQL_ECHO=true`
- **THEN** el pool tiene tamaño 2, no admite conexiones extra y muestra las consultas en consola

### Requirement: Una sesión por petición
El sistema SHALL proveer a cada petición que la solicite una sesión de base de datos nueva, obtenida de la fábrica del estado de la aplicación, y MUST cerrarla al terminar la petición, haya terminado con éxito o con error. Los objetos leídos MUST seguir siendo legibles tras confirmar la transacción sin volver a consultar la base.

#### Scenario: Sesiones distintas por petición
- **WHEN** dos peticiones solicitan una sesión
- **THEN** cada una recibe una sesión distinta

#### Scenario: Cierre al terminar
- **WHEN** termina una petición que usó una sesión, con éxito o con excepción
- **THEN** la sesión queda cerrada y su conexión vuelve al pool

#### Scenario: Atributos legibles tras confirmar
- **WHEN** se confirma una transacción que creó una fila
- **THEN** los atributos del objeto (incluido su identificador) se leen sin emitir otra consulta a la base
