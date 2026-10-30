# Design — C-05 `auth-registro-login-sesion`

> ⚠️ **Governance CRITICO** (CHANGES.md §C-05): este diseño define autenticación, sesión y autorización de toda la API (Auth/Security). **Requiere aprobación humana explícita antes de `/opsx:apply`.** Ningún agente debe escribir código de este change sin ese visto bueno. Puntos que piden revisión explícita: D2 (claims y algoritmo), D3 (cookie), D5 (usuario actual sin transacción abierta), D7 (límite de intentos y reloj), D8 (registro y 409), D9 (cambio de contraseña e `iat`) y los supuestos SU-C05-*.

## Context

- Estado tras C-01..C-04 (observado en el código):
  - `app/core/config.py`: `jwt_secret_key: SecretStr` (mín. 32, sin default), `jwt_expire_minutes=30` y `jwt_expire_seconds` (`@computed_field`), `bcrypt_rounds=12` (4..31), `bcrypt_max_concurrency=4`, `cookie_secure=False`. `get_settings()` con `lru_cache`.
  - `app/core/dependencies.py`: `exigir_acceso()` lanza 401 "Se requiere iniciar sesión" (gancho que falla cerrado, C-02 D3). `main.crear_app(abiertos, protegidos)` lo monta **una vez** en el grupo protegido; el lifespan deja el punto de extensión "hash ficticio antes del `yield`". `app.state` tiene `engine` y `session_factory` (`expire_on_commit=False`).
  - `app/core/unit_of_work.py`: `UnitOfWork(session)` confirma al salir, revierte ante excepción, no cierra la sesión. `BaseRepository[T]` con `flush()`.
  - `app/modules/usuarios/models.py`: `Rol` (StrEnum), `Usuario` (`email` UNIQUE exacto → restricción `uq_usuario_email`; `activo`, `debe_cambiar_password`, `password_cambiada_en` TIMESTAMPTZ nula), `AsignacionRol` (CHECK de rol, índice único parcial `uq_asignacion_rol_abierta`), `IntentoAcceso` (índice `(email, ip, cuando)`), `EventoSeguridad` (`actor` texto, `accion`). `Cliente` con `uq_cliente_documento` y `uq_cliente_usuario_id`. Relaciones con `lazy="raise"`. C-03 dejó la **normalización del correo a C-05**.
  - Las columnas `cuando`/`desde` usan `server_default now()` **y** `default_factory=datetime.now(UTC)` en Python (el ORM envía el valor de la app).
  - Tests: `test/conftest.py` (`entorno_limpio`, `secretos_validos`), `test/integration/conftest.py` (`settings_db` con skip/`--exigir-db`, `esquema_migrado` por sesión, `conexion_migrada` con transacción externa revertida, helpers `aplicar_migraciones`/`crear_esquema`/`borrar_esquema`). No existe fixture HTTP sobre el esquema migrado. `test/unit/test_grupos_rutas.py` exige 401 `{"detail": "Se requiere iniciar sesión"}` sin cookie **sin lifespan** (sin `app.state.session_factory`).
- Motivación y alcance: `proposal.md`. Requisitos observables: `specs/{contrasenas,token-sesion,registro-clientes,inicio-sesion,sesion-usuario,autorizacion,grupos-de-rutas}/spec.md`.
- Restricciones: reglas duras de `CLAUDE.md`; KB 05 (RN-01, 02, 04, 06–09, reglas de contrato), KB 07 Flujos 1–4 y 10, KB 08 §Seguridad, DD-01, DD-05..DD-08, DD-13, DD-15..DD-17, DD-19, IN-04. PDF Ej. 4/5/7 (orden del login, `iat` sin truncar, intento en transacción propia declarado en un comentario con su costo).

### Discrepancias detectadas con `CHANGES.md` / KB

