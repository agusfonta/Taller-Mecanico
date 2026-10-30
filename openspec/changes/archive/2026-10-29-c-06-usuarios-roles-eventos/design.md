# Design — C-06 `usuarios-roles-eventos`

> ⚠️ **Governance CRITICO** (CHANGES.md §C-06): este diseño define quién administra el acceso a toda la API (alta de personal, roles, autoprotección del administrador, historial de seguridad). **Requiere aprobación humana explícita antes de `/opsx:apply`.** Ningún agente debe escribir código de este change sin ese visto bueno. Puntos que piden revisión explícita: D2 (rol inicial restringido a personal), D3 (reasignación de rol vencido), D4 (semántica de revocación y 404 al repetir), D5 (autoprotección y bloqueo de filas), D6 (textos de eventos), D7 (orden y forma de `GET /eventos`) y los supuestos SU-C06-*.

## Context

- Motivación y alcance: `proposal.md`. Requisitos observables: `specs/{alta-personal,roles-usuario,historial-seguridad}/spec.md`.
- Estado tras C-05 (observado en el código):
  - `app/core/dependencies.py`: `UsuarioActual` inmutable (`id`, `email`, `nombre`, `debe_cambiar_password`, `roles_vigentes: frozenset[Rol]`, `roles_token`), `get_usuario_actual` (roles vigentes de la base **en cada petición**), `exigir_acceso` montado una vez en el grupo protegido (403 cambio pendiente), `requiere_rol(*roles)` (403 "No tiene permiso para esta operación"), `ContrasenasDep`, `SettingsDep`. **La revocación ya corta el permiso en la petición siguiente**: no hace falta nada nuevo en `core` para RN-04.
  - `app/core/security.py`: `PasswordNueva` (mín. 8 caracteres, máx. 72 bytes, sin nulo), `ServicioContrasenas.hashear` (`to_thread` + semáforo).
  - `app/core/paginacion.py`: `PaginacionDep`, `verificar_pagina`, `Pagina[T].crear`, 422 propio de página fuera de rango ya registrado en `crear_app`.
  - `app/core/errores.py`: `restriccion_violada(exc)` (nombre de la restricción desde asyncpg).
  - `app/modules/usuarios/`: `models.py` (`Rol` StrEnum; `AsignacionRol` con índice único parcial **`uq_asignacion_rol_abierta`** `(usuario_id, rol) WHERE revocada_en IS NULL`; `desde` con `default_factory=now(UTC)`; `otorgada_por` FK nula a `usuario`; `EventoSeguridad(actor, accion)`), `repository.py` (`UsuarioRepository.get_by_email`, `AsignacionRolRepository.roles_vigentes`, `EventoSeguridadRepository` sin métodos), `unit_of_work.py` (`UsuariosUoW` con `usuarios`, `asignaciones`, `clientes`, `eventos`, `intentos`; `UsuariosUoWDep`), `service.py` (`registrar_cliente`, `iniciar_sesion`, `cambiar_password`, jerarquía `ConflictoError` → `CorreoYaRegistradoError`; reloj `ahora()`; textos `"Registro de cliente"`, `"Cambio de contraseña"`, actor = correo), `schemas.py` (`_Entrada` con `extra="forbid"`, `EmailNormalizado`, `TextoNoVacio`), `router.py` (`router_auth`; su docstring ya anuncia `router_usuarios` en el mismo archivo).
  - `main.py`: `app = crear_app(abiertos=[router_health, router_auth])` — todavía **sin** routers protegidos.
  - Tests: `test/integration/conftest.py` ofrece `esquema_auth` (esquema `c05_auth_*` migrado una vez por sesión), `settings_auth` (bcrypt 4 rondas), `motor_auth` (TRUNCATE de las 13 tablas al terminar cada test), `db_auth` (`crear_usuario(email, password, roles, activo, debe_cambiar_password)`, `asignar_rol(usuario_id, rol, vence_en, revocada_en)`, `contar`, `conteos`, `filas`, `ejecutar`), `app_auth` (app como el lifespan; protegidos = sólo un router de prueba), `fabrica_http` / `http`. Los tests de C-05 definen sus ayudantes de login por archivo y generan contraseñas aleatorias (`secrets`), nunca literales.
