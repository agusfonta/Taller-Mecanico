# Proposal — C-04 `health-endpoints`

## Why

C-02 dejó motor, fábrica de sesiones y lifespan, pero la aplicación no tiene cómo **informar su estado** a quien la opera: no se distingue un proceso vivo (que no conviene reiniciar) de un proceso listo para atender (que depende de que PostgreSQL conteste). US-001 lo pide explícitamente ("reiniciar no arregla una base caída") y el criterio del Ej. 1 de la consigna puntúa la "salud" junto con el lifespan. Además, son las primeras rutas reales de la app: validan de punta a punta que el grupo abierto de DD-07 funciona y que el motor creado en el lifespan es usable. Sólo depende de C-02, por lo que corre en paralelo con C-03.

## What Changes

- `app/modules/health/router.py` (KB 08: el módulo `health` tiene **sólo** `router.py`) con dos rutas bajo el prefijo `/health`:
  - `GET /health/live` → **200** siempre que el proceso atienda; **no toca la base** (no abre sesión ni conexión).
  - `GET /health/ready` → ejecuta `SELECT 1` contra PostgreSQL con un **tiempo máximo acotado**; **200** si contesta, **503** si no contesta, falla o excede el tiempo. El cuerpo nunca expone detalles internos (ni URL, ni host, ni texto de la excepción).
- `main.py`: la `app` real se arma con `crear_app(abiertos=[router_health])`, es decir, las rutas de salud viven en el **grupo abierto** (sin control de acceso, DD-07). Así quedan fuera del control que C-05 montará en el grupo protegido (incluido el bloqueo por cambio obligatorio de contraseña, KB 07: "todo fuera de `/auth/*` y `/health/*` → 403").
- Tests: unitarios con la fábrica `crear_app` y dobles del motor (vivo sin base, listo, base que falla, base que no contesta a tiempo, cuerpo sin detalles internos) e **integración contra PostgreSQL real** (`ready` → 200 con la base levantada; `ready` → 503 con un motor apuntando a un puerto sin servidor).

## Capabilities

### New Capabilities
- `salud`: chequeos de vida (`live`, sin tocar la base) y de disponibilidad (`ready`, con consulta trivial a la base, tiempo acotado y 503 sin detalles internos), accesibles sin sesión.

### Modified Capabilities
<!-- Ninguna: `grupos-de-rutas` ya exige que las rutas del grupo abierto no pasen por el control; `sesion-base-datos` ya garantiza que el arranque no contacta la base. C-04 sólo se apoya en esos requisitos. -->

## Impact

- **Código nuevo**: `app/modules/health/router.py`; `test/unit/test_health.py`; `test/integration/test_health.py`.
- **Código modificado**: `main.py` (sólo la línea que construye `app`, para registrar el router de salud en el grupo abierto).
- **APIs**: `GET /health/live` (200) y `GET /health/ready` (200, 503), abiertas a cualquiera (KB 03, KB 06).
- **Dependencias**: ninguna nueva.
- **No depende de C-03**: no usa modelos, tablas ni migraciones; `SELECT 1` funciona sobre una base vacía.
- **Infra de tests**: los tests de integración reutilizan `settings_db` y `--exigir-db` de C-02.
- **Desbloquea**: C-12 (verificación y entrega).
- **Governance**: **BAJO** (CHANGES.md §C-04) — autonomía completa si los tests pasan.
