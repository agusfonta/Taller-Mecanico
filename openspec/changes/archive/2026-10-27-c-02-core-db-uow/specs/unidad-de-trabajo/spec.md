# Spec Delta — unidad-de-trabajo

## Purpose

Define la frontera transaccional de cada operación de negocio: una Unit of Work que confirma todo lo hecho dentro de su bloque, lo revierte ante cualquier error y nunca cierra la sesión que recibió, compartida por todos los repositorios del módulo.

## ADDED Requirements

### Requirement: Confirmación al salir sin error
La Unit of Work MUST confirmar la transacción de su sesión al salir de su bloque sin excepción, de modo que los cambios hechos por los repositorios dentro del bloque queden visibles para otras conexiones.

#### Scenario: Cambios confirmados
- **WHEN** dentro de un bloque de UoW se agrega una fila y el bloque termina sin error
- **THEN** la fila es visible desde otra sesión independiente

### Requirement: Reversión ante excepción
Si dentro del bloque de la Unit of Work se produce una excepción, la UoW MUST revertir la transacción y SHALL propagar la misma excepción sin ocultarla ni transformarla. Si la confirmación misma falla, la UoW MUST revertir y propagar el error de la confirmación.

#### Scenario: Excepción en el bloque
- **WHEN** dentro de un bloque de UoW se agrega una fila y luego se lanza una excepción
- **THEN** la excepción llega a quien abrió el bloque y la fila no es visible desde otra sesión

#### Scenario: Falla al confirmar
- **WHEN** la confirmación al salir del bloque viola una restricción de la base
- **THEN** la transacción queda revertida, el error de la base se propaga y la sesión sigue utilizable

### Requirement: La UoW no cierra la sesión
La Unit of Work MUST NOT cerrar la sesión que recibió, ni al confirmar ni al revertir: quien creó la sesión es quien la cierra.

#### Scenario: Sesión abierta tras el bloque
- **WHEN** termina un bloque de UoW, con o sin excepción
- **THEN** la sesión recibida no fue cerrada por la UoW y puede usarse para una nueva transacción

### Requirement: Repositorios del módulo sobre la misma sesión
Una Unit of Work de módulo SHALL exponer sus repositorios construidos sobre la misma sesión que la UoW, de modo que todas las escrituras de una operación de negocio formen una única transacción.

#### Scenario: Escrituras de dos repositorios en una transacción
- **WHEN** dentro de un bloque de UoW de módulo dos repositorios escriben y luego se lanza una excepción
- **THEN** ninguna de las dos escrituras es visible desde otra sesión
