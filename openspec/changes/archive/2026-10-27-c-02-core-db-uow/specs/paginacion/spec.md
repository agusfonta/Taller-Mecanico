# Spec Delta — paginacion

## Purpose

Define el contrato común de todos los listados de la API: parámetros `page` y `size`, el envoltorio `{items, total, page, size, pages}`, el cálculo de la cantidad de páginas y el rechazo de páginas inexistentes con 422.

## ADDED Requirements

### Requirement: Parámetros de paginación
Todo listado SHALL aceptar `page` (entero desde 1, por defecto 1) y `size` (entero entre 1 y 100, por defecto 20). Un valor fuera de esos rangos o no entero MUST responderse con 422 y nunca con 500.

#### Scenario: Valores por defecto
- **WHEN** se pide un listado sin `page` ni `size`
- **THEN** se usa `page=1` y `size=20`

#### Scenario: Tamaño fuera de rango
- **WHEN** se pide un listado con `size=0` o `size=101` o `size=500`
- **THEN** la respuesta es 422

#### Scenario: Página inválida
- **WHEN** se pide un listado con `page=0` o `page=abc`
- **THEN** la respuesta es 422

### Requirement: Envoltorio de listados
Todo listado SHALL responder con un objeto con exactamente los campos `items` (los elementos de la página), `total` (cantidad de elementos que cumplen los mismos filtros, sin paginar), `page`, `size` y `pages`. `pages` MUST ser el techo de `total / size`, con un mínimo de 1.

#### Scenario: Cálculo de páginas
- **WHEN** hay 45 elementos y `size=20`
- **THEN** `total` es 45 y `pages` es 3; la página 3 contiene 5 elementos

#### Scenario: Cero resultados
- **WHEN** ningún elemento cumple los filtros y se pide `page=1`
- **THEN** la respuesta es 200 con `items` vacío, `total` 0 y `pages` 1

#### Scenario: Total exacto múltiplo del tamaño
- **WHEN** hay 40 elementos y `size=20`
- **THEN** `pages` es 2

### Requirement: Página más allá de la última
Pedir una página mayor que `pages` MUST responderse con 422 y un mensaje propio de la aplicación, sin texto interno de la base ni traza.

#### Scenario: Página inexistente con resultados
- **WHEN** hay 1 elemento, `size=1` y se pide `page=2`
- **THEN** la respuesta es 422 con un mensaje propio

#### Scenario: Página inexistente sin resultados
- **WHEN** no hay elementos y se pide `page=2`
- **THEN** la respuesta es 422
