# Proposal — C-05 `auth-registro-login-sesion`

## Why

Tras C-01..C-04 la API arranca, habla con PostgreSQL y tiene las 13 tablas, pero **nadie puede identificarse**: no hay registro, ni login, ni sesión, y el grupo protegido rechaza todo con un 401 fijo (gancho que falla cerrado de C-02). Sin autenticación no se puede construir ningún módulo protegido (C-06 usuarios/roles, C-07 clientes, C-08 repuestos, C-09/C-10 órdenes) ni el seed (C-11, que necesita el hash). Es el eslabón siguiente del camino crítico y el que más puntaje concentra (Ej. 4 Autenticación 16 pts + buena parte de Ej. 5 Autorización 14 pts y Ej. 7 `intento_acceso`).

## What Changes

- **`app/core/security.py`** (nuevo): hash y verificación bcrypt **siempre** con `asyncio.to_thread` bajo un **semáforo** (`BCRYPT_MAX_CONCURRENCY`) y costo `BCRYPT_ROUNDS`; tipo de contrato de contraseña (**mín. 8 caracteres** al crear, **máx. 72 bytes** en todo campo que termina en bcrypt, DD-16); emisión y verificación de JWT HS256 con `sub`, `iat` **fraccional sin truncar**, `exp` y roles vigentes al emitir; **hash ficticio** calculado una vez en el lifespan (RN-09).
- **`app/core/dependencies.py`**: `get_usuario_actual` (lee **sólo** la cookie `access_token`; 401 si falta, es inválida o venció, el usuario no existe o está inactivo, o `iat` < `password_cambiada_en`), `requiere_rol(...)` (403; roles vigentes **consultados en la base en cada petición**, DD-01/RN-04) y **`exigir_acceso`** reimplementado: usuario actual + control de cambio obligatorio (**403** si `debe_cambiar_password`, RN-06), conservando nombre y punto de montaje únicos del grupo protegido (DD-07). **BREAKING** respecto de C-02: el grupo protegido deja de rechazar todo; ahora admite usuarios autenticados sin cambio pendiente.
- **Módulo `usuarios`** (schemas, repository, unit_of_work, service, router): router **`/auth`** en el **grupo abierto** con:
  - `POST /auth/registro` (201/409/422): `usuario` + `asignacion_rol` CLIENTE + `cliente` (+ línea de `evento_seguridad`) en **un solo** bloque de UoW, hash **antes** de abrir la transacción, correo normalizado a minúsculas, `extra="forbid"`; correo o documento repetido → 409 con mensaje propio y sin filas sueltas (la unicidad la garantiza la base).
  - `POST /auth/login` (200/401/422/429): primero el límite (**5 fallos / 60 s por (correo, IP)** → 429 + `Retry-After` sin calcular hash, RN-08), luego verificación contra el hash real o el ficticio (mismo cuerpo y tiempo parecido, RN-09); cada intento verificado se anota en `intento_acceso` en **sesión y transacción propias** (DD-05); cookie `access_token` HttpOnly, SameSite=Lax, Path=/, Max-Age = duración, Secure según `COOKIE_SECURE`; el cuerpo no trae token.
  - `POST /auth/logout` (200, idempotente, sin sesión requerida, IN-04), `GET /auth/yo` (usuario, roles vigentes de la base y roles del token, DD-19), `POST /auth/cambiar-password` (valida la actual, anota `password_cambiada_en`, invalida las sesiones previas aun del mismo segundo y devuelve cookie nueva válida, RN-07).
- **`app/modules/clientes/repository.py`** (nuevo, mínimo): `ClienteRepository` para el alta atómica del registro; C-07 lo extiende.
- **`app/core/errores.py`** (nuevo): extracción del nombre de la restricción violada de un `IntegrityError` (para traducir a 409 sin exponer texto de la base, RN-18); reutilizable por C-06..C-10.
- **`main.py`**: el lifespan crea el servicio de contraseñas (semáforo) y calcula el hash ficticio antes del `yield`; el router `/auth` se registra en el grupo abierto.
- **Tests** (Strict TDD): unitarios de seguridad/contratos/dependencias y de integración HTTP contra **PostgreSQL real** con el esquema migrado por Alembic; bcrypt con `BCRYPT_ROUNDS=4` en la suite.

## Capabilities

### New Capabilities
- `contrasenas`: política de contraseña (8 caracteres / 72 bytes), hash y verificación bcrypt fuera del bucle bajo semáforo con costo configurable, y hash ficticio calculado en el arranque.
- `token-sesion`: contenido del JWT (`sub`, `iat` fraccional, `exp`, roles), firma y validación, y transporte exclusivo en la cookie `access_token` con sus atributos.
- `registro-clientes`: auto-registro atómico de usuario + rol CLIENTE + ficha de cliente, con normalización del correo, 409 sin filas sueltas y evento de seguridad.
- `inicio-sesion`: login con límite de intentos, anti-enumeración, anotación de `intento_acceso` en transacción propia, emisión de cookie, y logout idempotente.
- `sesion-usuario`: resolución del usuario actual desde la cookie (casos de 401), `GET /auth/yo` y cambio de contraseña con invalidación de sesiones previas.
- `autorizacion`: `requiere_rol` con roles vigentes de la base en cada petición (403) y bloqueo del grupo protegido mientras el cambio de contraseña está pendiente (403).

### Modified Capabilities
- `grupos-de-rutas`: se retira el requisito "Grupo protegido cerrado hasta tener autenticación" (401 incondicional) y se reemplaza por el control real del grupo protegido (401 sin sesión válida, 403 con cambio pendiente, ruta ejecutada en otro caso). Las rutas `/auth/*` quedan en el grupo abierto.

## Impact

- **Código nuevo**: `app/core/security.py`, `app/core/errores.py`, `app/modules/usuarios/{schemas,repository,unit_of_work,service,router}.py`, `app/modules/clientes/repository.py`; tests en `test/unit/` y `test/integration/` (fixture de app HTTP sobre esquema migrado).
- **Código modificado**: `app/core/dependencies.py` (reemplaza el gancho de C-02), `main.py` (lifespan + router `/auth`), `test/unit/test_grupos_rutas.py` (el 401 sin cookie se mantiene; se agrega el caso autenticado), `test/integration/conftest.py` (fixtures nuevas).
- **APIs**: 5 rutas nuevas `/auth/*` en el grupo abierto; el grupo protegido pasa de "siempre 401" a "401/403/ejecuta".
- **Dependencias**: ninguna nueva (`bcrypt`, `PyJWT`, `email-validator` y `httpx` ya vienen con `requirements.txt` / `fastapi[standard]`).
- **Datos**: sin migraciones; usa `usuario`, `asignacion_rol`, `cliente`, `intento_acceso` y `evento_seguridad` tal como las dejó C-03.
- **Desbloquea**: C-06, C-07, C-08 y C-11 (GATE 4).
- **Fuera de alcance**: `POST /usuarios`, roles y `GET /eventos` (C-06); `seed.py` y sus contraseñas (C-11, DD-15); archivos `.http` (C-12).
- **Governance**: **CRITICO** — requiere aprobación humana explícita del diseño antes de `/opsx:apply`.
