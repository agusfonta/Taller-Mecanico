# CHANGES — Secuencia de Implementación

> Índice canónico de todos los changes del proyecto Taller Mecánico (API asincrónica FastAPI + PostgreSQL).
> Cada change es atómico: un agente puede implementarlo en una sesión (~4-6 horas).
> **Leer este archivo antes de ejecutar cualquier `/opsx:propose`.**

---

## Cómo usar este documento

1. Identificá el próximo change con `[ ]` cuyas dependencias estén todas en `[x]`.
2. Leé los archivos listados en **Leer antes** (la KB es la fuente de verdad; los nombres de tablas y columnas son obligatorios).
3. Ejecutá `/opsx:propose C-NN-nombre` y luego `/opsx:apply`.
4. Al terminar, `/opsx:archive C-NN-nombre`.
5. Marcá el checkbox del change (`[ ]` → `[x]`) en **Estado**.

---

## Árbol de dependencias

```
C-01 foundation-setup
└── C-02 core-db-uow
    ├── C-03 modelos-y-migraciones
    │   └── C-05 auth-registro-login-sesion
    │       ├── C-06 usuarios-roles-eventos
    │       ├── C-07 clientes-vehiculos ──────┐
    │       ├── C-08 repuestos-stock ─────────┤
    │       │                                 └── C-09 ordenes-alta-consulta
    │       │                                       └── C-10 ordenes-ciclo-de-vida
    │       └── C-11 seed-datos-iniciales (también requiere C-03)
    └── C-04 health-endpoints

C-12 verificacion-y-entrega  ◄── C-04, C-06, C-10, C-11
```

### Paralelismo por fase

```
GATE 0: (inicio)
  → C-01 foundation-setup                      [Agente A]

GATE 1: C-01 ✓
  → C-02 core-db-uow                           [Agente A]

GATE 2: C-02 ✓                                  ← FORK
  → C-03 modelos-y-migraciones                 [Agente A]
  → C-04 health-endpoints                      [Agente B]

GATE 3: C-03 ✓
  → C-05 auth-registro-login-sesion            [Agente A]

GATE 4: C-05 ✓                                  ← FORK
  → C-06 usuarios-roles-eventos                [Agente A]
  → C-07 clientes-vehiculos                    [Agente B]
  → C-08 repuestos-stock                       [Agente C]
  → C-11 seed-datos-iniciales                  [Agente C — tras C-08, o B si queda libre]

GATE 5: C-07 ✓ y C-08 ✓
  → C-09 ordenes-alta-consulta                 [Agente A]

GATE 6: C-09 ✓
  → C-10 ordenes-ciclo-de-vida                 [Agente A]

GATE 7: C-04 ✓, C-06 ✓, C-10 ✓, C-11 ✓
  → C-12 verificacion-y-entrega                [Agente A]
```

### Camino crítico (8 changes — mínimo irreducible)

`C-01 → C-02 → C-03 → C-05 → C-07* / C-08* → C-09 → C-10 → C-12`

(\* C-07 y C-08 son ambos indispensables para C-09; cualquiera de los dos puede ser el último en cerrarse.)

### Plan óptimo con 3 agentes

| Paso | Agente A (Backend Core) | Agente B (Backend Aux) | Agente C (Dominio Inventario) |
|------|-------------------------|------------------------|-------------------------------|
| 1 | C-01 foundation-setup | — | — |
| 2 | C-02 core-db-uow | — | — |
| 3 | C-03 modelos-y-migraciones | C-04 health-endpoints | — |
| 4 | C-05 auth-registro-login-sesion | — | — |
| 5 | C-06 usuarios-roles-eventos | C-07 clientes-vehiculos | C-08 repuestos-stock |
| 6 | C-09 ordenes-alta-consulta | C-11 seed-datos-iniciales | — |
| 7 | C-10 ordenes-ciclo-de-vida | — | — |
| 8 | C-12 verificacion-y-entrega | (apoyo: evidencias) | (apoyo: README) |

---

## FASE 1 — Fundación e infraestructura