1. **Eventos de seguridad**: CHANGES.md los pone tanto en C-05 ("altas y cambios de contraseña") como en C-06 ("altas, cambios de rol y de contraseña"). Decisión: C-05 crea `EventoSeguridadRepository` y escribe los eventos de **registro** y **cambio de contraseña**; C-06 reutiliza el repositorio para alta de personal y roles, y expone `GET /eventos`.
2. **Ficha de cliente**: el módulo `clientes/` (repository, service, router) es de C-07, pero el registro (RN-02) inserta un `cliente` en el mismo UoW. C-05 crea `app/modules/clientes/repository.py` con un `ClienteRepository` **mínimo** (hereda `BaseRepository[Cliente]`, sin métodos propios); C-07 lo extiende sin romperlo.
3. **Ubicación del router `/auth`**: la estructura obligatoria (KB 08) no tiene módulo `auth`; los modelos de acceso viven en `usuarios` (PDF). El router `/auth` vive en `app/modules/usuarios/router.py` como `router_auth` (grupo abierto); C-06 agregará en el mismo archivo `router_usuarios` (grupo protegido). Son dos `APIRouter` distintos porque van a grupos distintos.
4. **Flujo 1 paso 5** registra el evento "después" de confirmar; aquí se escribe **dentro** del mismo bloque (D8): un alta sin su evento (o un evento sin alta) sería un historial inconsistente.
5. **`app/core/errores.py`** no figura en el scope: es necesario para traducir `IntegrityError` a 409 por nombre de restricción sin exponer texto de la base (RN-18); se ubica en `core` para que C-06..C-10 no lo dupliquen.
6. KB 03 lista `GET /auth/yo` y `POST /auth/cambiar-password` como "Autenticado" **en el grupo abierto**: exigen usuario actual pero **no** el control de cambio obligatorio (si estuvieran en el grupo protegido, el usuario con cambio pendiente nunca podría cambiarla). Se respeta.

## Goals / Non-Goals

**Goals:**
- Un único punto de verdad para "quién es" (`get_usuario_actual`) y "qué puede" (`requiere_rol` + control del grupo protegido), consultando la base en cada petición.
- Ningún hash con conexión tomada; ningún bcrypt en el bucle; ninguna entrada que termine en 500.
- Piezas reutilizables por C-06 (repos de usuario/rol/evento, `requiere_rol`, servicio de contraseñas) y C-11 (hash del seed).
- Verificación contra PostgreSQL real con el esquema que produce Alembic.

**Non-Goals:**
- Refresh tokens, revocación por lista negra, "cerrar todas las sesiones" explícito, recuperación de contraseña por correo, MFA, CSRF token (SameSite=Lax alcanza para el TP: no hay formularios cross-site ni GET con efectos).
- `POST /usuarios`, gestión de roles, `GET /eventos` (C-06). `seed.py` (C-11). Archivos `.http` (C-12).
- Confiar en `X-Forwarded-For` / proxies (ver SU-C05-4).
- Resolver la carrera del límite de intentos bajo concurrencia (DD-11: concurrencia diferida).

## Decisions

### D1 — `app/core/security.py`: servicio de contraseñas creado en el lifespan
```python
class ServicioContrasenas:
    def __init__(self, rondas: int, max_concurrencia: int) -> None   # crea asyncio.Semaphore
    async def hashear(self, password: str) -> str                    # to_thread(bcrypt.hashpw) bajo semáforo
    async def verificar(self, password: str, hash_: str) -> bool     # to_thread(bcrypt.checkpw) bajo semáforo
def crear_servicio_contrasenas(settings: Settings) -> ServicioContrasenas
```
- Semáforo **por instancia**, creada en el lifespan y guardada en `app.state.contrasenas` (dependencia `get_contrasenas(request)`). Nada de semáforo global de módulo: se crearía al importar, fuera del bucle (EA-08), y entre tests con bucles distintos puede quedar ligado al bucle equivocado. `seed.py` (C-11) construye su propia instancia con `crear_servicio_contrasenas(get_settings())`.
- `verificar` devuelve `False` (y loguea sólo el nombre de la clase) si `checkpw` lanza `ValueError` por un hash corrupto: un dato roto no debe convertirse en 500 ni en un oráculo distinto del 401.
- **Contratos de contraseña** (en el mismo módulo, usados por los schemas): `PasswordIngresada = Annotated[str, Field(min_length=1), AfterValidator(_max_72_bytes_sin_nulo)]` y `PasswordNueva = Annotated[str, Field(min_length=8), AfterValidator(_max_72_bytes_sin_nulo)]`. El validador mide `len(v.encode("utf-8")) <= 72` y rechaza `"\x00"` (bcrypt no lo admite → sería 500). Mensajes propios en español.
- **Alternativas**: `passlib` (sin mantenimiento, choca con bcrypt ≥ 4.1) → descartada; `ThreadPoolExecutor` propio → `to_thread` + semáforo es lo que pide el PDF y acota igual; argon2 → el PDF exige bcrypt.