- Restricciones: reglas duras de `CLAUDE.md`; KB 03 §Modelo de roles, KB 05 RN-03/04/05 y reglas de contrato, KB 06 Épica 3, KB 04 §`asignacion_rol`/§`evento_seguridad`, DD-01, DD-06, DD-14, DD-16, SU-06; casos C-06, C-07, C-08 de KB 11.

### Discrepancias detectadas con `CHANGES.md` / KB

1. **Eventos de cambio de contraseña**: CHANGES.md §C-06 dice "Eventos de seguridad en altas, cambios de rol y de contraseña", pero C-05 ya escribe "Registro de cliente" y "Cambio de contraseña" (C-05 design, discrepancia 1). C-06 agrega sólo alta de personal, asignación y revocación, y expone `GET /eventos`.
2. **Códigos de `GET /usuarios/{id}/roles`**: la tabla de endpoints (KB 06) lista 200/404, **sin 422**, a diferencia de todos los listados paginados (que listan 422). Se interpreta que **no es paginado**: el historial de roles de un usuario está acotado (≤ 4 roles × pocas reasignaciones). Ver D8 y SU-C06-4.
3. **422 implícitos**: `DELETE /usuarios/{id}/roles/{rol}` lista 200/404/409; un `id` no entero o un `rol` fuera del vocabulario en la ruta da 422 por contrato (caso C-01, RN-18). Igual que IN-03, 401/403 del grupo protegido son implícitos en todas las rutas.
4. **"Reasignar un rol vencido cierra la fila anterior"** (KB 03): el modelo no tiene una columna "cerrada"; la única forma de cerrar una asignación abierta es escribir `revocada_en`. Se usa esa columna (D3), y el historial distingue "cerrada por reasignación" de "revocada" porque en la primera `revocada_en > vence_en` y hay una fila posterior del mismo rol.
5. **RN-05, segunda mitad** ("el sistema nunca queda sin administradores"): como el actor siempre es un ADMIN vigente y no puede revocarse a sí mismo, en una ejecución secuencial siempre queda al menos él. La guarda sólo se dispara en **concurrencia** (dos admins revocándose mutuamente) o si el actor perdió ADMIN entre su chequeo de permisos y la transacción. Por eso se implementa con bloqueo de filas (D5), no sólo con un conteo.
6. **`POST /usuarios` y rol `CLIENTE`**: la KB lo llama "alta de personal" y un CLIENTE sin ficha de `cliente` no tendría `/mis-*` útiles; se restringe el rol inicial a `ADMIN`/`RECEPCION`/`MECANICO` (D2, SU-C06-1). El endpoint de roles sí admite los cuatro (SU-C06-2).

## Goals / Non-Goals

**Goals:**
- Reutilizar sin duplicar lo de C-05: `requiere_rol`, `UsuarioActual`, `PasswordNueva`, `EmailNormalizado`, `ServicioContrasenas`, `restriccion_violada`, `UsuariosUoW`, paginación.
- Toda escritura administrativa y su evento en **un solo** bloque `async with uow`; hash antes de abrirlo.
- Unicidad de asignaciones garantizada por la base (`uq_asignacion_rol_abierta`), traducida a 409 sin texto de la base.
- RN-05 correcta también bajo concurrencia.
- No tocar `app/core/*`; cambios en archivos compartidos limitados a una línea cada uno.

**Non-Goals:**
- Baja/desactivación o edición de usuarios, cambio de `vence_en` de una asignación existente, reseteo de contraseña por un admin (no están en la KB).
- Filtros en `GET /eventos` (por actor, acción o fecha) y columnas nuevas en `evento_seguridad` (usuario afectado, IP).
- Invalidar tokens al revocar (innecesario: DD-01 decide con la base en cada petición).
- Impedir que el paso del tiempo deje el sistema sin admins (todas las asignaciones ADMIN vencidas): ver Riesgos.
- `seed.py` y el evento `SISTEMA` (C-11); archivos `.http` (C-12).

## Decisions