### [C-01] `foundation-setup`
- **Estado**: `[x]` completado
- **Scope**:
  - Estructura de directorios obligatoria: `main.py`, `app/core/`, `app/modules/{health,usuarios,clientes,repuestos,ordenes}/`, `migrations/`, `test/`
  - `requirements.txt` (FastAPI, SQLModel/SQLAlchemy async, asyncpg, Alembic, bcrypt, PyJWT, pydantic-settings, uvicorn)
  - `app/core/config.py`: `Settings` con pydantic-settings, `@computed_field` para la URL de base, sin secretos por defecto (la app no arranca sin clave de firma ni contraseña de base); variables `POSTGRES_*`, `SQL_ECHO`, `JWT_SECRET_KEY`, `JWT_EXPIRE_MINUTES`, `BCRYPT_ROUNDS`, `BCRYPT_MAX_CONCURRENCY`, `COOKIE_SECURE`, `DB_POOL_SIZE`, `DB_MAX_OVERFLOW` (nombres según DD-13/DD-17)
  - `env.example` sin secretos; `.env` en `.gitignore`
  - `alembic.ini` sin secretos; PostgreSQL 16 de desarrollo
  - Tests: arranque falla sin `JWT_SECRET_KEY`/`POSTGRES_PASSWORD`; URL de base computada correctamente
- **Dependencias**: ninguna
- **Governance**: BAJO
- **Leer antes**:
  - `knowledge-base/08_arquitectura_propuesta.md` §Estructura de directorios, §Variables de entorno
  - `knowledge-base/06_funcionalidades.md` §US-002
  - `knowledge-base/09_decisiones_y_supuestos.md`
  - `knowledge-base/10_preguntas_abiertas.md`

### [C-02] `core-db-uow`
- **Estado**: `[x]` completado
- **Scope**:
  - `app/core/database.py`: creación de motor y fábrica de sesiones (los llama el lifespan, nunca al importar) + `get_session`; pool configurable
  - `main.py`: lifespan que guarda motor/fábrica en `app.state` y hace `engine.dispose()` al apagar; dos grupos de rutas (abierto / protegido)
  - `app/core/repository.py`: `BaseRepository[T]` (recibe sesión y clase del modelo; `add`/`update` con `flush()`, nunca `commit()`) y `SoftDeleteRepository[T]` (`get_by_id_including_deleted`, `soft_delete`)
  - `app/core/unit_of_work.py`: `UnitOfWork` base como gestor de contexto asincrónico (commit al salir, rollback ante excepción, no cierra la sesión)
  - `app/core/paginacion.py`: envoltorio `{items,total,page,size,pages}`
  - Tests: UoW confirma/revierte; repositorio no hace commit; soft delete filtra dados de baja
- **Dependencias**: `C-01`
- **Governance**: CRITICO
- **Leer antes**:
  - `knowledge-base/08_arquitectura_propuesta.md` §Patrones aplicados, §Reglas de las capas
  - `knowledge-base/07_flujos_principales.md` §Flujo 10
  - `knowledge-base/05_reglas_de_negocio.md` §Reglas transversales

### [C-03] `modelos-y-migraciones`
- **Estado**: `[x]` completado
- **Scope**:
  - Modelos: `Usuario`, `AsignacionRol`, `IntentoAcceso`, `EventoSeguridad`, `Cliente`, `Vehiculo`, `Repuesto`, `MovimientoStock`, `HistorialPrecioRepuesto`, `EstadoOrden`, `OrdenTrabajo`, `ItemOrden`, `HistorialEstadoOrden` con nombres de tabla/columna exactos de la KB
  - Constraints: UNIQUE (`email`, `documento`, `usuario_id` en cliente, `posicion`, `orden_id+repuesto_id`), índices únicos parciales (patente, código de repuesto, asignación de rol abierta), CHECKs (precio, stock, cantidad, anio, total, rol, `precio_nuevo <> precio_anterior`), FK `estado` → `estado_orden.codigo`, índice por cada FK, índice (`email`,`ip`,`cuando`)
  - Navegación declarada en ambos extremos; `Usuario.cliente` devuelve un objeto
  - Migración 1: `--autogenerate`, todas las tablas, catálogo vacío, comentario que lo indique
  - Migración 2: escrita a mano, función + disparador de sólo-agregado sobre `historial_estado_orden`, `movimiento_stock`, `historial_precio_repuesto`
  - Plantilla asincrónica de Alembic; sin `create_all`
  - Tests: `upgrade head` → `downgrade base` → `upgrade head`; UPDATE/DELETE rechazados en las 3 tablas sólo-agregado; cada CHECK/índice parcial dispara su violación
