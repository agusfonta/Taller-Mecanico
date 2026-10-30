# Proposal — C-03 `modelos-y-migraciones`

## Why

C-02 dejó motor, sesión, repositorios y Unit of Work, pero la base todavía **no tiene esquema**: `migrations/versions/` está vacío y `migrations/env.py` tiene `target_metadata = None`. Ningún módulo funcional (C-05 en adelante) puede escribir una fila sin las 13 tablas de la KB, y gran parte de las garantías del TP (RN-01, RN-03, RN-15, RN-19, CHECKs de valores) se delegan **a la base**, no al código (KB 04 §Garantías delegadas). El Ejercicio 2 (14 pts) evalúa exactamente esto: restricciones, índices únicos parciales, catálogo con FK, navegación, dos migraciones (una a mano) y upgrade/downgrade; el Ejercicio 7 (10 pts) evalúa el disparador de sólo-agregado. Es el tercer eslabón del camino crítico y desbloquea C-05 y C-11.

## What Changes

- **Modelos de tabla** (SQLModel, `table=True`) con los **nombres de tabla y columna exactos** de KB 04, uno por archivo de módulo:
  - `app/modules/usuarios/models.py`: `Usuario`, `AsignacionRol`, `IntentoAcceso`, `EventoSeguridad` (+ enum `Rol` como vocabulario del CHECK).
  - `app/modules/clientes/models.py`: `Cliente`, `Vehiculo`.
  - `app/modules/repuestos/models.py`: `Repuesto`, `MovimientoStock`, `HistorialPrecioRepuesto`.
  - `app/modules/ordenes/models.py`: `EstadoOrden`, `OrdenTrabajo`, `ItemOrden`, `HistorialEstadoOrden`.
- **Base común de modelos** `app/core/models.py`: convención de nombres de restricciones e índices sobre `SQLModel.metadata` y tipos de columna compartidos (fecha con zona, dinero `NUMERIC`/`Decimal`, texto, PK identidad). **Registro de modelos** `app/modules/modelos.py`: importa los cuatro módulos y expone la metadata completa (la usan Alembic y la app).
- **Restricciones**: UNIQUE (`usuario.email`, `cliente.documento`, `cliente.usuario_id`, `estado_orden.posicion`, `item_orden(orden_id, repuesto_id)`); índices únicos parciales (`vehiculo.patente` y `repuesto.codigo` `WHERE borrado_en IS NULL`; `asignacion_rol(usuario_id, rol) WHERE revocada_en IS NULL`); CHECKs (rol, anio, precio, stock, total, cantidades, precios unitarios, `precio_nuevo > 0`, `precio_nuevo <> precio_anterior`, `movimiento_stock.cantidad <> 0`); FK `orden_trabajo.estado`, `desde_estado`, `hasta_estado` → `estado_orden.codigo`; **un índice cuyo primer campo es cada FK**; índice (`email`, `ip`, `cuando`) en `intento_acceso`.
- **Navegación** declarada en los dos extremos de cada relación del ERD; `Usuario.cliente` devuelve **un objeto**; todas las relaciones **prohíben la carga implícita** (una relación no precargada falla en vez de emitir SQL oculto).
- **Migración 1** generada con `alembic revision --autogenerate` (todas las tablas, catálogo `estado_orden` **vacío**), revisada antes de aplicar y con comentario que lo dice.
- **Migración 2 escrita a mano**: función + disparador de sólo-agregado (rechaza UPDATE y DELETE) en `historial_estado_orden`, `movimiento_stock` y `historial_precio_repuesto`, con `downgrade` que los elimina.
- `migrations/env.py`: `target_metadata` = metadata del registro de modelos; acepta una conexión inyectada (para que los tests apliquen las migraciones en un esquema desechable). Sin `create_all` en ningún camino de la app.
- **Tests** (Strict TDD): unitarios sobre metadata/mapeos (sin base) y de **integración contra PostgreSQL real** sobre un esquema **migrado con Alembic**: `upgrade head → downgrade base → upgrade head`, sin diferencias entre modelos y migraciones, cada CHECK/UNIQUE/índice parcial/FK dispara su violación, UPDATE/DELETE rechazados en las 3 tablas sólo-agregado, toda FK indexada, navegación con precarga y carga implícita prohibida.

## Capabilities

### New Capabilities
- `modelo-de-datos`: tablas, columnas, tipos, restricciones e índices que la base garantiza (unicidad, unicidad parcial, CHECKs, FK al catálogo, índices de FK) y navegación entre entidades sin carga implícita.
- `migraciones`: esquema administrado sólo por migraciones versionadas (una autogenerada, una escrita a mano), reversibles de punta a punta, en sincronía con los modelos y con el catálogo de estados vacío.
- `solo-agregado`: inmutabilidad de `historial_estado_orden`, `movimiento_stock` e `historial_precio_repuesto` garantizada por la base (UPDATE y DELETE rechazados; INSERT permitido).

### Modified Capabilities
<!-- Ninguna: `repositorios`, `unidad-de-trabajo` y `sesion-base-datos` no cambian sus requisitos; los modelos nuevos los usan tal cual. -->

## Impact

- **Código nuevo**: `app/core/models.py`, `app/modules/modelos.py`, `app/modules/{usuarios,clientes,repuestos,ordenes}/models.py`, `migrations/versions/<rev1>_esquema_inicial.py` (autogenerada), `migrations/versions/<rev2>_solo_agregado.py` (a mano); tests en `test/unit/` y `test/integration/`.
- **Código modificado**: `migrations/env.py` (`target_metadata`, conexión inyectable, logging que no desactiva loggers existentes); `test/integration/conftest.py` (fixtures de esquema migrado); `main.py` sólo para importar el registro de modelos (mapeos configurados al arrancar).
- **APIs**: ninguna ruta nueva. Los contratos de entrada/salida (schemas) **no** se crean acá: llegan con cada módulo (C-05+), separados de los modelos de tabla.
- **Dependencias**: ninguna nueva (SQLModel, SQLAlchemy async, asyncpg, Alembic ya declarados en C-01).
- **Base de datos**: `alembic upgrade head` crea las 13 tablas + `alembic_version`; el catálogo queda vacío hasta `seed.py` (C-11). Tests de integración requieren el PostgreSQL de `docker-compose.yml`.
- **Desbloquea**: C-05 (auth), C-11 (seed); C-07..C-10 usan estos modelos y sus relaciones.
- **Governance**: **CRITICO** (CHANGES.md §C-03) — requiere aprobación humana explícita de `design.md` antes de `/opsx:apply`.