### D2 — Token: JWT HS256 con `iat` flotante
```python
def emitir_token(usuario_id: int, roles: Sequence[str], settings: Settings, *, ahora: float | None = None) -> str
def decodificar_token(token: str, settings: Settings) -> ClaimsToken   # lanza TokenInvalidoError
```
- Claims: `sub=str(usuario_id)` (PyJWT ≥ 2.10 exige `sub` string), `iat=time.time()` **como número flotante** (no `datetime`: PyJWT convierte `datetime` a entero con `timegm` y truncaría), `exp=iat + jwt_expire_seconds`, `roles=[...]` ordenados.
- Decodificación: `jwt.decode(token, clave, algorithms=["HS256"], options={"require": ["sub", "iat", "exp"]})`, `leeway=0`. La lista fija de algoritmos rechaza `none` y confusión de algoritmos. Cualquier `jwt.PyJWTError`, `sub` no entero o `roles` no lista → `TokenInvalidoError` → 401.
- **Alternativas**: RS256 (par de claves) → innecesario con un único servicio que emite y valida; roles como fuente de permisos → prohibido por DD-01 (sólo informativos). Session server-side en tabla → contradice el PDF (JWT en cookie).

### D3 — Cookie `access_token`
- Helpers en `security.py`: `poner_cookie_sesion(response, token, settings)` → `response.set_cookie("access_token", token, max_age=settings.jwt_expire_seconds, httponly=True, samesite="lax", secure=settings.cookie_secure, path="/")`; `borrar_cookie_sesion(response, settings)` → `delete_cookie` con los **mismos** `path`, `httponly`, `samesite`, `secure` (si difieren, el navegador no la reemplaza).
- Sin `Domain` (cookie de host), sin `Expires` (basta `Max-Age`). El token nunca va en el cuerpo ni se lee de `Authorization` (`get_usuario_actual` usa `request.cookies` como dice el PDF).
- **Alternativas**: `SameSite=Strict` → rompe la navegación desde enlaces externos sin ganar seguridad relevante aquí; el PDF fija Lax. `Secure` siempre → impide probar en `http://localhost`; por eso `COOKIE_SECURE`.

### D4 — Lifespan: servicio de contraseñas y hash ficticio
```python
motor = crear_motor(settings); app.state.engine = motor; app.state.session_factory = ...
app.state.contrasenas = crear_servicio_contrasenas(settings)
app.state.hash_ficticio = await app.state.contrasenas.hashear(secrets.token_urlsafe(32))
```
- Una vez por proceso, con el costo configurado (el mismo que tienen los hashes reales generados por la app) y un valor aleatorio que se descarta. Costo: ~300 ms extra al arrancar con 12 rondas; aceptable.
- Dependencia `get_hash_ficticio(request)`. Si los hashes del seed se generan con otro costo, el tiempo se desalinea: C-11 debe usar `BCRYPT_ROUNDS` (riesgo anotado).
- **Alternativa**: hash ficticio constante en el código → sería un "secreto" fijo y con costo fijo; descartada. Calcularlo perezosamente en el primer login → el primer login de un correo inexistente tardaría el doble (oráculo); descartada.

