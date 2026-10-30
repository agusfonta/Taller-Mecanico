# Spec Delta — migraciones

## Purpose

Define cómo se crea y evoluciona el esquema: sólo mediante migraciones versionadas y reversibles (una generada a partir de los modelos y otra escrita a mano para lo que la generación automática no detecta), en sincronía con los modelos y sin datos de catálogo.

## ADDED Requirements

### Requirement: Esquema administrado sólo por migraciones
El esquema de la aplicación MUST crearse y modificarse exclusivamente aplicando migraciones versionadas. La aplicación MUST NOT crear tablas por sí misma al arrancar ni en ningún otro momento. La conexión de las migraciones MUST obtenerse de la configuración de la aplicación (entorno), nunca de un archivo versionado.

#### Scenario: Arranque no crea tablas
- **WHEN** la aplicación arranca contra una base vacía
- **THEN** la base sigue sin tablas de la aplicación

#### Scenario: Migrar desde cero
- **WHEN** se ejecuta la migración a la última versión sobre una base vacía
- **THEN** quedan creadas todas las tablas del modelo y la versión registrada es la última

### Requirement: Dos migraciones iniciales identificables
El historial SHALL contener, en este orden: (1) una migración que crea todas las tablas, generada automáticamente a partir de los modelos y revisada antes de aplicarse, con un comentario que lo indique; (2) una migración escrita a mano, con un comentario que lo indique, que instala la protección de sólo-agregado (función y disparadores), que la generación automática no detecta. Cada migración MUST tener reversión.

#### Scenario: Orden y origen de las migraciones
- **WHEN** se lista el historial de migraciones
- **THEN** hay exactamente dos, la primera crea las tablas y declara en un comentario que fue autogenerada y revisada, y la segunda depende de la primera y declara en un comentario que fue escrita a mano

#### Scenario: Revertir sólo la segunda
- **WHEN** desde la última versión se revierte una migración
- **THEN** las tablas siguen existiendo y la protección de sólo-agregado ya no está instalada

### Requirement: Migraciones reversibles de punta a punta
Aplicar todas las migraciones, revertirlas hasta la base y volver a aplicarlas MUST funcionar sin errores. Tras revertir hasta la base, MUST NOT quedar tablas, índices, funciones ni disparadores de la aplicación.

#### Scenario: Ida, vuelta e ida
- **WHEN** se ejecuta migrar a la última versión, revertir hasta la base y migrar a la última versión otra vez
- **THEN** las tres operaciones terminan sin error y el esquema final es idéntico al de la primera aplicación

#### Scenario: Nada queda tras revertir
- **WHEN** se revierte hasta la base
- **THEN** no existe ninguna de las 13 tablas ni la función de sólo-agregado

### Requirement: Modelos y migraciones en sincronía
Tras aplicar todas las migraciones, comparar el esquema resultante con los modelos de la aplicación MUST NOT arrojar diferencias (tablas, columnas, tipos, nulabilidad, restricciones, índices). Las tablas definidas sólo para pruebas MUST NOT formar parte de los modelos que ve la generación de migraciones.

#### Scenario: Sin diferencias pendientes
- **WHEN** después de migrar a la última versión se compara la base con los modelos
- **THEN** la comparación no informa ninguna diferencia

#### Scenario: Tablas de prueba invisibles
- **WHEN** se inspecciona el conjunto de tablas que ve la generación de migraciones
- **THEN** contiene exactamente las 13 tablas del modelo y ninguna tabla de prueba

### Requirement: Catálogo de estados vacío tras migrar
Las migraciones MUST crear `estado_orden` **sin filas**; la carga del catálogo es responsabilidad del script de datos iniciales. Ninguna migración MUST insertar datos de dominio ni contraseñas.

#### Scenario: Catálogo vacío
- **WHEN** se migra a la última versión una base vacía
- **THEN** `estado_orden` no tiene filas, y ninguna otra tabla de la aplicación tiene filas