- **Dependencias**: `C-02`
- **Governance**: CRITICO
- **Leer antes**:
  - `knowledge-base/04_modelo_de_datos.md` §Entidades, §Garantías delegadas a la base, §Migraciones
  - `knowledge-base/05_reglas_de_negocio.md` §Integridad e inmutabilidad
  - `knowledge-base/03_actores_y_roles.md` §Modelo de roles
  - `knowledge-base/08_arquitectura_propuesta.md` §Patrones aplicados

### [C-04] `health-endpoints`
- **Estado**: `[x]` completado
- **Scope**:
  - `GET /health/live` (200, no toca la base)
  - `GET /health/ready` (ejecuta `SELECT 1`; 200, 503 si la base no contesta)
  - `app/modules/health/router.py`, montado en el grupo abierto
  - Tests: `live` no abre sesión; `ready` devuelve 503 con base caída
- **Dependencias**: `C-02`
- **Governance**: BAJO
- **Leer antes**:
  - `knowledge-base/06_funcionalidades.md` §US-001
  - `knowledge-base/08_arquitectura_propuesta.md` §Patrones aplicados (lifespan)
  - `knowledge-base/11_casos_de_prueba_y_evaluacion.md`

---

## FASE 2 — Acceso y seguridad

### [C-05] `auth-registro-login-sesion`
- **Estado**: `[x]` completado
- **Scope**:
  - `app/core/security.py`: bcrypt con `to_thread` + semáforo, costo configurable, máx. 72 bytes; emisión/verificación JWT (`sub`, `iat` fraccional, `exp`, roles); hash ficticio calculado en el lifespan
  - `app/core/dependencies.py`: `get_usuario_actual` (cookie `access_token`; 401 si falta, inválido, usuario inactivo o `iat` < `password_cambiada_en`), control de cambio obligatorio (403), `requiere_rol(...)` con roles vigentes consultados en la base
  - `POST /auth/registro` (201/409/422): usuario + `asignacion_rol` CLIENTE + `cliente` en un solo UoW, hash fuera de la transacción, `extra="forbid"`, documento existente → 409
  - `POST /auth/login` (200/401/422/429): límite 5 fallos/60 s por (email, ip) con `Retry-After` sin hash, anti-enumeración, cookie HttpOnly/SameSite=Lax/Max-Age/Secure configurable, `intento_acceso` en sesión y transacción propias
  - `POST /auth/logout`, `GET /auth/yo`, `POST /auth/cambiar-password` (invalida sesiones previas, cookie nueva)
  - Registro de `evento_seguridad` en altas y cambios de contraseña
  - Tests: registro atómico, 409 sin filas sueltas, 429, 401 vs 403, mismo cuerpo/tiempo con correo inexistente, token viejo → 401 tras cambio de contraseña, bloqueo con cambio pendiente
- **Dependencias**: `C-03`
- **Governance**: CRITICO
- **Leer antes**:
  - `knowledge-base/03_actores_y_roles.md`
  - `knowledge-base/05_reglas_de_negocio.md` §Roles y autorización, §Sesión y login
  - `knowledge-base/07_flujos_principales.md` §Flujos 1-4
  - `knowledge-base/08_arquitectura_propuesta.md` §Seguridad
  - `knowledge-base/06_funcionalidades.md` §Épica 2