### D1 — Routers y permisos: dos `APIRouter` con `requiere_rol(ADMIN)` a nivel de router
```python
# app/modules/usuarios/router.py (mismo archivo que router_auth, como anunció C-05)
_solo_admin = [Depends(requiere_rol(Rol.ADMIN))]
router_usuarios = APIRouter(prefix="/usuarios", tags=["usuarios"], dependencies=_solo_admin)
router_eventos  = APIRouter(prefix="/eventos",  tags=["eventos"],  dependencies=_solo_admin)
```
- Ambos van al **grupo protegido** (`exigir_acceso` montado una vez). Orden resultante: 401 sin sesión → 403 cambio pendiente → 403 sin ADMIN → validación de ruta/cuerpo (422) → handler. FastAPI resuelve las dependencias antes de validar los parámetros, así que un no-ADMIN con cuerpo inválido recibe **403** (no 422) y nunca se calcula un hash. Se cubre con un test.
- Los handlers que necesitan al actor lo piden con `UsuarioActualDep` (FastAPI cachea la dependencia: el usuario se resuelve una sola vez por petición, requisito vigente de `grupos-de-rutas`).
- **Alternativas**: `requiere_rol` por ruta → repetido 5 veces y fácil de olvidar en una ruta nueva; un único router `/` con ambos prefijos → mezcla dos recursos; un módulo `eventos/` aparte → la estructura obligatoria (KB 08) no lo tiene y `evento_seguridad` es un modelo de `usuarios`.

### D2 — Alta de personal: un bloque, rol inicial de personal, cambio obligatorio
Contrato:
```python
RolPersonal = Literal[Rol.ADMIN, Rol.RECEPCION, Rol.MECANICO]   # CLIENTE → 422
class AltaPersonalEntrada(_Entrada):              # extra="forbid"
    email: EmailNormalizado; nombre: TextoNoVacio; password: PasswordNueva; rol: RolPersonal
class UsuarioCreadoRespuesta(BaseModel):
    id: int; email: str; nombre: str; debe_cambiar_password: bool; roles: list[str]
```
Servicio `dar_alta_personal(uow, contrasenas, actor: UsuarioActual, datos) -> Usuario`:
1. `hash_ = await contrasenas.hashear(datos.password)` **antes** del bloque (DD-06).
2. `async with uow:` → `usuarios.add(Usuario(email, nombre, password_hash=hash_, activo=True, debe_cambiar_password=True))` → `_abrir_asignacion(uow, usuario, datos.rol, vence_en=None, actor)` (D3, compartida con `POST /roles`, como pide DD-14) → evento (D6).
3. `IntegrityError` → `restriccion_violada`: `uq_usuario_email` → `CorreoYaRegistradoError` (reutilizado de C-05, mismo mensaje); otro → `ConflictoError`. El router traduce a 409.
- 201 sin cookie (no altera la sesión del admin). `debe_cambiar_password=true` hace que el nuevo usuario quede bloqueado por `exigir_acceso` hasta cambiarla (RN-06, Flujo 4) — no hay código nuevo para eso.
- **Alternativas**: rol inicial opcional → descartado por DD-14 (el usuario nunca queda sin rol); permitir `CLIENTE` → un cliente sin ficha (`cliente.usuario_id`) rompe la expectativa de `/mis-*` y el auto-registro ya cubre a los clientes (SU-C06-1); contraseña provisoria generada por el servidor y devuelta en el cuerpo → la KB fija `password` en el cuerpo (DD-14) y devolver secretos en respuestas está prohibido por el espíritu de RN/`contrasenas`.

### D3 — Asignación de rol: vencimiento validado en el contrato; reasignar un vencido cierra la fila
Contrato:
```python
def _futuro(v: datetime) -> datetime:        # AwareDatetime ya rechaza la fecha sin zona
    if v <= datetime.now(UTC): raise ValueError("El vencimiento debe ser una fecha futura")
    return v
class AsignarRolEntrada(_Entrada):           # extra="forbid"
    rol: Rol
    vence_en: Annotated[AwareDatetime, AfterValidator(_futuro)] | None = None
class AsignacionRespuesta(BaseModel):
    id: int; usuario_id: int; rol: str; desde: datetime; vence_en: datetime | None
    revocada_en: datetime | None; otorgada_por: int | None; vigente: bool
```
- **422 en el contrato, no en el servicio**: "sin zona" y "pasado" son incumplimientos del contrato (KB 03: "si no, **422** (no 409)"). `AwareDatetime` de Pydantic rechaza la fecha ingenua; el validador compara con `datetime.now(UTC)` en el instante de la validación (la diferencia con el reloj del servicio es de microsegundos e irrelevante para "futuro").
- Servicio `asignar_rol(uow, actor, usuario_id, datos) -> AsignacionRol`, un único bloque:
  1. `usuarios.get_by_id(usuario_id)` → `None` → `UsuarioNoEncontradoError` (404). El 404 se decide **antes** que el 409.
  2. `_abrir_asignacion(uow, usuario, rol, vence_en, actor)`:
     - `abierta = asignaciones.abierta(usuario.id, rol)` (`revocada_en IS NULL`; a lo sumo una por el índice).
     - Si `abierta` y vigente (`vence_en` nulo o > `ahora()`) → `RolYaAsignadoError` (409 "El usuario ya tiene ese rol asignado").
     - Si `abierta` y vencida → `asignaciones.update(abierta, {"revocada_en": ahora()})` (flush inmediato: la fila sale del índice parcial **antes** del INSERT).
     - `asignaciones.add(AsignacionRol(usuario_id, rol, vence_en, otorgada_por=actor.id))`.
  3. Evento (D6). Respuesta 201 con la asignación nueva.
