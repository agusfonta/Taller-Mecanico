# Spec Delta — estados-orden

## Purpose

Expone el catálogo `estado_orden` a cualquier usuario autenticado, ordenado por posición e indicando qué estados son finales, sin permitir editarlo desde la API (RN-19, DD-02, caso C-17).

## ADDED Requirements

### Requirement: Consulta del catálogo de estados
`GET /estados-orden` SHALL pertenecer al grupo protegido y MUST ejecutarse para cualquier usuario autenticado sin cambio de contraseña pendiente (sin sesión → 401; cambio pendiente → 403). MUST responder 200 con la lista de estados del catálogo, cada uno con `codigo`, `descripcion`, `posicion` y `es_final`, ordenada por `posicion` ascendente. Con el catálogo vacío MUST responder 200 con una lista vacía.

#### Scenario: Los cuatro estados por posición
- **WHEN** el catálogo tiene PENDIENTE (1), EN_REPARACION (2), TERMINADA (3, final) y CANCELADA (4, final) y un cliente llama `GET /estados-orden`
- **THEN** la respuesta es 200 con los cuatro en ese orden, con `es_final` verdadero sólo en TERMINADA y CANCELADA

#### Scenario: Catálogo sin sesión
- **WHEN** se llama `GET /estados-orden` sin cookie
- **THEN** la respuesta es 401

#### Scenario: Catálogo vacío
- **WHEN** la tabla `estado_orden` está vacía
- **THEN** la respuesta es 200 con una lista vacía

### Requirement: El catálogo no se edita desde la API
La API MUST NOT exponer ninguna ruta que cree, modifique o borre filas de `estado_orden`; el acceso del código de la aplicación al catálogo MUST ser de sólo lectura. Las filas del catálogo sólo las carga `seed.py`.

#### Scenario: Intento de alta de estado
- **WHEN** un administrador llama `POST /estados-orden`
- **THEN** la respuesta es 405 y la tabla `estado_orden` no cambia