### [C-06] `usuarios-roles-eventos`
- **Estado**: `[x]` completado
- **Scope**:
  - `POST /usuarios` (ADMIN; alta de personal con contraseña provisoria, `debe_cambiar_password=true`; 201/409/422)
  - `GET /usuarios/{id}/roles`, `POST /usuarios/{id}/roles` (vencimiento opcional con zona y futuro, si no 422; duplicado abierto 409), `DELETE /usuarios/{id}/roles/{rol}` (escribe `revocada_en`, no borra; no revocar el propio ADMIN ni dejar el sistema sin admins → 409; reasignar rol vencido cierra la fila previa)
  - `GET /eventos` (ADMIN, `page`, `size`, 422 si inválidos) sobre `evento_seguridad`
  - Eventos de seguridad en altas, cambios de rol y de contraseña
  - Tests: revocación corta el permiso en la petición siguiente; 409 de último admin; 422 de vencimiento sin zona/pasado; 403 a no-ADMIN
- **Dependencias**: `C-05`
- **Governance**: CRITICO
- **Leer antes**:
  - `knowledge-base/03_actores_y_roles.md` §Modelo de roles
  - `knowledge-base/05_reglas_de_negocio.md` §Roles y autorización
  - `knowledge-base/06_funcionalidades.md` §Épica 3
  - `knowledge-base/04_modelo_de_datos.md` §`asignacion_rol`, §`evento_seguridad`

---

## FASE 3 — Dominio: clientes e inventario

> C-07 y C-08 son independientes entre sí y se ejecutan en paralelo.

### [C-07] `clientes-vehiculos`
- **Estado**: `[x]` completado
- **Scope**:
  - Módulo `app/modules/clientes/` (models, schemas, repository, unit_of_work, service, router)
  - `POST /clientes` (RECEPCION, ADMIN; 201/409/422; documento repetido 409)
  - `GET /clientes/{id}` con vehículos por precarga (`selectinload`, sin N+1)
  - `POST /clientes/{id}/vehiculos` (patente vigente repetida 409; `anio` 1950-2100)
  - `DELETE /vehiculos/{id}` (204; borrado lógico; 409 con órdenes abiertas según `estado_orden.es_final`; patente reutilizable)
  - `GET /mis-vehiculos` (autenticado)
  - Tests: unicidad parcial de patente, baja con orden abierta, reutilización de patente, aislamiento de `/mis-vehiculos`
- **Dependencias**: `C-05`
- **Governance**: MEDIO
- **Leer antes**:
  - `knowledge-base/06_funcionalidades.md` §Épica 4
  - `knowledge-base/04_modelo_de_datos.md` §`cliente`, §`vehiculo`
  - `knowledge-base/07_flujos_principales.md` §Flujo 9
  - `knowledge-base/05_reglas_de_negocio.md` §Unicidad y registro

### [C-08] `repuestos-stock`
- **Estado**: `[x]` completado
- **Scope**:
  - Módulo `app/modules/repuestos/` (Repuesto, MovimientoStock, HistorialPrecioRepuesto)
  - `POST /repuestos` (ADMIN, con `stock_inicial` → movimiento "Stock inicial"; código vigente repetido 409)
  - `GET /repuestos` (`q` por descripción con parámetros ligados, `page`, `size`; ADMIN/RECEPCION/MECANICO) y `GET /repuestos/{id}`
  - `PATCH /repuestos/{id}` (descripción y precio; `extra="forbid"` → stock 422; cambio de precio escribe `historial_precio_repuesto` en la misma transacción; sin cambio de precio no escribe)
  - `DELETE /repuestos/{id}` (204, borrado lógico)
  - `POST /repuestos/{id}/reponer` (ADMIN; movimiento positivo)
  - **Punto único de escritura de stock** reutilizable por C-10 (RN-14)
  - `GET /repuestos/{id}/movimientos` y `/precios` (ADMIN; recepción recibe 403)
  - Tests: PATCH de stock → 422, historial de precio, `stock >= 0`, SQL sin inyección en `q`, 403 a RECEPCION en trazabilidad