- **Unicidad por la base**: la lectura previa sólo distingue "vigente → 409" de "vencida → cerrar"; si dos asignaciones del mismo rol corren a la vez, ambas ven "no hay" y la segunda falla en `uq_asignacion_rol_abierta` → `IntegrityError` → `RolYaAsignadoError` (409). En la reasignación concurrente de un vencido, la segunda espera el bloqueo de fila del UPDATE y luego choca con el índice → 409. No se necesita `FOR UPDATE`.
- **Alternativas**: validar "futuro" en el servicio → mezcla 422 de contrato con reglas de dominio y obliga a un error de dominio extra; reabrir la fila vencida (UPDATE `vence_en`) → pierde el historial de "quién tuvo qué y hasta cuándo", contra KB 03; dejar la vencida abierta y rechazar con 409 → contradice "reasignar un rol vencido cierra la fila anterior y abre una nueva"; `ON CONFLICT DO NOTHING` → ocultaría el 409 que pide RN-03.

### D4 — Revocación: escribe `revocada_en`, 404 al repetir, efecto en la petición siguiente
Servicio `revocar_rol(uow, actor, usuario_id, rol) -> AsignacionRol`, un único bloque:
1. `usuarios.get_by_id` → 404 `UsuarioNoEncontradoError` ("Usuario no encontrado").
2. Si `rol == ADMIN`: guardas de D5 (antes de buscar la asignación, porque bloquean filas).
3. `abierta = asignaciones.abierta(usuario_id, rol)` → `None` → `AsignacionNoEncontradaError` (404 "El usuario no tiene ese rol asignado").
4. `asignaciones.update(abierta, {"revocada_en": ahora()})`; evento (D6); 200 con la asignación (`vigente=false`).
- **Abierta pero vencida**: se revoca igual (200). Deja explícito en el historial que un admin la cerró; negarla con 404 confundiría ("figura abierta y no puedo cerrarla").
- **Idempotencia**: el **estado** es idempotente (revocar dos veces deja lo mismo), pero la respuesta no: la segunda revocación da **404** (no hay asignación abierta). Es lo que permite la tabla (200/404/409) y evita un evento duplicado sin efecto. SU-C06-5.
- **Sesiones vivas**: no se toca ningún token. `get_usuario_actual` relee los roles vigentes en cada petición (DD-01), así que la siguiente petición con la misma cookie ya da 403; `GET /auth/yo` muestra la diferencia entre `roles_vigentes` (base) y `roles_token`. Revocar el último rol de un usuario lo deja autenticado pero sin permisos (403 en todo lo que exige rol; `/auth/*` sigue).
- **Alternativas**: `DELETE` físico de la fila → prohibido (KB 03: "la fila no se borra nunca"); 200 idempotente al repetir → registraría eventos vacíos o mentiría sobre lo que pasó; lista negra de tokens → innecesaria con DD-01.

