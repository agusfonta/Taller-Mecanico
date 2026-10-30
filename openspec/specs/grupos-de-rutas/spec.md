# grupos-de-rutas Specification

## Purpose

Define cómo se organizan las rutas de la API en dos grupos: uno abierto, sin control de acceso, y uno protegido, cuyo control se aplica una sola vez a todas sus rutas, de modo que ninguna ruta protegida pueda quedar accidentalmente sin control (DD-07).

## Requirements

### Requirement: Dos grupos de rutas
La aplicación SHALL montar sus rutas en exactamente dos grupos: abierto y protegido. Toda ruta de negocio MUST pertenecer a uno de los dos. El grupo protegido MUST aplicar su control de acceso una única vez a nivel de grupo, de modo que toda ruta agregada a él quede controlada sin declararlo ruta por ruta; el grupo abierto MUST NOT aplicar ese control.

#### Scenario: Ruta abierta sin control
- **WHEN** se llama a una ruta del grupo abierto sin sesión
- **THEN** la ruta responde normalmente sin pasar por el control del grupo protegido

#### Scenario: Ruta protegida controlada sin declararlo
- **WHEN** se agrega al grupo protegido una ruta que no declara ningún control propio y se la llama
- **THEN** el control del grupo protegido se ejecuta antes que la ruta, exactamente una vez

### Requirement: Control de acceso del grupo protegido
El control del grupo protegido MUST, en este orden: responder 401 con un mensaje propio si no hay un usuario actual válido (sin cookie, token inválido o vencido, usuario inexistente o inactivo, o sesión anterior al último cambio de contraseña); responder 403 con un mensaje propio si el usuario tiene el cambio de contraseña pendiente; y en otro caso dejar pasar la petición a la ruta. En ningún caso de rechazo MUST ejecutarse la ruta ni contener la respuesta trazas. Las rutas de autenticación (`/auth/*`) y de salud (`/health/*`) MUST pertenecer al grupo abierto. El usuario actual MUST resolverse una sola vez por petición aunque la ruta además exija roles.

#### Scenario: Petición protegida sin sesión
- **WHEN** se llama a una ruta del grupo protegido sin cookie
- **THEN** la respuesta es 401 con el mensaje "Se requiere iniciar sesión", sin trazas, y la ruta no se ejecuta

#### Scenario: Petición protegida con sesión válida
- **WHEN** un usuario autenticado sin cambio pendiente llama a una ruta del grupo protegido que no exige roles
- **THEN** la ruta se ejecuta exactamente una vez

#### Scenario: Petición protegida con cambio pendiente
- **WHEN** un usuario autenticado con cambio de contraseña pendiente llama a una ruta del grupo protegido
- **THEN** la respuesta es 403 y la ruta no se ejecuta

#### Scenario: Usuario resuelto una vez
- **WHEN** una ruta protegida que exige un rol es llamada con sesión válida
- **THEN** el usuario se busca en la base una sola vez en esa petición