- **Dependencias**: `C-05`
- **Governance**: ALTO
- **Leer antes**:
  - `knowledge-base/06_funcionalidades.md` §Épica 5
  - `knowledge-base/04_modelo_de_datos.md` §`repuesto`, §`movimiento_stock`, §`historial_precio_repuesto`
  - `knowledge-base/05_reglas_de_negocio.md` §Inventario
  - `knowledge-base/07_flujos_principales.md` §Flujo 8
  - `knowledge-base/10_preguntas_abiertas.md` §IN-01, §IN-05

---

## FASE 4 — Órdenes de trabajo

### [C-09] `ordenes-alta-consulta`
- **Estado**: `[x]` completado
- **Scope**:
  - Módulo `app/modules/ordenes/` (EstadoOrden, OrdenTrabajo, ItemOrden, HistorialEstadoOrden) con repositorio de sólo lectura para el catálogo `estado_orden` (PK `codigo`) y enum en código
  - `POST /ordenes` (RECEPCION, ADMIN; 201/409/422): nace PENDIENTE, ≥ 1 ítem sin repuestos repetidos, precio copiado del repuesto, `total` calculado en el servidor, primera línea de historial con `desde_estado=null`; repuesto/vehículo inexistente o de baja o catálogo vacío → 409 sin dejar rastro; todo en un único `async with uow`
  - `GET /ordenes` (filtro `estado` declarado en el contrato; otro valor → 422; `page`, `size`), `GET /ordenes/{id}` (personal o dueño; ajena 403; número fijo de consultas con eager loading), `GET /mis-ordenes`, `GET /estados-orden` (ordenado por `posicion`)
  - Respuesta con ítems, subtotales e historial
  - Tests: total y precio copiados, rollback total ante 409, número constante de consultas en el detalle (evidencia C-15), 403 a dueño ajeno
- **Dependencias**: `C-07, C-08`
- **Governance**: MEDIO
- **Leer antes**:
  - `knowledge-base/06_funcionalidades.md` §US-050, §US-054
  - `knowledge-base/07_flujos_principales.md` §Flujo 5
  - `knowledge-base/04_modelo_de_datos.md` §`orden_trabajo`, §`item_orden`, §`estado_orden`
  - `knowledge-base/05_reglas_de_negocio.md` §Órdenes de trabajo

### [C-10] `ordenes-ciclo-de-vida`
- **Estado**: `[x]` completado
- **Scope**:
  - `POST /ordenes/{id}/iniciar` (MECANICO; PENDIENTE → EN_REPARACION, queda asignado; 200/404/409)
  - `POST /ordenes/{id}/terminar` (mecánico asignado o ADMIN; EN_REPARACION → TERMINADA): un único UoW que descuenta stock vía el punto único, un `movimiento_stock` negativo por ítem con `orden_id`, línea de `historial_estado_orden`; stock insuficiente → 409 con rollback total (caso C-11); permiso 403 antes que estado 409
  - `POST /ordenes/{id}/cancelar` (RECEPCION, ADMIN o dueño; PENDIENTE → CANCELADA; ajena 403, terminada 409; 403 evaluado antes que 409)
  - `BackgroundTasks`: aviso al cliente (`asyncio.sleep(0.5)` + log) sólo tras commit exitoso
  - Cualquier otra transición → 409
  - Tests: matriz de transiciones, atomicidad de `terminar` con la orden #2 del seed (4 bujías vs stock 2), aviso sólo si hubo commit, orden de 403/409
- **Dependencias**: `C-09`
- **Governance**: ALTO
- **Leer antes**:
  - `knowledge-base/06_funcionalidades.md` §US-051, §US-052, §US-053
  - `knowledge-base/07_flujos_principales.md` §Flujos 6-7
  - `knowledge-base/05_reglas_de_negocio.md` §Órdenes de trabajo, §Inventario
  - `knowledge-base/11_casos_de_prueba_y_evaluacion.md`
  - `knowledge-base/10_preguntas_abiertas.md` §IN-02, §IN-03

---

## FASE 5 — Datos iniciales y entrega