### D5 — Autoprotección del administrador (RN-05) con bloqueo de filas
Para `rol == ADMIN`, dentro del mismo bloque y **antes** de escribir:
1. `if usuario_id == actor.id: raise AutoRevocacionAdminError` → 409 "No puede revocarse su propio rol ADMIN".
2. `admins = await asignaciones.bloquear_admins_vigentes(ahora())` →
   ```sql
   SELECT a.usuario_id FROM asignacion_rol a JOIN usuario u ON u.id = a.usuario_id
   WHERE a.rol = 'ADMIN' AND a.revocada_en IS NULL AND (a.vence_en IS NULL OR a.vence_en > :ahora)
     AND u.activo
   ORDER BY a.id FOR UPDATE OF a
   ```
   (SQLAlchemy `with_for_update(of=AsignacionRol)`, parámetros ligados).
3. `if not (set(admins) - {usuario_id}): raise UltimoAdminError` → 409 "El sistema debe conservar al menos un administrador".
- **Por qué el bloqueo**: con dos ADMIN (A y B) revocándose mutuamente a la vez, un conteo sin bloqueo ve 2 en ambas transacciones y ambas revocan → cero admins. Con `FOR UPDATE` sobre las filas ADMIN abiertas, la segunda transacción espera; al liberarse, PostgreSQL (READ COMMITTED) reevalúa el `WHERE` sobre la versión confirmada, la fila revocada ya no califica, el conjunto queda `{A}` y, al excluir al objetivo A, queda vacío → 409. `ORDER BY a.id` da un orden de bloqueo único y evita interbloqueos entre dos revocaciones.
- Cuentan sólo usuarios **activos** (un ADMIN inactivo no puede iniciar sesión: no administra nada). SU-C06-6.
- **Alternativas**: `pg_advisory_xact_lock(const)` → también serializa, pero es un mecanismo implícito y global ajeno al modelo; `SERIALIZABLE` sólo para esta operación → exige reintentos ante fallos de serialización; un CHECK/disparador en la base → la regla depende del actor y del tiempo (vencimientos), no se expresa bien como restricción; confiar sólo en el conteo → falla en el caso concurrente descrito.

### D6 — Textos de `evento_seguridad`
Convención heredada de C-05: `actor` = correo del usuario que actúa (texto, no FK), `accion` = frase en español. `evento_seguridad` no tiene columna de "usuario afectado", así que el objetivo va en el texto:

| Acción | `actor` | `accion` |
|---|---|---|
| Alta de personal | correo del ADMIN | `Alta de personal: {email} con rol {ROL}` |
| Asignación sin vencimiento | correo del ADMIN | `Asignación de rol {ROL} a {email}` |
| Asignación con vencimiento | correo del ADMIN | `Asignación de rol {ROL} a {email} hasta {vence_en ISO 8601 UTC}` |
| Revocación | correo del ADMIN | `Revocación de rol {ROL} a {email}` |
| (C-05) Registro / cambio | correo del usuario | `Registro de cliente` / `Cambio de contraseña` |
| (C-11) Carga inicial | `SISTEMA` | `Carga de los datos iniciales` |

- La reasignación de un vencido deja **un** evento de asignación (el cierre de la fila vieja es parte de la misma acción). El alta de personal deja **un** evento (no uno de alta y otro de asignación). Nunca contraseñas ni hashes.
- Constantes/funciones de formato en `service.py` junto a `ACCION_REGISTRO`/`ACCION_CAMBIO_PASSWORD`.
- **Alternativas**: columnas nuevas (`usuario_afectado_id`, `detalle` JSON) → migración aditiva fuera del alcance de la KB y del TP; actor = id del admin → inconsistente con C-05 y con `SISTEMA` (texto).

### D7 — `GET /eventos`: paginado, más reciente primero, sin filtros
```python
@router_eventos.get("")
async def listar_eventos(uow: UsuariosUoWDep, params: PaginacionDep) -> Pagina[EventoRespuesta]
# servicio: async with uow: total = eventos.count(); verificar_pagina(params, total);
#           items = eventos.listar_recientes(offset, limit)  → ORDER BY cuando DESC, id DESC
```
- Reutiliza exactamente el patrón de `app/core/paginacion.py` (422 de `page`/`size` por `Query`, 422 propio de página fuera de rango por el manejador ya registrado). `count` y la lista en el **mismo** bloque (misma instantánea de lectura no garantizada en READ COMMITTED, aceptable para un historial).
- `EventoSeguridadRepository.listar_recientes(*, offset, limit)` (el `list` genérico ordena por id ascendente, que no es lo que se quiere leer en un historial). Orden estable con desempate por `id`.
- Sin filtros: la KB sólo define `page`/`size` (KB 06). Filtros por actor/acción quedan como mejora (Non-Goals).
- **Visibilidad**: sólo ADMIN ve eventos, y los ve **todos** (incluidos los de otros admins y los de registro de clientes). No hay vista "mis eventos" para otros roles.
- **Alternativas**: orden ascendente (por id) → el más reciente quedaría en la última página; paginación por cursor → la KB fija `{items,total,page,size,pages}`.

