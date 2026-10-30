# Actores y Roles

## Actores del sistema

| Actor | Rol en base | Descripción | Cómo interactúa |
|---|---|---|---|
| Visitante | — | Persona sin sesión | Se registra (`/auth/registro`), inicia sesión, consulta salud |
| Cliente | `CLIENTE` | Dueño de vehículos; se registra solo en la web | Ve sus vehículos y órdenes (`/mis-*`), puede cancelar su orden pendiente |
| Recepción | `RECEPCION` | Atiende el ingreso | Alta de clientes/vehículos, abre y cancela órdenes, consulta repuestos |
| Mecánico | `MECANICO` | Repara | Inicia y termina órdenes asignadas, consulta repuestos y órdenes |
| Administrador | `ADMIN` | Gestiona catálogo, stock, personal y roles | Todo lo anterior + usuarios, roles, repuestos, eventos de seguridad |
| Sistema | — (texto `SISTEMA`) | Actor no-usuario del historial de seguridad | Firma la carga de datos iniciales; **es un texto, no un usuario** |

Un usuario puede tener **varios roles vigentes** a la vez (`asignacion_rol`). `usuario` **no tiene columna `rol`**.

## Modelo de roles (RN-03, RN-04)

- Rol vigente = fila de `asignacion_rol` **no revocada** (`revocada_en IS NULL`) y **sin vencer** (`vence_en` nulo o futuro).
- Revocar escribe `revocada_en`; **la fila no se borra nunca** (historial de quién tuvo qué rol).
- A lo sumo **una asignación abierta por (usuario, rol)** — índice único parcial; 409 si se repite.
- Reasignar un rol vencido cierra la fila anterior y abre una nueva.
- `vence_en` debe llegar **con zona horaria y en el futuro**; si no, **422** (no 409).
- Los permisos se deciden con los roles de la base **en cada petición**; los roles del token son **informativos**. Revocar un rol quita el permiso a una sesión ya abierta.
- Autoprotección (RN-05): un admin no puede revocarse su propio `ADMIN` y el sistema nunca queda sin administradores vigentes (409).

## RBAC — Matriz de permisos

`A`=ADMIN, `R`=RECEPCION, `M`=MECANICO, `Auth`=cualquier autenticado, `Dueño`=dueño del vehículo de la orden. Todo el grupo protegido responde además 401 sin sesión y 403 con cambio de contraseña pendiente.

| Recurso / acción | A | R | M | CLIENTE | Notas |
|---|---|---|---|---|---|
| `POST /usuarios` (alta de personal, contraseña provisoria) | ✅ | | | | |
| `GET/POST /usuarios/{id}/roles`, `DELETE …/roles/{rol}` | ✅ | | | | |
| `GET /eventos` (historial de seguridad) | ✅ | | | | paginado |
| `POST /clientes`, `GET /clientes/{id}`, `POST /clientes/{id}/vehiculos`, `DELETE /vehiculos/{id}` | ✅ | ✅ | | | |
| `GET /mis-vehiculos`, `GET /mis-ordenes`, `GET /estados-orden` | ✅ | ✅ | ✅ | ✅ | cualquier autenticado |
| `GET /repuestos`, `GET /repuestos/{id}` | ✅ | ✅ | ✅ | | |
| `POST/PATCH/DELETE /repuestos…`, `reponer`, `movimientos`, `precios` | ✅ | | | | sólo ADMIN |
| `POST /ordenes` | ✅ | ✅ | | | |
| `GET /ordenes` (lista, filtro `estado`) | ✅ | ✅ | ✅ | | |
| `GET /ordenes/{id}` | ✅ | ✅ | ✅ | Dueño | el personal o el dueño; ajena → 403 |
| `POST /ordenes/{id}/iniciar` | | | ✅ | | el mecánico queda asignado |
| `POST /ordenes/{id}/terminar` | ✅ | | asignado | | el mecánico asignado o ADMIN |
| `POST /ordenes/{id}/cancelar` | ✅ | ✅ | | Dueño | **sin `requiere_rol`**: decide el servicio |

> **Cancelar no lleva `requiere_rol`**: el dueño no tiene rol de personal. El servicio decide primero quién es y qué relación tiene con la orden (**403**) y recién después si el estado lo permite (**409**).

## Rutas públicas (grupo abierto)

| Ruta | Quién |
|---|---|
| `GET /health/live`, `GET /health/ready` | Cualquiera |
| `POST /auth/registro`, `POST /auth/login`, `POST /auth/logout` | Cualquiera |
| `GET /auth/yo`, `POST /auth/cambiar-password` | Autenticado (aunque tenga el cambio de contraseña pendiente) |

Con el cambio de contraseña obligatorio pendiente, el usuario **sólo puede usar `/auth/*` y las rutas de salud** (RN-06): todo lo demás responde 403.

## Usuarios semilla

Ver [04](04_modelo_de_datos.md) — Seed data inicial.