### [C-11] `seed-datos-iniciales`
- **Estado**: `[x]` completado
- **Scope**:
  - `seed.py`: vacía las tablas y carga primero el catálogo `estado_orden` (PENDIENTE 1, EN_REPARACION 2, TERMINADA 3 final, CANCELADA 4 final)
  - Usuarios: `admin@example.com`, `admin2@example.com`, `recepcion@example.com`, `mecanico@example.com`, `mecanico2@example.com`, `cliente@example.com`, `nuevo@example.com` (MECANICO, `debe_cambiar_password=true`) con contraseñas de seed sólo dentro de `seed.py`
  - Clientes Laura (con usuario, 2 vehículos) y Jorge (sin usuario, 1 vehículo)
  - Repuestos `FIL-001` (10), `FRE-010` (4), bujía (2), `ACE-530` (20), cada stock como movimiento "Stock inicial"
  - Órdenes #1 PENDIENTE y #2 EN_REPARACION (mecánico asignado, 4 bujías con stock 2), historial de precio 8000 → 8500, evento de seguridad con actor `SISTEMA`
  - Tests: idempotencia (re-ejecutable), estado inicial conocido, catálogo cargado antes que órdenes
- **Dependencias**: `C-03, C-05`
- **Governance**: ALTO
- **Leer antes**:
  - `knowledge-base/04_modelo_de_datos.md` §Seed data inicial
  - `knowledge-base/03_actores_y_roles.md`
  - `knowledge-base/11_casos_de_prueba_y_evaluacion.md`
  - `knowledge-base/07_flujos_principales.md` §Flujo 10

### [C-12] `verificacion-y-entrega`
- **Estado**: `[x]` completado
- **Scope**:
  - `test/*.http` cubriendo todos los endpoints y códigos de la tabla de referencia (casos de la KB 11)
  - `test/solo_agregado.sql`: intentos de UPDATE/DELETE sobre las 3 tablas sólo-agregado
  - Evidencias de los casos C-14 y C-15 (con `SQL_ECHO=true`)
  - `README.md`: venv → dependencias → `.env` (cómo generar la clave) → `alembic upgrade head` → `python seed.py` → `uvicorn`
  - Revisión final: ningún 500 por entrada inválida, ningún `IntegrityError` ni traza expuestos, sin secretos en el repo
  - Tests: corrida completa end-to-end de los flujos 1-9 sobre la base seed
- **Dependencias**: `C-04, C-06, C-10, C-11`
- **Governance**: BAJO
- **Leer antes**:
  - `knowledge-base/11_casos_de_prueba_y_evaluacion.md`
  - `knowledge-base/08_arquitectura_propuesta.md` §Diagnóstico y entrega
  - `knowledge-base/06_funcionalidades.md` §Tabla completa de endpoints
  - `knowledge-base/README.md`

---

## Resumen

| Change | Nombre | Fase | Dependencias | Governance |
|--------|--------|------|--------------|------------|
| C-01 | foundation-setup | 1 | — | BAJO |
| C-02 | core-db-uow | 1 | C-01 | CRITICO |
| C-03 | modelos-y-migraciones | 1 | C-02 | CRITICO |
| C-04 | health-endpoints | 1 | C-02 | BAJO |
| C-05 | auth-registro-login-sesion | 2 | C-03 | CRITICO |
| C-06 | usuarios-roles-eventos | 2 | C-05 | CRITICO |
| C-07 | clientes-vehiculos | 3 | C-05 | MEDIO |
| C-08 | repuestos-stock | 3 | C-05 | ALTO |
| C-09 | ordenes-alta-consulta | 4 | C-07, C-08 | MEDIO |
| C-10 | ordenes-ciclo-de-vida | 4 | C-09 | ALTO |
| C-11 | seed-datos-iniciales | 5 | C-03, C-05 | ALTO |
| C-12 | verificacion-y-entrega | 5 | C-04, C-06, C-10, C-11 | BAJO |

**Primer change recomendado**: `C-01` (foundation-setup) — `/opsx:propose C-01-foundation-setup`
