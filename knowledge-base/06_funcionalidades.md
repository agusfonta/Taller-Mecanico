# Funcionalidades

Organizadas por **épica** y **historia de usuario** (US-NNN). Los endpoints, roles y códigos provienen de la tabla "Endpoints de referencia" del PDF (págs. 15–17, leída como imagen). Toda ruta del grupo protegido responde además **401** sin sesión y **403** con el cambio de contraseña pendiente.

## Tabla completa de endpoints

| Grupo | Método | Ruta | Quién | Códigos |
|---|---|---|---|---|
| Abierto | GET | `/health/live` | Cualquiera | 200 |
| Abierto | GET | `/health/ready` | Cualquiera | 200, 503 |
| Abierto | POST | `/auth/registro` | Cualquiera | 201, 409, 422 |
| Abierto | POST | `/auth/login` | Cualquiera | 200, 401, 422, 429 |
| Abierto | POST | `/auth/logout` | Cualquiera | 200 |
| Abierto | GET | `/auth/yo` | Autenticado | 200, 401 |
| Abierto | POST | `/auth/cambiar-password` | Autenticado | 200, 401, 422 |
| Protegido | POST | `/usuarios` (alta de personal, contraseña provisoria) | ADMIN | 201, 409, 422 |
| Protegido | GET | `/usuarios/{id}/roles` | ADMIN | 200, 404 |
| Protegido | POST | `/usuarios/{id}/roles` | ADMIN | 201, 404, 409, 422 |
| Protegido | DELETE | `/usuarios/{id}/roles/{rol}` | ADMIN | 200, 404, 409 |
| Protegido | GET | `/eventos` (`page`, `size`) | ADMIN | 200, 422 |
| Protegido | POST | `/clientes` | RECEPCION, ADMIN | 201, 409, 422 |
| Protegido | GET | `/clientes/{id}` (con sus vehículos) | RECEPCION, ADMIN | 200, 404 |
| Protegido | POST | `/clientes/{id}/vehiculos` | RECEPCION, ADMIN | 201, 404, 409, 422 |
| Protegido | DELETE | `/vehiculos/{id}` | RECEPCION, ADMIN | 204, 404, 409 |
| Protegido | GET | `/mis-vehiculos` | Autenticado | 200 |
| Protegido | GET | `/repuestos` (`q`, `page`, `size`) | ADMIN, RECEPCION, MECANICO | 200, 422 |
| Protegido | GET | `/repuestos/{id}` | ADMIN, RECEPCION, MECANICO | 200, 404 |
| Protegido | POST | `/repuestos` (con `stock_inicial`) | ADMIN | 201, 409, 422 |
| Protegido | PATCH | `/repuestos/{id}` (descripción y precio) | ADMIN | 200, 404, 422 |
| Protegido | DELETE | `/repuestos/{id}` | ADMIN | 204, 404 |
| Protegido | POST | `/repuestos/{id}/reponer` | ADMIN | 200, 404, 422 |
| Protegido | GET | `/repuestos/{id}/movimientos` | ADMIN | 200, 404 |
| Protegido | GET | `/repuestos/{id}/precios` (historial de precios) | ADMIN | 200, 404 |
| Protegido | POST | `/ordenes` | RECEPCION, ADMIN | 201, 409, 422 |
| Protegido | GET | `/ordenes` (`estado`, `page`, `size`) | ADMIN, RECEPCION, MECANICO | 200, 422 |
| Protegido | GET | `/ordenes/{id}` | El personal, o el dueño del vehículo | 200, 403, 404 |
| Protegido | POST | `/ordenes/{id}/iniciar` | MECANICO | 200, 404, 409 |
| Protegido | POST | `/ordenes/{id}/terminar` | El mecánico asignado, o ADMIN | 200, 403, 404, 409 |
| Protegido | POST | `/ordenes/{id}/cancelar` | RECEPCION, ADMIN o el dueño | 200, 403, 404, 409 |
| Protegido | GET | `/estados-orden` (catálogo, por posición) | Autenticado | 200 |
| Protegido | GET | `/mis-ordenes` (`page`, `size`) | Autenticado | 200, 422 |

## Épica 1: Plataforma y salud

### US-001 — Vivir y estar listo
**Como** operador **quiero** `/health/live` (sin tocar la base) y `/health/ready` (ejecuta `SELECT 1`, 503 si la base no contesta) **para** distinguir proceso vivo de proceso listo (reiniciar no arregla una base caída).
- [ ] `live` no toca la base. - [ ] `ready` responde 503 si la base cae.
**Reglas**: —

### US-002 — Configuración segura
**Como** desarrollador **quiero** `Settings` desde entorno/`.env` sin secretos por defecto **para** que la app no arranque si faltan clave de firma o contraseña de base.
- [ ] URL de base con `@computed_field`. - [ ] Pool y costo de bcrypt configurables. - [ ] `env.example` sin secretos.

## Épica 2: Autenticación

### US-010 — Registro de cliente
**Como** visitante **quiero** registrarme **para** consultar mis vehículos.
- [ ] Crea usuario + rol CLIENTE + ficha de cliente en un solo UoW (201). - [ ] Correo o documento repetido → 409 con mensaje propio, sin filas sueltas. - [ ] Documento de un cliente existente → 409 (no se apropia de la ficha). - [ ] `extra="forbid"`: no se puede registrar con un rol.
**Reglas**: RN-01, RN-02

