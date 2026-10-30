# Proposal — C-02 `core-db-uow`

## Why

C-01 dejó la configuración tipada y el esqueleto, pero la aplicación todavía no tiene **cómo hablar con PostgreSQL**: no hay motor, ni fábrica de sesiones, ni lifespan, ni las piezas transaccionales que el PDF exige (repositorio que nunca confirma, Unit of Work que confirma/revierte y no cierra la sesión, servicio que nunca construye su UoW). Todos los módulos funcionales (C-03 en adelante) se apoyan en estas abstracciones; si nacen mal, cada módulo hereda el defecto (commits dispersos, sesiones filtradas, recursos creados al importar — EA-08). Es el segundo eslabón del camino crítico y desbloquea C-03 (modelos y migraciones) y C-04 (salud).

## What Changes

- `app/core/database.py`: funciones que **crean** el motor asincrónico (pool configurable con `DB_POOL_SIZE`/`DB_MAX_OVERFLOW`, `SQL_ECHO`) y la fábrica de sesiones; las llama **sólo** el lifespan, nunca la importación del módulo. Dependencia `get_session` que entrega una sesión por petición tomada de `app.state` y la cierra al terminar.
- `main.py`: fábrica de aplicación con **lifespan** que guarda motor y fábrica de sesiones en `app.state` y ejecuta `engine.dispose()` al apagar; **dos grupos de rutas** (abierto / protegido, DD-07). El grupo protegido lleva **una** dependencia de control montada una sola vez; en C-02 es un **gancho que rechaza (falla cerrado)** hasta que C-05 implemente la autenticación real. Se conserva el fail-fast de configuración de C-01.
- `app/core/dependencies.py`: sólo el gancho del grupo protegido (C-05 lo reemplaza por usuario actual + control de cambio de contraseña).
- `app/core/repository.py`: `BaseRepository[T]` (recibe sesión **y** clase del modelo; `add`/`update`/`delete` con `flush()`, **nunca** `commit()`; `get_by_id`, `list`, `count`) y `SoftDeleteRepository[T]` (filtra por defecto las filas con `borrado_en` no nulo; agrega `get_by_id_including_deleted` y `soft_delete`).
- `app/core/unit_of_work.py`: `UnitOfWork` base como gestor de contexto asincrónico: confirma al salir sin error, revierte ante excepción (y la propaga), **no cierra la sesión**. Los módulos lo extienden componiendo sus repositorios sobre la misma sesión.
- `app/core/paginacion.py`: parámetros `page`/`size` (page ≥ 1; size 1–100, default 20), envoltorio `{items, total, page, size, pages}`, cálculo de páginas (cero resultados → una página vacía) y error de página fuera de rango traducido a **422** con mensaje propio.
- Tests: unitarios (UoW con sesión espía, cálculo de páginas, grupos de rutas, lifespan) y de **integración contra PostgreSQL real** (UoW confirma/revierte de verdad, repositorio no confirma, borrado lógico filtra dados de baja) usando una tabla **sólo de test**, fuera del código de la app.

## Capabilities

### New Capabilities
- `sesion-base-datos`: ciclo de vida de motor y fábrica de sesiones (creados en el lifespan, guardados en `app.state`, liberados al apagar), pool configurable y entrega de una sesión por petición.
- `unidad-de-trabajo`: semántica transaccional del UoW base (commit al salir, rollback ante excepción, no cierra la sesión) y su extensión por módulo.
- `repositorios`: repositorio genérico que nunca confirma y repositorio con borrado lógico (filtrado por defecto, consulta incluyendo dados de baja, baja lógica).
- `paginacion`: contrato de parámetros y envoltorio de listados, cálculo de páginas y rechazo de páginas inexistentes.
- `grupos-de-rutas`: grupo abierto y grupo protegido con su dependencia de control montada una vez (gancho que falla cerrado hasta C-05).

### Modified Capabilities
<!-- Ninguna: `estructura-proyecto` y `configuracion` no cambian a nivel de requisitos. El arranque sigue fallando sin secretos y cargando sin contactar la base (el motor es perezoso y se crea en el lifespan). -->

## Impact

- **Código nuevo**: `app/core/database.py`, `app/core/repository.py`, `app/core/unit_of_work.py`, `app/core/paginacion.py`, `app/core/dependencies.py`; tests en `test/unit/` y `test/integration/` (+ `test/integration/conftest.py`).
- **Código modificado**: `main.py` (lifespan, fábrica de app, grupos de rutas); `test/conftest.py` sólo si hace falta compartir fixtures.
- **APIs**: ninguna ruta de negocio nueva. Respuesta 422 propia para página fuera de rango (la usan los listados de C-06..C-10).
- **Dependencias**: ninguna nueva (SQLAlchemy async, asyncpg, SQLModel y pytest-asyncio ya declarados en C-01).
- **Infra de tests**: los tests de integración requieren el PostgreSQL de `docker-compose.yml` levantado y las `POSTGRES_*` en el entorno/`.env`.
- **Desbloquea**: C-03 (`modelos-y-migraciones`) y C-04 (`health-endpoints`); C-05 reemplaza el gancho del grupo protegido.
- **Governance**: **CRITICO** — requiere aprobación humana explícita del diseño antes de `/opsx:apply`.