### D8 — `GET /usuarios/{id}/roles`: historial completo, no paginado
```python
class RolesUsuarioRespuesta(BaseModel):
    usuario_id: int; email: str; roles_vigentes: list[str]; asignaciones: list[AsignacionRespuesta]
```
- `asignaciones.historial(usuario_id)` → todas las filas del usuario `ORDER BY desde, id`; `vigente` y `roles_vigentes` se calculan con el mismo `ahora()` (coherentes entre sí). Una consulta para el usuario (404) y una para el historial; sin relaciones (sin carga perezosa).
- No paginado (discrepancia 2): sin `page`/`size` no existe el 422 que la tabla no lista.
- **Alternativa**: envoltorio paginado → agregaría un 422 que la KB no menciona para un conjunto que nunca pasa de unas pocas filas.

### D9 — Mapa de errores y mensajes
Errores de dominio nuevos en `service.py` (el router traduce; nunca `str(exc)` de la base):

| Situación | Excepción | Código | `detail` |
|---|---|---|---|
| Usuario de la ruta inexistente | `UsuarioNoEncontradoError` | 404 | "Usuario no encontrado" |
| Sin asignación abierta de ese rol | `AsignacionNoEncontradaError` | 404 | "El usuario no tiene ese rol asignado" |
| Correo repetido en alta | `CorreoYaRegistradoError` (C-05) | 409 | "El correo ya está registrado" |
| Rol abierto y vigente / choque en `uq_asignacion_rol_abierta` | `RolYaAsignadoError(ConflictoError)` | 409 | "El usuario ya tiene ese rol asignado" |
| Admin se revoca su ADMIN | `AutoRevocacionAdminError(ConflictoError)` | 409 | "No puede revocarse su propio rol ADMIN" |
| Quedaría sin admins vigentes | `UltimoAdminError(ConflictoError)` | 409 | "El sistema debe conservar al menos un administrador" |
| Vencimiento sin zona / pasado, rol inválido, campo extra, contraseña fuera de política, `id`/`rol` de ruta inválidos | (contrato) | 422 | validación de FastAPI |
| Página fuera de rango | `PaginaFueraDeRangoError` (core) | 422 | "La página solicitada no existe" |

- Los 404 heredan de una base `NoEncontradoError` (con `mensaje`), espejo de `ConflictoError`; el router tiene un único `except` por familia.
- Precedencia: 401 → 403 (cambio) → 403 (rol) → 422 (ruta/cuerpo) → 404 (usuario) → 409 → 2xx.

### D10 — Organización y archivos

| Archivo | Cambio |
|---|---|
| `app/modules/usuarios/schemas.py` | `AltaPersonalEntrada`, `UsuarioCreadoRespuesta`, `AsignarRolEntrada`, `AsignacionRespuesta`, `RolesUsuarioRespuesta`, `EventoRespuesta` |
| `app/modules/usuarios/repository.py` | `AsignacionRolRepository.abierta`, `.historial`, `.bloquear_admins_vigentes`; `EventoSeguridadRepository.listar_recientes` (todo con parámetros ligados, sólo `flush`) |
| `app/modules/usuarios/service.py` | `dar_alta_personal`, `asignar_rol`, `revocar_rol`, `roles_de_usuario`, `listar_eventos`, `_abrir_asignacion`, textos de eventos, errores de D9 |
| `app/modules/usuarios/router.py` | `router_usuarios` (4 rutas), `router_eventos` (1 ruta), traducción de errores |
| `app/modules/usuarios/unit_of_work.py` | sin cambios (ya compone los repos necesarios) |
| `app/core/*` | **sin cambios** |

### D11 — Archivos compartidos con C-07 / C-08 (secuenciación del apply)
C-06, C-07 y C-08 se proponen en paralelo y los tres registran routers protegidos. Para que el apply pueda hacerse en cualquier orden con conflictos triviales:

