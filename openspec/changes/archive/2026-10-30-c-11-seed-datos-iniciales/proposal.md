# Proposal — C-11 `seed-datos-iniciales`

## Why

La migración deja el catálogo `estado_orden` vacío a propósito y no hay usuarios ni datos: sin `seed.py` la API no puede crear ni transicionar órdenes (FK al catálogo) y los casos de prueba de la KB 11 (C-01..C-19), que se corren "después de `python seed.py`", no tienen un estado inicial conocido. En particular el caso C-11 (terminar la orden #2 con 4 bujías cuando hay 2 → 409) y el C-12 (reponer y terminar → 200) dependen de datos exactos. Es el último prerrequisito de C-12 (`verificacion-y-entrega`).

## What Changes

- Nuevo `seed.py` en la raíz del proyecto, ejecutable con `python seed.py` tras `alembic upgrade head`.
- Vacía las 13 tablas de negocio con un único `TRUNCATE ... RESTART IDENTITY CASCADE` (los disparadores de sólo-agregado son por fila y no frenan `TRUNCATE`) y carga, **en la misma transacción**, el estado inicial de la KB 04 §Seed:
  - Catálogo `estado_orden` primero: PENDIENTE (1), EN_REPARACION (2), TERMINADA (3, final), CANCELADA (4, final), con descripción.
  - 7 usuarios (`admin`, `admin2`, `recepcion`, `mecanico`, `mecanico2`, `cliente`, `nuevo` @example.com) con su rol vigente sin vencimiento; `nuevo` es MECANICO con `debe_cambiar_password=true`. Contraseñas fijas y ficticias definidas **sólo** en `seed.py` (DD-15, ≥ 8 caracteres DD-16), hasheadas con el `ServicioContrasenas` existente (`BCRYPT_ROUNDS`, `to_thread` + semáforo) **antes** de abrir la transacción.
  - Clientes Laura (con usuario `cliente@example.com`, 2 vehículos) y Jorge (sin usuario, 1 vehículo), patentes ya normalizadas.
  - Repuestos `FIL-001`, `FRE-010`, `BUJ-001` (bujía), `ACE-530`, con stock cargado a través de `mover_stock` como movimiento "Stock inicial".
  - Orden #1 PENDIENTE (primer vehículo de Laura) y orden #2 EN_REPARACION (vehículo de Jorge, asignada a `mecanico@example.com`, con 4 bujías y stock 2), con ítems, total e historial de estado.
  - Historial de precio del filtro 8000 → 8500 y una línea de `evento_seguridad` con actor `SISTEMA` y acción "Carga de los datos iniciales".
- Idempotente: cada ejecución deja exactamente el mismo estado conocido (mismos ids gracias a `RESTART IDENTITY`). Si algo falla, la transacción se revierte y la base queda como estaba.
- Guarda mínima de seguridad (a aprobar): se niega a correr contra un host que no sea local salvo bandera explícita; informa el destino (sin contraseña) antes de vaciar.
- Tests de integración sobre PostgreSQL real (esquema efímero migrado con Alembic): estado conocido, idempotencia, catálogo antes que órdenes, garantías de sólo-agregado intactas, y escenarios dependientes del seed (C-11/C-12 por HTTP con login real, más los puntos de partida de C-06, C-09, C-16, C-17, C-18 y DD-18).

## Capabilities

### New Capabilities
- `datos-iniciales`: carga del estado inicial conocido con `seed.py` — vaciado atómico, contenido exacto (catálogo, usuarios y roles, clientes y vehículos, repuestos y stock, órdenes, historiales), idempotencia, manejo de contraseñas del seed y guarda de destino.

### Modified Capabilities
<!-- Ninguna: `estados-orden` ya establece que sólo `seed.py` carga el catálogo; `solo-agregado` ya admite TRUNCATE; `configuracion` ya prohíbe variables SEED_*. El seed sólo consume esas garantías. -->

## Impact

- **Código nuevo**: `seed.py` (raíz). No modifica módulos de `app/`; reutiliza `app/core/{config,database,security,unit_of_work}.py`, `app/modules/modelos.py`, los repositorios de cada módulo y `mover_stock` (`app/modules/repuestos/stock.py`).
- **Tests nuevos**: `test/unit/test_seed_*.py` (datos y guarda, sin base) y `test/integration/seed/` (PostgreSQL real, esquema efímero).
- **Base de datos**: ningún cambio de esquema ni migración. `seed.py` **destruye todos los datos** de las 13 tablas del destino: por eso la guarda.
- **Dependencias**: ninguna nueva.
- **Downstream**: C-12 (README, `.http`, evidencias) asume este estado inicial y los ids fijos (órdenes 1 y 2, repuestos 1..4).
- **Governance**: ALTO (usuarios y contraseñas, borrado de datos): las decisiones del `design.md` §"Decisiones a aprobar" requieren aprobación antes de `apply`.
