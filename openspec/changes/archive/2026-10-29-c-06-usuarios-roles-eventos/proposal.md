# Proposal — C-06 `usuarios-roles-eventos`

## Why

Tras C-05 la API autentica y autoriza (`get_usuario_actual`, `exigir_acceso`, `requiere_rol` con roles vigentes de la base), pero **nadie puede administrar el acceso**: no hay forma de dar de alta personal (recepción, mecánicos, otros administradores), de asignar o revocar roles ni de consultar el historial de seguridad. Sin esto, el único camino para tener personal es tocar la base a mano, y quedan sin demostrar los casos C-06, C-07 y C-08 del TP (403 sin rol, revocación con la sesión abierta, vencimientos inválidos, autoprotección del admin) que concentran buena parte del Ej. 5 (Autorización, 14 pts). Es el siguiente eslabón del camino crítico hacia C-12 y no depende de C-07/C-08.

## What Changes

- **`POST /usuarios`** (ADMIN; 201/409/422): alta de personal con cuerpo `{email, nombre, password, rol}` (DD-14, rol inicial **obligatorio**). Crea en **un solo** bloque de UoW el `usuario` (activo, **`debe_cambiar_password=true`**, contraseña provisoria hasheada **antes** de abrir la transacción), su `asignacion_rol` abierta con `otorgada_por` = id del admin, y una línea de `evento_seguridad`. Correo normalizado como en C-05; correo repetido → 409 sin filas sueltas.
- **`GET /usuarios/{id}/roles`** (ADMIN; 200/404): historial completo de asignaciones del usuario (vigentes, vencidas y revocadas) y sus roles vigentes.
- **`POST /usuarios/{id}/roles`** (ADMIN; 201/404/409/422): cuerpo `{rol, vence_en?}`; `vence_en` **con zona horaria y en el futuro** o 422; asignación abierta y vigente del mismo rol → 409 (RN-03, índice único parcial); si la asignación abierta está **vencida**, se cierra (`revocada_en`) y se abre una nueva en la misma transacción. Evento de seguridad en la misma transacción.
- **`DELETE /usuarios/{id}/roles/{rol}`** (ADMIN; 200/404/409): escribe `revocada_en` (la fila **no se borra**); un admin no puede revocarse su propio ADMIN y el sistema **nunca queda sin administradores vigentes** (409, RN-05), con bloqueo de filas para que dos revocaciones cruzadas concurrentes no dejen el sistema sin admins. La revocación corta el permiso **en la petición siguiente** con la misma cookie (RN-04, ya garantizado por C-05).
- **`GET /eventos`** (ADMIN; 200/422): historial de `evento_seguridad` paginado con el envoltorio común `{items, total, page, size, pages}`, del más reciente al más antiguo.
- **Eventos de seguridad** para alta de personal, asignación y revocación de rol (los de registro y cambio de contraseña ya los escribe C-05), con textos fijados en `design.md`.
- **`main.py`**: registro de `router_usuarios` y `router_eventos` en el **grupo protegido**.
- **Tests** (Strict TDD): unitarios de contratos (`extra="forbid"`, vencimiento con zona y futuro); integración HTTP contra **PostgreSQL real** reutilizando la infraestructura de C-05 (`esquema_auth`, `motor_auth`, `db_auth`, `app_auth`).

## Capabilities

### New Capabilities
- `alta-personal`: alta de usuarios de personal por un ADMIN con rol inicial obligatorio, contraseña provisoria y cambio obligatorio al primer ingreso, atómica y con evento de seguridad.
- `roles-usuario`: consulta del historial de roles de un usuario, asignación con vencimiento opcional (zona y futuro), reasignación de un rol vencido, revocación sin borrado y autoprotección de administradores (RN-03, RN-04, RN-05).
- `historial-seguridad`: registro de eventos de seguridad de las acciones administrativas y su consulta paginada por ADMIN (`GET /eventos`).

### Modified Capabilities
- Ninguna. `autorizacion` ya exige que la revocación y el vencimiento corten el permiso en la petición siguiente; este change lo ejercita con endpoints reales sin cambiar el requisito. `paginacion` se reutiliza tal cual.

## Impact

- **Código nuevo/modificado** (módulo `usuarios`, propiedad de este change): `app/modules/usuarios/schemas.py` (contratos nuevos), `repository.py` (consultas de asignaciones abiertas, historial, bloqueo de admins vigentes, listado de eventos), `service.py` (alta de personal, asignar/revocar rol, listar eventos, errores de dominio), `router.py` (`router_usuarios`, `router_eventos`).
- **Archivos compartidos** (secuenciar con C-07/C-08, ver `design.md` §Archivos compartidos): `main.py` (registro de routers protegidos) y `test/integration/conftest.py` (los routers protegidos reales en `app_auth`). **No** toca `app/core/*`.
- **APIs**: 5 rutas nuevas en el grupo protegido, todas sólo ADMIN.
- **Datos**: sin migraciones; usa `usuario`, `asignacion_rol` y `evento_seguridad` como las dejó C-03 (índice `uq_asignacion_rol_abierta`).
- **Dependencias**: ninguna nueva.
- **Desbloquea**: C-12 (verificación y entrega, casos C-06/C-07/C-08) junto con C-04, C-10 y C-11.
- **Fuera de alcance**: `seed.py`, sus contraseñas y el evento "Carga de los datos iniciales" con actor `SISTEMA` (C-11, DD-15); archivos `.http` (C-12); baja/desactivación de usuarios, edición de usuarios y modificación de `vence_en` de una asignación existente (no figuran en la KB).
- **Governance**: **CRITICO** (CHANGES.md §C-06) — requiere aprobación humana explícita del diseño antes de `/opsx:apply`.