| Archivo compartido | Qué toca C-06 | Regla de convivencia |
|---|---|---|
| `main.py` | `app = crear_app(abiertos=[router_health, router_auth], protegidos=[router_usuarios, router_eventos])` + su `import` | Cada change **agrega** sus routers a la lista `protegidos` y su línea de `import`; nadie reordena ni reescribe la llamada. Si otro change ya creó la lista, se agrega al final. |
| `test/integration/conftest.py` (`app_auth`) | `protegidos=[protegido, router_usuarios, router_eventos]` (import local en la fixture) | Mismo criterio: sólo se agregan routers a la lista; no se cambia la firma de `app_auth` ni los ayudantes de `AyudantesAuth`. Los ayudantes propios de C-06 (login, encabezado de cookie) van en un módulo nuevo `test/integration/sesiones.py`, no en `conftest.py`. |
| `app/modules/usuarios/unit_of_work.py` | ninguno | C-07 puede extender `ClienteRepository` (que `UsuariosUoW` importa) sin afectar a C-06. |
| `app/core/*` | ninguno | — |

- Se recomienda aplicar C-06 **antes** que C-07/C-08 si se aplican en serie (es el que más ejercita `requiere_rol` y deja el patrón de registro de routers protegidos), pero no es obligatorio.

### D12 — Estrategia de pruebas (Strict TDD, PostgreSQL real)
- **Unitarios** (`test/unit/test_schemas_usuarios.py`): `AltaPersonalEntrada` (`rol` ausente / `CLIENTE` / `JEFE` → error; campo extra → error; correo normalizado; contraseña de 7 caracteres o 74 bytes → error); `AsignarRolEntrada` (sin `vence_en` OK; `vence_en` ingenuo → error; pasado con zona → error; futuro con `-03:00` OK; campo extra → error); textos de eventos (funciones de formato puras, incluido el vencimiento en ISO UTC).
- **Integración** (`test/integration/test_usuarios_*.py`, `test_eventos.py`), reutilizando `esquema_auth`, `motor_auth`, `db_auth`, `fabrica_http`/`http` y `app_auth` con los routers reales (D11). Sesiones: usuarios sembrados con `db_auth.crear_usuario(..., roles=("ADMIN",))` y login real por `POST /auth/login`; contraseñas aleatorias con `secrets` (nunca literales). Ayudantes en `test/integration/sesiones.py`.
  - Alta: 201 + filas + `otorgada_por` + evento; login del creado → `debe_cambiar_password` y 403 en ruta protegida; 409 sin filas sueltas y sin texto de la base; 422 varios con espía de `hashear` (0 llamadas); 403 no-ADMIN con cuerpo inválido; atomicidad forzando un fallo en `eventos.add`.
  - Roles: C-07 completo (revocación con la misma cookie → 403, `/auth/yo` con la diferencia, fila revocada presente, vencimiento pasado/sin zona → 422); C-08 (auto-revocación → 409); 409 de rol vigente; reasignación de vencido (fila vieja cerrada + nueva abierta); 404 usuario inexistente y revocación repetida; historial con vigentes/vencidas/revocadas.
  - Concurrencia (real, con dos clientes HTTP y `asyncio.gather`): dos asignaciones iguales → {201, 409}; dos admins revocándose mutuamente → {200, 409} y exactamente un ADMIN vigente. Si la carrera no se da de forma confiable por el transporte en proceso, se fuerza la intercalación con dos conexiones directas al repositorio (`bloquear_admins_vigentes` en dos transacciones) y se verifica que la segunda espera y luego ve un solo admin.
  - Eventos: orden descendente, paginación (`page=2&size=2`), 422 de `size=500`/`page=0`/página más allá, 403 a no-ADMIN; sin evento en peticiones rechazadas.
- La limpieza por `TRUNCATE` de `motor_auth` deja cada test independiente.

## Risks / Trade-offs