### D5 — `get_usuario_actual`: token antes que base, lectura sin transacción abierta
```python
@dataclass(frozen=True, slots=True)
class UsuarioActual:
    id: int; email: str; nombre: str; debe_cambiar_password: bool
    roles_vigentes: frozenset[Rol]; roles_token: tuple[str, ...]

async def leer_claims(request: Request, settings: SettingsDep) -> ClaimsToken      # 401 sin cookie / token inválido
async def get_usuario_actual(claims: ClaimsDep, uow: UsuariosUoWDep) -> UsuarioActual
UsuarioActualDep = Annotated[UsuarioActual, Depends(get_usuario_actual)]
```
- **Orden**: `claims` se declara **antes** que `uow`. FastAPI resuelve las subdependencias en orden y corta con la primera excepción: sin cookie o con token inválido se responde 401 **sin pedir sesión ni tocar la base** (y sin `app.state.session_factory`, que es lo que exige `test_grupos_rutas.py`). Se cubre con un test explícito.
- Con el usuario: `async with uow:` → `usuarios.get_by_id(sub)` y `asignaciones.roles_vigentes(usuario_id, ahora)`; al salir, el UoW confirma una transacción de sólo lectura y **devuelve la conexión al pool**: no queda una transacción abierta mientras luego corre bcrypt (cambio de contraseña) o el handler. Se devuelve un `UsuarioActual` inmutable (no la entidad ORM): sin carga perezosa posible, sin `password_hash`, sin riesgo de serializarlo.
- 401 (mensaje único "Se requiere iniciar sesión") si: usuario inexistente; `activo` falso; o `password_cambiada_en is not None and datetime.fromtimestamp(claims.iat, UTC) < password_cambiada_en` (precisión de microsegundos de PostgreSQL; **sin truncar** a segundos, DD-08).
- **Roles vigentes** (repositorio): `SELECT rol FROM asignacion_rol WHERE usuario_id = :id AND revocada_en IS NULL AND (vence_en IS NULL OR vence_en > :ahora)` con `ahora = datetime.now(UTC)` ligado. Son 2 consultas por petición autenticada (DD-01 lo acepta). FastAPI cachea la dependencia por petición: `exigir_acceso`, `requiere_rol` y la ruta comparten la misma resolución (spec: "una sola vez por petición").
- **Alternativas**: abrir una sesión aparte desde `session_factory` → funciona, pero son dos sesiones por petición y el usuario queda en otra sesión; leer en la sesión de la petición sin cerrar la transacción → retendría la conexión ~300 ms durante el hash del cambio (contradice DD-06); devolver la entidad `Usuario` → acopla rutas al ORM y arriesga exponer el hash.

### D6 — `exigir_acceso` y `requiere_rol`
```python
async def exigir_acceso(usuario: UsuarioActualDep) -> UsuarioActual:     # mismo nombre y montaje (C-02)
    if usuario.debe_cambiar_password: raise HTTPException(403, "Debe cambiar la contraseña antes de continuar")
    return usuario
def requiere_rol(*roles: Rol) -> Callable[..., Awaitable[UsuarioActual]]   # 403 "No tiene permiso para esta operación"
```
- `requiere_rol` valida en el momento de declararse que hay ≥ 1 rol y que todos son `Rol` (un typo falla al importar, no en producción). Su dependencia interna depende de `exigir_acceso` (no sólo del usuario), así el 403 por cambio pendiente se evalúa **antes** que el de rol aun si alguien la usara fuera del grupo protegido.
- Orden resultante en el grupo protegido: 401 (sin sesión) → 403 (cambio pendiente) → 403 (rol) → ruta. `cancelar` (DD-09) no usa `requiere_rol`: decide su servicio.
- **Alternativa**: middleware de autenticación → corre para todas las rutas (incluidas las abiertas) y no se integra con la inyección de dependencias ni con `dependency_overrides`; descartada. Control de cambio dentro de `get_usuario_actual` → bloquearía `/auth/yo` y `cambiar-password` (DD-07: FastAPI suma dependencias, no las resta).