### US-011 — Login
**Como** usuario **quiero** iniciar sesión **para** operar.
- [ ] Orden: límite de intentos (429 + `Retry-After`, sin hash) → verificación (contra hash ficticio si el correo no existe). - [ ] Mismo mensaje y tiempo parecido exista o no el correo. - [ ] Cookie `access_token` HttpOnly, SameSite=Lax, Max-Age, Secure configurable; el cuerpo **no** trae token (`mensaje`, `debe_cambiar_password`, `expira_en_segundos`). - [ ] Cada intento se anota en `intento_acceso` en sesión y transacción propias.
**Reglas**: RN-08, RN-09

### US-012 — Sesión: yo, logout, cambio de contraseña
- [ ] `GET /auth/yo` devuelve usuario, roles vigentes y roles del token. - [ ] `logout` borra la cookie. - [ ] `cambiar-password` invalida sesiones anteriores (iat sin truncar) y devuelve cookie nueva válida; contraseña ≤ 72 bytes.
**Reglas**: RN-06, RN-07

## Épica 3: Usuarios, roles y seguridad

### US-020 — Alta de personal
**Como** ADMIN **quiero** crear personal con contraseña provisoria **para** que cambie la clave al primer ingreso (`debe_cambiar_password`).
### US-021 — Asignar / revocar roles
**Como** ADMIN **quiero** asignar roles con vencimiento opcional y revocarlos sin borrar la fila.
- [ ] Vencimiento sin zona o en el pasado → 422. - [ ] Duplicado abierto → 409. - [ ] Revocar un rol corta el permiso en la petición siguiente. - [ ] Admin no se revoca su ADMIN ni deja al sistema sin admins (409).
**Reglas**: RN-03, RN-04, RN-05
### US-022 — Historial de seguridad
**Como** ADMIN **quiero** `GET /eventos` paginado **para** ver altas, cambios de rol y de contraseña y la carga inicial (actor `SISTEMA`).

## Épica 4: Clientes y vehículos

### US-030 — Alta de cliente y vehículo
**Como** recepción **quiero** crear clientes y sus vehículos (`POST /clientes`, `/clientes/{id}/vehiculos`). Documento repetido y patente vigente repetida → 409.
### US-031 — Consulta
`GET /clientes/{id}` devuelve el cliente con sus vehículos (precarga, sin N+1). `GET /mis-vehiculos` para el cliente.
### US-032 — Baja de vehículo
`DELETE /vehiculos/{id}` → 204 (borrado lógico). Con órdenes abiertas → 409. La misma patente puede registrarse luego para otro cliente.
**Reglas**: RN-01, RN-16, RN-17

## Épica 5: Repuestos y stock

### US-040 — Catálogo de repuestos
**Como** ADMIN **quiero** crear (con `stock_inicial`), editar descripción/precio y dar de baja repuestos. Listado con búsqueda `q` por descripción (parámetros ligados), paginado.
- [ ] PATCH de stock → 422 (`extra="forbid"`). - [ ] Código vigente repetido → 409.
### US-041 — Reponer stock
`POST /repuestos/{id}/reponer` → movimiento positivo; único punto de escritura de stock.
### US-042 — Trazabilidad
`GET /repuestos/{id}/movimientos` y `/precios`. Cambiar precio deja una línea (anterior/nuevo); PATCH sin cambio de precio no deja ninguna; la recepción recibe 403.
**Reglas**: RN-14, RN-15, RN-16, RN-20

## Épica 6: Órdenes de trabajo

### US-050 — Abrir orden
**Como** recepción **quiero** `POST /ordenes` con `vehiculo_id`, `falla` e `items` (`repuesto_id`, `cantidad`) **para** registrar el ingreso.
- [ ] Nace PENDIENTE, ≥ 1 ítem, sin repuestos repetidos. - [ ] Precio copiado del repuesto; total calculado en el servidor; precio/total/estado/fecha **no** viajan en el cuerpo. - [ ] Repuesto inexistente o dado de baja → 409 y la orden no queda. - [ ] Catálogo vacío → 409. - [ ] Respuesta con ítems, subtotal e historial (primera línea).
**Reglas**: RN-10, RN-16, RN-19
### US-051 — Iniciar
Mecánico: PENDIENTE → EN_REPARACION y queda asignado. **Reglas**: RN-11
### US-052 — Terminar
Mecánico asignado o ADMIN: EN_REPARACION → TERMINADA; descuenta stock, un movimiento por ítem y línea de historial, todo atómico; si no alcanza → 409 sin cambios. Al confirmarse, `BackgroundTasks` agenda el aviso al cliente. **Reglas**: RN-11, RN-13, RN-14
### US-053 — Cancelar
Recepción, ADMIN o dueño: PENDIENTE → CANCELADA. Ajena → 403; terminada → 409 (403 antes que 409). **Reglas**: RN-12
### US-054 — Consultar
`GET /ordenes` (filtro `estado` declarado en el contrato; otro → 422), `GET /ordenes/{id}` (personal o dueño; ajena 403), `GET /mis-ordenes`, `GET /estados-orden`. El detalle se resuelve con número **fijo** de consultas.
**Reglas**: RN-17, RN-19