- [**Todas las asignaciones ADMIN pueden vencer con el tiempo** y dejar el sistema sin admins] → RN-05 sólo se puede garantizar sobre acciones, no sobre el reloj. Mitigación: el seed (C-11) crea los ADMIN **sin** vencimiento; documentarlo en el README de C-12. Una guarda extra ("no asignar ADMIN con vencimiento si sería el último sin vencer") se descarta por complejidad.
- [**Bloqueo de filas ADMIN** serializa las revocaciones de ADMIN] → operación rara y breve; las demás revocaciones y todas las lecturas no se bloquean (`FOR UPDATE OF asignacion_rol` no bloquea `SELECT` simples).
- [**Carrera entre `requiere_rol` y la transacción**: el actor puede perder ADMIN entre la verificación de permisos y la revocación] → la guarda de D5 no exige que el actor siga siendo admin; el peor caso es una acción administrativa que empezó con permiso válido milisegundos antes (aceptado, DD-11).
- [**`revocada_en` con doble significado** (revocación manual vs. cierre por reasignación)] → distinguible por `revocada_en > vence_en` y por el evento de asignación asociado; agregar una columna "motivo" sería aditivo pero fuera de alcance.
- [**Historial de roles sin paginar**] → acotado por diseño (≤ 4 roles); si creciera, agregar paginación sería un cambio de contrato (se anota).
- [**Validación de "futuro" en el contrato** depende del reloj del proceso] → mismo reloj que usa el resto de la app (C-05: reloj único de la app).
- [**Enumeración de cuentas por `POST /usuarios`** (409 revela correos)] → sólo para ADMIN autenticado; aceptado.
- [**Conflictos de merge en `main.py` y `conftest.py`** con C-07/C-08] → reglas de convivencia de D11 (sólo se agregan elementos a listas).
- [**`evento_seguridad.accion` como texto libre**] → no consultable por usuario afectado; los textos son estables (D6) para que los tests y el `.http` de C-12 los verifiquen.

## Supuestos (requieren visto bueno)

- **SU-C06-1**: `POST /usuarios` sólo acepta roles de personal (`ADMIN`, `RECEPCION`, `MECANICO`); `CLIENTE` → 422 (los clientes se auto-registran con su ficha).
- **SU-C06-2**: `POST /usuarios/{id}/roles` acepta los cuatro roles, incluido `CLIENTE`, y se puede asignar roles a usuarios inactivos o al propio admin.
- **SU-C06-3**: respuestas — alta: `{id, email, nombre, debe_cambiar_password, roles}`; asignación/revocación: `{id, usuario_id, rol, desde, vence_en, revocada_en, otorgada_por, vigente}`; historial: `{usuario_id, email, roles_vigentes, asignaciones}`; eventos: `Pagina[{id, cuando, actor, accion}]`.
- **SU-C06-4**: `GET /usuarios/{id}/roles` no es paginado y devuelve vigentes, vencidas y revocadas, ordenadas por `desde`, `id`.
- **SU-C06-5**: revocar un rol sin asignación abierta (nunca asignado o ya revocado) → 404; revocar una asignación abierta pero vencida → 200 (la cierra).
- **SU-C06-6**: "administradores vigentes" = usuarios **activos** con ADMIN no revocado y no vencido.
- **SU-C06-7**: textos de eventos de D6; `actor` = correo del admin; un único evento por acción (también en reasignación y en alta).
- **SU-C06-8**: `GET /eventos` ordena por `cuando DESC, id DESC`, sin filtros; sólo ADMIN y ve todos los eventos.
- **SU-C06-9**: `vence_en` sólo exige zona horaria y ser posterior al instante de la petición (sin mínimo ni máximo); se guarda tal cual en `timestamptz`.
- **SU-C06-10**: en `POST /usuarios/{id}/roles` y `DELETE`, el 404 del usuario se decide antes que cualquier 409; con `rol=ADMIN`, el 409 de auto-revocación se decide antes que el 404 de asignación inexistente.

## Migration Plan

Sin migraciones de esquema ni datos (usa `uq_asignacion_rol_abierta` de C-03). Despliegue: registrar `router_usuarios` y `router_eventos` en el grupo protegido. Mientras no exista el seed (C-11), el primer ADMIN sólo puede crearse por SQL; los tests lo siembran con `db_auth`. Rollback: quitar los dos routers de `main.py` y de `app_auth`, y los agregados del módulo `usuarios`; no quedan datos inconsistentes (las filas creadas son válidas para C-05).

## Open Questions

- Ninguna bloqueante. Pendiente de **aprobación humana** (governance CRITICO) de D2–D7 y de los supuestos SU-C06-1..10.