### D7 — Login: orden, límite de intentos e `intento_acceso` en transacción propia
Servicio `iniciar_sesion(uow, intentos, contrasenas, hash_ficticio, settings, email, password, ip)`:
1. **Lectura** (`async with uow:`): `intentos.fallos_bloqueantes(email, ip, desde=ahora-60s)`; si hay 5 → `DemasiadosIntentosError(retry_after)` → 429 **sin hash ni anotación**. Si no, `usuarios.get_by_email(email)` y, si existe, sus roles vigentes. El bloque cierra la transacción (D5) antes del hash.
2. **Verificación** (fuera de transacción): `await contrasenas.verificar(password, usuario.password_hash if usuario else hash_ficticio)`; `ok = verificado and usuario is not None and usuario.activo`. Siempre exactamente una verificación (RN-09).
3. **Anotación** en sesión y transacción propias (DD-05): `await registrar_intento(email, ip, ok, cuando=ahora)`.
4. Fallo → `CredencialesInvalidasError` → 401 "Correo o contraseña incorrectos" (cuerpo idéntico en los tres casos). Éxito → `emitir_token(...)`, cookie y cuerpo `{mensaje, debe_cambiar_password, expira_en_segundos}`.
- **Consulta de fallos bloqueantes** (parámetros ligados, usa el índice `(email, ip, cuando)`):
  ```sql
  SELECT cuando FROM intento_acceso
  WHERE email = :email AND ip = :ip AND exito = false AND cuando > :desde
    AND cuando > COALESCE((SELECT max(cuando) FROM intento_acceso
                           WHERE email = :email AND ip = :ip AND exito = true), '-infinity')
  ORDER BY cuando DESC LIMIT 5
  ```
  Con 5 filas: `retry_after = max(1, ceil((fila_5.cuando + 60 s) - ahora))` (cuando el quinto más reciente sale de la ventana, quedan 4 y se puede volver a intentar). Constantes `MAX_FALLOS = 5`, `VENTANA = timedelta(seconds=60)` en el servicio (fijadas por RN-08, no configurables).
- **Reloj único**: `cuando` del intento y `:desde` salen de `datetime.now(UTC)` de la app (función `ahora()` del módulo, sustituible en tests). **Alternativa** `now()` de la base → es la hora de inicio de la transacción y mezclaría dos relojes con el `default_factory` del modelo; descartada.
- **`registrar_intento`**: dependencia `get_registro_intentos(request)` que devuelve un callable sobre `request.app.state.session_factory`: `async with fabrica() as s: async with UnitOfWork(s): await IntentoAccesoRepository(s).add(...)`. Es la **única** escritura fuera de la transacción de su petición; el código lo declara en un comentario con su costo (deja filas aunque la petición falle). El servicio no construye un UoW de la petición: recibe un colaborador ya armado por el router.
- **No se anotan** los 429 (no hubo verificación; anotarlos extendería el bloqueo indefinidamente bajo ataque y escribiría en cada intento bloqueado) ni los 422 (no llegan al servicio). Ver SU-C05-2.
- **IP**: `request.client.host`, o `"desconocida"` si no hay cliente. No se lee `X-Forwarded-For`.
- **Alternativas**: contador en memoria/Redis → no sobrevive reinicios ni varios procesos y el PDF pide contar la tabla; bloqueo por cuenta (sin IP) → permitiría a cualquiera bloquear una cuenta ajena; descartadas.

### D8 — Registro: un solo bloque, 409 por nombre de restricción
Servicio `registrar_cliente(uow, contrasenas, datos)`:
1. `hash_ = await contrasenas.hashear(datos.password)` (antes de abrir la transacción, DD-06).
2. `async with uow:` → `usuarios.add(Usuario(email=..., nombre=..., password_hash=hash_))` (flush → id) → `asignaciones.add(AsignacionRol(usuario_id, rol=Rol.CLIENTE, otorgada_por=None))` (SU-06) → `clientes.add(Cliente(usuario_id, nombre, documento, telefono))` → `eventos.add(EventoSeguridad(actor=email, accion="Registro de cliente"))`. Un único bloque (RN-02).
3. Un `IntegrityError` en cualquier `flush` atraviesa el bloque (el UoW revierte todo) y el servicio lo traduce con `app/core/errores.restriccion_violada(exc) -> str | None` (lee `exc.orig.__cause__.constraint_name` de asyncpg, con `getattr` defensivo): `uq_usuario_email` → `CorreoYaRegistradoError` ("El correo ya está registrado"); `uq_cliente_documento` → `DocumentoYaRegistradoError` ("El documento ya pertenece a un cliente del taller"); otra → `ConflictoError` genérico ("Los datos chocan con un registro existente"). El router traduce las tres a 409. Nunca se devuelve `str(exc)`.
- Sin consulta previa de existencia (la base garantiza la unicidad, KB 05). Si chocan ambos, gana el correo (se inserta primero). La ficha existente con ese documento **no se toca** (RN-02).
- Respuesta 201: `{id, email, nombre, cliente_id, roles: ["CLIENTE"]}`. Sin cookie: el registro no inicia sesión (SU-C05-3).
- **Normalización**: `email: EmailStr` + `AfterValidator(lambda v: v.strip().lower())` en un tipo `EmailNormalizado` compartido por registro y login; `nombre/documento/telefono: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]`. Schemas con `model_config = ConfigDict(extra="forbid")`. **Alternativa** índice único sobre `lower(email)` → aditivo, pero toca la migración de C-03; con la normalización en la entrada alcanza (C-03 Riesgos lo deja abierto).

