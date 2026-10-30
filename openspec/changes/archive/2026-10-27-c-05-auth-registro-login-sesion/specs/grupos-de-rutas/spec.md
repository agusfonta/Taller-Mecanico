# Spec Delta — `grupos-de-rutas`

## ADDED Requirements

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

## REMOVED Requirements

### Requirement: Grupo protegido cerrado hasta tener autenticación
**Reason**: C-05 implementa la autenticación; el gancho de C-02 que rechazaba toda petición con 401 se reemplaza por el control real del grupo protegido (usuario actual + cambio de contraseña pendiente).
**Migration**: El control conserva su nombre y su único punto de montaje en el grupo protegido; las peticiones sin sesión siguen recibiendo 401 con el mismo mensaje. Los tests que sólo verificaban el 401 sin cookie siguen valiendo; los que necesiten una ruta protegida accesible deben iniciar sesión o reemplazar la dependencia de control.
