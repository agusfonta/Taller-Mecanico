# Spec Delta — repositorios

## Purpose

Define el acceso a datos por entidad: un repositorio genérico que lee y escribe sin confirmar nunca la transacción, y un repositorio con borrado lógico que oculta por defecto las filas dadas de baja (`borrado_en` no nulo) sin eliminarlas.

## ADDED Requirements

### Requirement: Los repositorios nunca confirman
Las operaciones de escritura de un repositorio (alta, modificación, eliminación) MUST enviar los cambios a la base dentro de la transacción en curso y MUST NOT confirmarla. La confirmación es responsabilidad exclusiva de la Unit of Work.

#### Scenario: Alta visible en la transacción, invisible fuera
- **WHEN** un repositorio agrega una fila y todavía no se confirmó la transacción
- **THEN** la fila tiene identificador asignado y es visible en la misma sesión, pero no desde otra sesión independiente

#### Scenario: Reversión descarta lo escrito
- **WHEN** un repositorio agrega o modifica una fila y luego la transacción se revierte
- **THEN** la base queda como estaba antes de la escritura

### Requirement: Operaciones genéricas de lectura y escritura
El repositorio genérico SHALL ofrecer, para la entidad con la que se construye: buscar por identificador (sin resultado si no existe), listar con desplazamiento y límite en un orden estable por identificador, contar, agregar, modificar sólo los campos indicados y eliminar. Modificar un campo que la entidad no tiene MUST rechazarse sin escribir nada. Toda consulta MUST usar parámetros ligados.

#### Scenario: Buscar inexistente
- **WHEN** se busca por un identificador que no existe
- **THEN** el resultado es vacío y no se lanza error

#### Scenario: Listado paginado estable
- **WHEN** hay 5 filas y se listan con desplazamiento 2 y límite 2
- **THEN** se devuelven la tercera y la cuarta fila en orden de identificador, y el conteo devuelve 5

#### Scenario: Modificación parcial
- **WHEN** se modifica una fila indicando sólo uno de sus campos
- **THEN** cambia sólo ese campo y los demás conservan su valor

#### Scenario: Campo desconocido
- **WHEN** se intenta modificar un campo que la entidad no tiene
- **THEN** la operación se rechaza con error y ningún campo cambia

### Requirement: Borrado lógico filtrado por defecto
Para entidades con borrado lógico, el repositorio MUST excluir de la búsqueda por identificador, del listado y del conteo las filas con `borrado_en` no nulo. Dar de baja SHALL registrar el instante de la baja en `borrado_en` sin eliminar la fila y sin confirmar la transacción. El repositorio SHALL ofrecer además una búsqueda por identificador que incluya las filas dadas de baja.

#### Scenario: Baja oculta la fila
- **WHEN** se da de baja una fila
- **THEN** la búsqueda por identificador no la encuentra, el listado no la incluye y el conteo la descuenta

#### Scenario: Búsqueda incluyendo dados de baja
- **WHEN** se busca por identificador una fila dada de baja con la búsqueda que incluye bajas
- **THEN** se obtiene la fila con `borrado_en` no nulo

#### Scenario: La baja no elimina la fila
- **WHEN** se da de baja una fila y se confirma la transacción
- **THEN** la fila sigue existiendo en la tabla con `borrado_en` igual al instante de la baja (con zona horaria)

#### Scenario: Baja sin confirmar
- **WHEN** se da de baja una fila y la transacción se revierte
- **THEN** la fila vuelve a aparecer en búsquedas, listados y conteos