### D9 — Cambio de contraseña: tres fases, `iat` posterior al cambio
Servicio `cambiar_password(uow, contrasenas, usuario_actual, actual, nueva)`:
1. **Lectura** (`async with uow:`): `usuarios.get_by_id(usuario_actual.id)` → hash vigente.
2. **Fuera de transacción**: `verificar(actual, hash)` → si no coincide, `PasswordActualIncorrectaError` → 401 "La contraseña actual no es correcta"; si coincide, `nuevo_hash = hashear(nueva)`.
3. **Escritura** (`async with uow:`): relee el usuario, `update(usuario, {password_hash, password_cambiada_en: ahora(), debe_cambiar_password: False})`, `eventos.add(actor=email, accion="Cambio de contraseña")`. Al salir confirma.
4. **Después** del commit: `emitir_token(usuario.id, roles_vigentes, settings)` con `iat = time.time()` tomado ahora (posterior a `password_cambiada_en`) → cookie nueva; respuesta `{"mensaje": "Contraseña actualizada"}`.
- Por qué funciona RN-07: un token previo tiene `iat` < `password_cambiada_en` (aun en el mismo segundo, porque la comparación es en microsegundos); el nuevo tiene `iat` ≥ `password_cambiada_en` porque se toma después del commit. Test sin `sleep` entre login y cambio (C-09).
- Dos bloques del mismo UoW en una operación: es la consecuencia directa de DD-06 (no retener la conexión durante dos bcrypt). La escritura de RN-07 sigue siendo un único bloque.
- **Alternativas**: `token_version` entero en `usuario` → requiere columna nueva (C-03 no la tiene y la KB fija la comparación `iat` vs `password_cambiada_en`); descartada.

### D10 — Organización del módulo y quién construye qué
| Archivo | Contenido |
|---|---|
| `app/modules/usuarios/schemas.py` | `RegistroEntrada`, `RegistroRespuesta`, `LoginEntrada`, `LoginRespuesta`, `MensajeRespuesta`, `YoRespuesta`, `CambioPasswordEntrada` (entradas con `extra="forbid"`; ninguna con `password_hash`) |
| `app/modules/usuarios/repository.py` | `UsuarioRepository` (`get_by_email`), `AsignacionRolRepository` (`roles_vigentes`), `IntentoAccesoRepository` (`fallos_bloqueantes`), `EventoSeguridadRepository` |
| `app/modules/usuarios/unit_of_work.py` | `UsuariosUoW(UnitOfWork)`: `usuarios`, `asignaciones`, `clientes`, `eventos`, `intentos` sobre la misma sesión |
| `app/modules/usuarios/service.py` | `registrar_cliente`, `iniciar_sesion`, `cambiar_password` + errores de dominio |
| `app/modules/usuarios/router.py` | `router_auth = APIRouter(prefix="/auth", tags=["auth"])`; dependencia `get_usuarios_uow(session) -> UsuariosUoW`; traducción de errores de dominio a 401/409/429 |
| `app/modules/clientes/repository.py` | `ClienteRepository(BaseRepository[Cliente])` mínimo |
| `app/core/security.py`, `app/core/dependencies.py`, `app/core/errores.py` | D1–D6, D8 |

- El **router** construye el UoW (dependencia) y lo pasa sin abrir; el **servicio** lo abre con `async with` y nunca lo construye; los repositorios sólo hacen `flush()`.
- Todos los handlers son `async def`; nada bloqueante (bcrypt sólo por `ServicioContrasenas`).
- `main.py`: `app = crear_app(abiertos=[router_health, router_auth])`.

