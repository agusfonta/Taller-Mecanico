# Spec Delta — grupos-de-rutas

## Purpose

Define cómo se organizan las rutas de la API en dos grupos: uno abierto, sin control de acceso, y uno protegido, cuyo control se aplica una sola vez a todas sus rutas, de modo que ninguna ruta protegida pueda quedar accidentalmente sin control (DD-07).

## ADDED Requirements

### Requirement: Dos grupos de rutas
La aplicación SHALL montar sus rutas en exactamente dos grupos: abierto y protegido. Toda ruta de negocio MUST pertenecer a uno de los dos. El grupo protegido MUST aplicar su control de acceso una única vez a nivel de grupo, de modo que toda ruta agregada a él quede controlada sin declararlo ruta por ruta; el grupo abierto MUST NOT aplicar ese control.

#### Scenario: Ruta abierta sin control
- **WHEN** se llama a una ruta del grupo abierto sin sesión
- **THEN** la ruta responde normalmente sin pasar por el control del grupo protegido

#### Scenario: Ruta protegida controlada sin declararlo
- **WHEN** se agrega al grupo protegido una ruta que no declara ningún control propio y se la llama
- **THEN** el control del grupo protegido se ejecuta antes que la ruta, exactamente una vez

### Requirement: Grupo protegido cerrado hasta tener autenticación
Mientras la autenticación no esté implementada, el control del grupo protegido MUST rechazar toda petición con 401 y un mensaje propio, sin ejecutar la ruta. Ninguna ruta del grupo protegido SHALL ser accesible sin control en ningún momento del desarrollo.

#### Scenario: Petición a ruta protegida antes de C-05
- **WHEN** se llama a una ruta del grupo protegido
- **THEN** la respuesta es 401, el cuerpo no contiene trazas y la ruta no se ejecuta