### D11 — Mensajes y códigos
| Situación | Código | Cuerpo / cabecera |
|---|---|---|
| Sin sesión válida (todos los casos de D5) | 401 | `{"detail": "Se requiere iniciar sesión"}` |
| Credenciales inválidas en login | 401 | `{"detail": "Correo o contraseña incorrectos"}` |
| Contraseña actual incorrecta | 401 | `{"detail": "La contraseña actual no es correcta"}` |
| Límite de intentos | 429 | `{"detail": "Demasiados intentos fallidos; intente más tarde"}` + `Retry-After: <s>` |
| Cambio pendiente en grupo protegido | 403 | `{"detail": "Debe cambiar la contraseña antes de continuar"}` |
| Rol insuficiente | 403 | `{"detail": "No tiene permiso para esta operación"}` |
| Correo / documento repetido | 409 | mensajes de D8 |
| Login OK | 200 | `{"mensaje": "Sesión iniciada", "debe_cambiar_password": b, "expira_en_segundos": 1800}` |
| Logout | 200 | `{"mensaje": "Sesión cerrada"}` |

### D12 — Estrategia de pruebas (Strict TDD, PostgreSQL real)
- **Unitarios** (`test/unit/`): `test_security.py` (política 72 bytes/nulo/8 caracteres; hash/verify con 4 rondas; semáforo: con tope 2 y 6 verificaciones concurrentes, el máximo simultáneo observado es 2; `verificar` con hash corrupto → `False`; token: `iat` fraccional, `exp`, rechazo de `none`/otra clave/vencido/sin `sub`), `test_dependencies.py` (sin cookie → 401 sin `app.state`; `Authorization: Bearer` ignorado; `requiere_rol` con dobles de `get_usuario_actual`; orden 401 → 403 cambio → 403 rol), `test_schemas_auth.py` (`extra` → 422, normalización del correo), `test_lifespan.py` ampliado (publica `contrasenas` y `hash_ficticio` con el costo configurado).
- **Integración** (`test/integration/test_auth_*.py`), nueva infraestructura en `test/integration/conftest.py`:
  - `esquema_auth` (scope sesión): esquema propio `c05_auth_<hex>` migrado a `head` con Alembic (no comparte `esquema_migrado`, cuyos tests asumen tablas vacías dentro de una transacción revertida).
  - `app_auth` (por test): `crear_app(abiertos=[router_health, router_auth], protegidos=[router_prueba])` con `router_prueba` sólo de test (`/prueba/abierta-autenticada`, `/prueba/admin` con `requiere_rol(Rol.ADMIN)`, contador de ejecuciones); `app.state` armado como el lifespan pero con motor `search_path=esquema_auth` y `crear_servicio_contrasenas(settings con bcrypt_rounds=4)`; override de `get_settings`. Cliente `httpx.AsyncClient(transport=ASGITransport(app, client=(ip, 1234)))` para variar la IP.
  - Limpieza tras cada test: `TRUNCATE` de las 13 tablas `RESTART IDENTITY CASCADE` (los disparadores de sólo agregado son por fila y no frenan `TRUNCATE`). Necesario porque `intento_acceso` se confirma en su propia sesión: una transacción externa revertida no serviría.
  - Ayudantes para sembrar usuarios con roles/`debe_cambiar_password`/inactivos e intentos antiguos (`INSERT` con `cuando` en el pasado) y para inspeccionar filas.
  - Espía de `ServicioContrasenas.verificar`/`hashear` (contador) para RN-08 "sin hash" y RN-09 "una verificación".
  - Tiempo parecido (RN-09): test con `BCRYPT_ROUNDS=10`, 5 muestras por grupo, compara medianas con tolerancia de media verificación; los demás tests usan 4 rondas.
- Reloj: `service.ahora` sustituible con `monkeypatch` para la ventana de 60 s y `Retry-After` determinístico.

## Risks / Trade-offs

- [**Carrera en el límite de intentos**: N logins concurrentes pueden contar 4 y verificar todos] → aceptado (DD-11); el semáforo de bcrypt acota el daño. Un `SELECT ... FOR UPDATE` no aplica (no hay fila que bloquear) y un advisory lock por (email, ip) se deja como mejora.
- [**Bloqueo dirigido**: un atacante desde la misma IP que la víctima (NAT) puede bloquearla 60 s] → aceptado por RN-08; la clave (email, ip) lo limita a quien comparte IP.
- [**Detrás de un proxy** todas las peticiones tendrían la IP del proxy] → no se confía en `X-Forwarded-For` (falsificable); si se despliega detrás de proxy, configurar `--proxy-headers` de uvicorn con IPs de confianza (SU-C05-4).
- [**Enumeración por registro**: el 409 "correo ya registrado" revela cuentas] → lo exige RN-01/C-02 (409 con mensaje propio); el login sí es uniforme. Mitigable a futuro con límite también en registro.
- [**Tiempo del login no idéntico**: el camino con usuario lee roles (1 consulta más)] → diferencia de ~1 ms frente a ~300 ms de bcrypt; el spec pide "parecido". Igualable leyendo roles sólo tras el éxito si hiciera falta.
- [**Costo distinto entre hash ficticio y hashes del seed/antiguos**] → C-11 debe hashear con `BCRYPT_ROUNDS`; subir el costo deja hashes viejos más rápidos (re-hash al login: mejora futura).
- [**`intento_acceso` crece sin límite** (filas que nunca se borran)] → índice `(email, ip, cuando)` mantiene la consulta acotada; purga fuera de alcance.
- [**Escritura del intento perdida si la petición se cancela** a mitad de la anotación] → ventana de milisegundos; no se usa `asyncio.shield` para no ocultar cancelaciones del servidor al apagar.
- [**Contraseña actual por fuerza bruta** vía `cambiar-password` con una sesión robada] → requiere cookie válida; límite específico fuera de alcance (anotado).
- [**Orden de dependencias** como garantía de "401 sin tocar la base"] → test explícito que falla si alguien reordena los parámetros.
- [**Reloj de la app vs. reloj de la base**] → todo lo comparado (intentos, `password_cambiada_en`, `iat`, roles vigentes) usa el reloj de la app; `server_default now()` sólo actúa en inserciones fuera del ORM (seed/psql).
- [**`TRUNCATE` entre tests** sobre un esquema compartido por la sesión] → esquema exclusivo `c05_auth_*`; tests independientes del orden.
- [**Clave JWT filtrada** permitiría forjar tokens] → `SecretStr`, nunca logueada; rotarla invalida todas las sesiones (comportamiento deseado).

## Supuestos (requieren visto bueno)

- **SU-C05-1**: contraseña actual incorrecta en `cambiar-password` → **401** (la tabla de endpoints sólo lista 200/401/422).
- **SU-C05-2**: los 429 y los 422 **no** se anotan en `intento_acceso`; "cada intento" se interpreta como cada intento verificado. Un login correcto reinicia sólo la cuenta del mismo (correo, IP).
- **SU-C05-3**: el registro responde 201 **sin** iniciar sesión (sin cookie); el cuerpo trae `{id, email, nombre, cliente_id, roles}`.
- **SU-C05-4**: la IP es `request.client.host`; no se confía en cabeceras de proxy.
- **SU-C05-5**: un usuario inactivo recibe el mismo 401 que una clave incorrecta (se verifica el hash igual) y su intento cuenta como fallido.
- **SU-C05-6**: textos de `evento_seguridad.accion`: "Registro de cliente" y "Cambio de contraseña"; `actor` = correo del usuario.
- **SU-C05-7**: `GET /auth/yo` responde `{id, email, nombre, debe_cambiar_password, roles_vigentes, roles_token}` (listas ordenadas).
- **SU-C05-8**: no se exige que la contraseña nueva difiera de la actual.

## Migration Plan

Sin migraciones de esquema ni datos. Despliegue: reemplazar `exigir_acceso` y registrar `router_auth`; no hay rutas protegidas de negocio todavía, así que el cambio de "siempre 401" a "control real" no afecta a ningún cliente. Rollback: restaurar `app/core/dependencies.py` y `main.py` de C-04 y borrar los archivos nuevos; el grupo protegido vuelve a fallar cerrado. Rotar `JWT_SECRET_KEY` invalida todas las sesiones emitidas.

## Open Questions

- Ninguna bloqueante. Pendiente de **aprobación humana** (governance CRITICO) de D2, D3, D5, D7, D8, D9 y de los supuestos SU-C05-1..8.
