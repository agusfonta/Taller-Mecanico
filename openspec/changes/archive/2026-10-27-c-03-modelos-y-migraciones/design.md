# Design — C-03 `modelos-y-migraciones`

> ⚠️ **Governance CRITICO** (CHANGES.md §C-03): este diseño fija el esquema físico del que dependen todos los changes siguientes y la corrección (nombres de tablas/columnas obligatorios, Ej. 2 y Ej. 7). **Requiere aprobación humana explícita antes de `/opsx:apply`.** Ningún agente debe empezar a implementar sin ese visto bueno. Puntos a aprobar en particular: D1 (dónde viven los modelos), D3 (tipos y PK), D5 (relaciones con `lazy="raise"`), D7 (disparador y TRUNCATE), D8 (`env.py` con conexión inyectable) y D9 (estrategia de tests de integración).

## Context

- Estado tras C-01/C-02 (observado en el código):
  - `migrations/env.py`: plantilla asincrónica; URL desde `get_settings().database_url`; `target_metadata = None  # C-03: SQLModel.metadata`; `fileConfig(...)` con el default `disable_existing_loggers=True`; `run_migrations_online()` hace `asyncio.run(...)`. `migrations/versions/` vacío. `alembic.ini` sin URL.
  - `app/core/repository.py`: `BaseRepository[T]` exige PK de **una sola columna** (introspección) y usa `select(...).where(pk == id)`; `SoftDeleteRepository` filtra `borrado_en IS NULL`. Su docstring recomienda `lazy="raise"` para C-03.
  - `app/core/database.py`: fábrica con `expire_on_commit=False`.
  - `test/integration/conftest.py`: `settings_db` (ping síncrono con `asyncio.run`, skip / fallo con `--exigir-db`), `esquema_prueba` (esquema efímero `c02_prueba_<hex>` por test), `motor_prueba` (`NullPool`, `search_path` por `server_settings`, `BasePrueba.metadata.create_all`), `fabrica_prueba`.
  - `test/integration/modelos_prueba.py`: `BasePrueba(SQLModel, registry=registry())` → metadata **propia**, fuera de `SQLModel.metadata`.
  - `app/modules/{usuarios,clientes,repuestos,ordenes}/` sólo tienen `__init__.py`. `test/unit/test_estructura.py` importa cada módulo **sin secretos** en el entorno.
  - Versiones instaladas en el entorno de desarrollo: SQLAlchemy 2.0.43, Alembic 1.16.5, pytest-asyncio 0.24.
- Motivación y alcance: ver `proposal.md`. Requisitos observables: `specs/{modelo-de-datos,migraciones,solo-agregado}/spec.md`.
- Restricciones: KB 04 (nombres obligatorios, `timestamptz`, `NUMERIC`/`Decimal`, índice por FK, migración 1 autogenerada + migración 2 a mano, upgrade/downgrade/upgrade, catálogo vacío), KB 08 (estructura por módulo, repositorio de sólo lectura para `estado_orden`, eager loading en el repositorio), reglas duras de `CLAUDE.md` (modelos de tabla separados de contratos, sin carga perezosa, sin `float` para dinero, sin `create_all`, PostgreSQL real en integración), DD-01..DD-05, DD-15 (contraseñas de seed sólo en `seed.py`, C-11).

### Discrepancias detectadas con `CHANGES.md` / KB

1. **TRUNCATE y el disparador**: KB 04 dice que `seed.py` "vacía las tablas", y el disparador rechaza UPDATE/DELETE. Un `DELETE FROM` del seed sobre las tablas sólo-agregado sería rechazado. Se decide (D7) que el disparador es **por fila** sobre UPDATE/DELETE y **no** bloquea `TRUNCATE`; C-11 debe vaciar con `TRUNCATE ... RESTART IDENTITY CASCADE`. Queda registrado como requisito en `solo-agregado` para que C-11 no lo descubra tarde.
2. **"Índice por cada FK"** (KB 04) vs. regla de la skill "sin índices redundantes": se interpreta como "cada FK es el **primer campo** de algún índice". `cliente.usuario_id` (UNIQUE) e `item_orden.orden_id` (UNIQUE (`orden_id`,`repuesto_id`)) quedan cubiertos por esas restricciones; las demás FK llevan índice propio. Se verifica con una consulta al catálogo (D9). El índice único parcial de `asignacion_rol` **no** cubre `usuario_id` (sólo filas abiertas): lleva índice propio.
3. **Columnas no marcadas "(nulo)"** en KB 04 se toman como `NOT NULL` (p. ej. `movimiento_stock.usuario_id`, `historial_estado_orden.usuario_id`). Consecuencia para C-11: los movimientos "Stock inicial" y la primera línea de historial del seed necesitan un usuario (p. ej. el admin).
4. `CHANGES.md` lista "índice por cada FK" e "índice (`email`,`ip`,`cuando`)" pero no FKs de `otorgada_por`, `desde_estado`, `hasta_estado`, `orden_id` en `movimiento_stock`: KB 04 sí las implica (FK → `usuario`, FK → catálogo, FK → orden). Se incluyen.
5. La KB no fija la acción `ON DELETE`. Se usa el default (`NO ACTION`) en todas: no hay borrados físicos en el dominio (bajas lógicas, revocaciones por fecha, órdenes canceladas por estado) y un `CASCADE` borraría historial.
6. `main.py` no figura en el scope de C-03; se toca **sólo** para importar el registro de modelos, de modo que los mapeos estén completos al arrancar (D2).

## Goals / Non-Goals

**Goals:**
- Esquema físico idéntico a KB 04, generado por Alembic desde modelos que son la única fuente (sin DDL duplicado salvo el disparador).
- Toda garantía delegada a la base, verificada contra PostgreSQL real con una violación por regla y su caso borde válido.
- Relaciones listas para que C-05..C-10 precarguen con `selectinload`/`joinedload` y fallen ruidosamente si olvidan precargar.

**Non-Goals:**
- Repositorios, UoW, schemas (contratos de API) y servicios de cada módulo (C-05..C-10). El repositorio de sólo lectura del catálogo y el enum `EstadoOrden` en código son de C-09.
- Datos: catálogo, usuarios, contraseñas de demo (C-11, DD-15). Ninguna migración inserta filas.
- Traducción de `IntegrityError` a 409 (routers de cada módulo, RN-18).
- Normalización de `email` (minúsculas) — la hace el servicio en C-05; la base sólo garantiza UNIQUE exacto.
- Permisos por rol de base de datos (DD-04: no se pide).
- `test/solo_agregado.sql` y evidencias `psql` de C-14 (C-12).

## Decisions

### D1 — Modelos por módulo + registro central
- Cada módulo declara sus tablas en `app/modules/<modulo>/models.py`, como manda la estructura obligatoria de KB 08 (`usuarios`: Usuario, AsignacionRol, IntentoAcceso, EventoSeguridad; `clientes`: Cliente, Vehiculo; `repuestos`: Repuesto, MovimientoStock, HistorialPrecioRepuesto; `ordenes`: EstadoOrden, OrdenTrabajo, ItemOrden, HistorialEstadoOrden). `IntentoAcceso`/`EventoSeguridad` van a `usuarios` porque C-05/C-06 son sus únicos usuarios.
- `app/modules/modelos.py` (registro): importa los cuatro `models.py` y expone `metadata = SQLModel.metadata` y `__all__` con las 13 clases. Lo importan `migrations/env.py` (autogenerate) y `main.py` (mapeos completos antes de la primera consulta).
- Relaciones entre módulos con **nombres de clase como texto** (`"OrdenTrabajo"`) e imports bajo `TYPE_CHECKING`: ningún `models.py` importa a otro en runtime → sin ciclos. Los nombres de clase son únicos en todo el registro (requisito para resolver por texto).
- **Alternativa**: un único `app/core/models.py` con las 13 clases → más simple para Alembic, pero contradice la estructura obligatoria de KB 08 y C-07..C-10 (que dicen "módulo ... (models, ...)"); descartada.
- Importar `models.py` no requiere configuración: `test_estructura.py` sigue importando módulos sin secretos.

### D2 — Base común `app/core/models.py`
- Fija `SQLModel.metadata.naming_convention` **al importarse**, antes de que se defina cualquier tabla (cada `models.py` lo importa primero):
  `ix: ix_%(column_0_N_label)s`, `uq: uq_%(table_name)s_%(column_0_N_name)s`, `ck: ck_%(table_name)s_%(constraint_name)s`, `fk: fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s`, `pk: pk_%(table_name)s`.
  Nombres deterministas → la migración 1 es reproducible, el `downgrade` los encuentra y los tests identifican **qué** restricción falló por `constraint_name` (asyncpg lo expone en `exc.orig.__cause__`). Los CHECK se declaran con nombre corto (`ck_vehiculo_anio_rango` sale de `name="anio_rango"`).
- Helpers de columna (funciones que devuelven `sa_column`/`Field`) para no repetir tipos: `pk_identidad()`, `fk(tabla_col, nullable)`, `fecha(nullable, server_default_now)`, `dinero(precision, escala)`, `texto(nullable)`. Garantizan que **no** se use `AutoString`/`VARCHAR` (que además obligaría a `import sqlmodel` en la migración autogenerada).
- La convención **no** afecta a `BasePrueba` (registry/metadata propios de C-02).
- **Alternativa**: nombrar cada restricción a mano → propenso a olvidos; descartada. Sin convención → nombres de PostgreSQL (`vehiculo_anio_check`) que autogenerate deja en `None` y complican el downgrade; descartada.

### D3 — Tipos, PK y defaults
| Concepto | Tipo PostgreSQL | Python |
|---|---|---|
| PK (`id`) | `BIGINT GENERATED BY DEFAULT AS IDENTITY` | `int \| None` |
| FK a `id` | `BIGINT` | `int` / `int \| None` |
| Texto (`email`, `nombre`, `patente`, `codigo`, `falla`, `motivo`, `accion`, `actor`, `ip`, `estado`, `rol`…) | `TEXT` | `str` |
| Dinero | `NUMERIC(10,2)` / `NUMERIC(12,2)` (`total`) | `Decimal` |
| Fechas | `TIMESTAMPTZ` | `datetime` (aware) |
| Cantidades, `stock`, `anio`, `posicion` | `INTEGER` | `int` |
| Banderas | `BOOLEAN NOT NULL` | `bool` |
- `BY DEFAULT` y no `ALWAYS`: el seed (C-11) y los tests pueden necesitar ids explícitos ("orden #1/#2") y `TRUNCATE ... RESTART IDENTITY` los reinicia. **Alternativa** `SERIAL`/`INTEGER` (default de SQLModel) → la skill recomienda identidad `BIGINT`; costo nulo; descartada.
- `ip` como `TEXT`, no `INET`: `TestClient` reporta el host `"testclient"`, que `INET` rechazaría con un 500 en C-05.
- `rol` como `TEXT` + CHECK construido desde el enum `Rol(StrEnum)` (fuente única del vocabulario). **Alternativa** tipo `ENUM` de PostgreSQL → autogenerate no maneja bien su ciclo de vida en downgrade y cambiarlo exige DDL especial; la KB pide CHECK; descartada.
- Defaults: `activo=true`, `debe_cambiar_password=false`, `stock=0`, `total=0`, `es_final` sin default (lo fija el seed). Fechas de evento (`cuando`, `desde`, `creada_en`): default Python `datetime.now(UTC)` (el ORM no necesita releer la fila; coherente con `expire_on_commit=False` de C-02) **y** `server_default=now()` (para inserciones desde `psql`/seed). Los defaults de servidor se declaran como `server_default` para que autogenerate los emita.
- Nulos: exactamente los marcados "(nulo)" en KB 04 (`password_cambiada_en`, `vence_en`, `revocada_en`, `otorgada_por`, `cliente.usuario_id`, `borrado_en`, `mecanico_id`, `desde_estado`, `movimiento_stock.orden_id`); el resto `NOT NULL` (discrepancia 3).

### D4 — Restricciones e índices (en `__table_args__`)
- UNIQUE: `usuario.email`, `cliente.documento`, `cliente.usuario_id`, `estado_orden.posicion`, `item_orden(orden_id, repuesto_id)`.
- Únicos parciales: `Index("uq_vehiculo_patente_vigente", "patente", unique=True, postgresql_where=text("borrado_en IS NULL"))`; idem `uq_repuesto_codigo_vigente`; `uq_asignacion_rol_abierta (usuario_id, rol) WHERE revocada_en IS NULL`. Autogenerate los detecta (incluido el `WHERE`); se verifica en la revisión de la migración 1.
- CHECKs: los 10 de la spec, con nombre (`rol_valido`, `anio_rango`, `precio_positivo`, `stock_no_negativo`, `total_no_negativo`, `cantidad_positiva`, `precio_unitario_positivo`, `cantidad_distinta_de_cero`, `precio_nuevo_positivo`, `precio_nuevo_distinto`).
- Índices de FK (discrepancia 2): `index=True` en cada FK no cubierta; `ix_intento_acceso_email_ip_cuando (email, ip, cuando)` (igualdades primero, rango al final — la consulta de RN-08).
- FKs con `ON DELETE` por defecto (`NO ACTION`) — discrepancia 5.
- **Sin** `CREATE INDEX CONCURRENTLY` / `NOT VALID`: la skill lo recomienda para tablas con datos en producción; acá las tablas nacen vacías dentro de la transacción de la migración y `CONCURRENTLY` no puede ir en una transacción. Se registra como decisión consciente.

### D5 — Relaciones: ambos extremos, `back_populates`, `lazy="raise"`
- Pares (todos con `back_populates`): `Cliente.vehiculos`↔`Vehiculo.cliente`; `Vehiculo.ordenes`↔`OrdenTrabajo.vehiculo`; `OrdenTrabajo.items`↔`ItemOrden.orden`; `ItemOrden.repuesto`↔`Repuesto.items_orden`; `OrdenTrabajo.historial`↔`HistorialEstadoOrden.orden`; `OrdenTrabajo.estado_orden`↔`EstadoOrden.ordenes` (la columna se llama `estado`, nombre obligatorio, por eso la relación es `estado_orden`); `OrdenTrabajo.mecanico`↔`Usuario.ordenes_asignadas`; `Usuario.asignaciones`↔`AsignacionRol.usuario`; `Usuario.cliente`↔`Cliente.usuario` con `uselist=False` (devuelve un objeto); `Repuesto.movimientos`↔`MovimientoStock.repuesto`; `Repuesto.historial_precios`↔`HistorialPrecioRepuesto.repuesto`.
- `AsignacionRol` tiene dos FK a `usuario` (`usuario_id`, `otorgada_por`): la relación declara `foreign_keys` explícito. `otorgada_por`, `usuario_id` de las tablas de auditoría, `desde_estado`/`hasta_estado` y `movimiento_stock.orden_id` quedan como **FK sin navegación** (nadie las lee como objeto hoy; un change posterior puede agregarlas en ambos extremos sin migración).
- **`lazy="raise"`** en todas (vía `sa_relationship_kwargs`): una relación no precargada lanza `InvalidRequestError` en vez de emitir SQL — en async la alternativa sería `MissingGreenlet` críptico; en sync, un N+1 silencioso. Los repositorios precargan con `selectinload` (colecciones) / `joinedload` (muchos-a-uno) en el método que lo necesita (KB 08). **Alternativa** `lazy="selectin"` por defecto → carga siempre, aunque no se use (consultas extra en listados, rompe la evidencia C-15 de "consultas fijas"); descartada.
- Cascada default (`save-update, merge`): agregar una orden con `items=[...]` persiste los ítems (composición ◆ de la KB) sin `delete-orphan` (no hay borrado físico de órdenes).
- Sin `from __future__ import annotations` en los `models.py`: SQLModel no resuelve `Relationship` con anotaciones diferidas; se usan referencias en texto.
- Los modelos de tabla **no** se usan como contratos de API (regla dura): los schemas `extra="forbid"` llegan con cada módulo y nunca exponen `password_hash`.

### D6 — Migración 1 (autogenerada)
- Se genera con `alembic revision --autogenerate -m "esquema inicial"` contra una base **vacía** (contenedor de desarrollo). Docstring/encabezado: *"Generada con --autogenerate y revisada a mano antes de aplicarla (C-03). No contiene datos: el catálogo estado_orden queda vacío (lo carga seed.py)."*
- Checklist de revisión (se anota en la tarea): 13 `create_table` en orden de dependencias; `sa.Identity`; `TIMESTAMPTZ`; `NUMERIC(p,s)`; los 3 índices parciales con su `postgresql_where`; los 10 CHECK con nombre; `server_default`s; ningún tipo `sqlmodel.*`; `downgrade` que borra índices y tablas en orden inverso; ninguna tabla `c02_*`.
- Se permiten **sólo** ediciones cosméticas (comentario, orden) — cualquier diferencia de contenido se corrige en el modelo y se regenera, para que el test de sincronía (D9) siga siendo la verdad.

### D7 — Migración 2 (a mano): función + disparadores de sólo-agregado
```sql
CREATE FUNCTION rechazar_modificacion_solo_agregado() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'La tabla % es de sólo agregado: % no permitido', TG_TABLE_NAME, TG_OP
    USING ERRCODE = 'P0001';
END $$;
CREATE TRIGGER solo_agregado_<tabla> BEFORE UPDATE OR DELETE ON <tabla>
  FOR EACH ROW EXECUTE FUNCTION rechazar_modificacion_solo_agregado();   -- x3
```
- `downgrade`: `DROP TRIGGER` x3 y `DROP FUNCTION`. Encabezado: *"Escrita a mano: autogenerate no detecta funciones ni disparadores (C-03, KB 04 §Migraciones)."* `down_revision` = migración 1. Las tres tablas en una constante de la migración (no importa los modelos: una migración no debe depender del código vivo).
- **Por fila** (`FOR EACH ROW`): un `DELETE`/`UPDATE` sin filas afectadas no falla (no hay nada que proteger); con filas, falla en la primera. **Alternativa** `FOR EACH STATEMENT` → rechazaría también sentencias que no tocan filas; sin beneficio; descartada.
- **TRUNCATE no se bloquea** (discrepancia 1): los disparadores de fila no se ejecutan en TRUNCATE; el seed (C-11) lo necesita. Los usuarios de la API no tienen forma de emitir TRUNCATE. Defensa en profundidad con permisos de rol queda fuera (DD-04).
- `ERRCODE P0001` (`raise_exception`): con asyncpg llega como `RaiseError` → SQLAlchemy `DBAPIError`/`InternalError`, **no** `IntegrityError`; así un bug que intente modificar historial no se disfraza de 409 por el traductor genérico de RN-18. Mensaje en español con tabla y operación (lo que muestra la evidencia `psql` de C-14).
- La función se crea sin calificar esquema: queda en el primero del `search_path` (público en desarrollo; el esquema efímero en tests).

### D8 — `migrations/env.py`
- `from app.modules.modelos import metadata` → `target_metadata = metadata`. Opciones de `context.configure`: `compare_type=True` (default en Alembic ≥1.12; explícito por claridad) y `compare_server_default=True` para que la sincronía (D9) detecte defaults.
- **Conexión inyectable** (receta "sharing a connection" de Alembic): si `config.attributes.get("connection")` trae una conexión síncrona, `env.py` corre `do_run_migrations(conexion)` directamente; si no, el camino actual (`asyncio.run` + motor asincrónico desde `Settings`). Permite a los tests migrar un esquema efímero dentro de su propio bucle sin `asyncio.run` anidado.
- `fileConfig(..., disable_existing_loggers=False)`: correr Alembic desde los tests no debe silenciar los loggers de la app/pytest.
- La URL se sigue calculando sólo desde `Settings` y sólo cuando no hay conexión inyectada (nunca de `alembic.ini`).
- **Alternativa** invocar `alembic` por subprocess en los tests con `-x esquema=...` → más lento, y obliga a pasar el esquema por argumentos; descartada.

### D9 — Tests: unitarios sobre metadata + integración sobre esquema **migrado** (no `create_all`)
- **Unitarios** (`test/unit/test_modelos.py`, sin base): `metadata.tables` == las 13 tablas exactas (y ninguna `c02_*`: el registry de prueba de C-02 no se mezcla); por tabla, columnas de KB 04 ⊆ columnas reales y `usuario` sin `rol`; columnas de dinero `Numeric` con precisión/escala y `python_type is Decimal`; fechas `DateTime(timezone=True)`; nulabilidad según D3; `configure_mappers()` sin errores; cada relación con `back_populates` recíproco y `lazy == "raise"`; `Usuario.cliente.property.uselist is False`. Guarda estática: ningún archivo de `app/` ni `main.py` contiene `create_all` (spec "arranque no crea tablas").
- **Integración** (`test/integration/`), dos fixtures nuevas en `conftest.py`, reutilizando `settings_db` (skip / `--exigir-db`):
  - `aplicar_migraciones(esquema, destino)` / `revertir(...)`: crea motor `NullPool` con `search_path` del esquema y, dentro de `conexion.run_sync`, llama `command.upgrade(cfg, destino)` con `cfg.attributes["connection"]` (D8). `cfg = Config(RAIZ / "alembic.ini")`.
  - **`esquema_migrado`** (ámbito **sesión**, fixture síncrona que usa `asyncio.run`, igual que `settings_db`): crea `c03_mig_<hex>`, migra a `head` una vez, y lo borra (`DROP SCHEMA ... CASCADE`) al terminar la sesión. Evita migrar 13 tablas por cada test de restricción y esquiva los problemas de `loop_scope` de fixtures asíncronas de sesión.
  - **`conexion_migrada`** (ámbito función): motor con `search_path` = esquema migrado, conexión con transacción externa que se **revierte** al final → cada test parte del esquema vacío y no deja filas. Cada violación se prueba dentro de un `SAVEPOINT` (`begin_nested`) para poder seguir usando la conexión y triangular (válido/ inválido) en el mismo test.
  - Los tests de **migraciones** (ida/vuelta/ida, revertir sólo la 2, sincronía) usan su **propio** esquema efímero por test (`esquema_prueba` de C-02 sin `create_all`), porque modifican el esquema.
- **Por qué esquema migrado y no `create_all` de los modelos**: el disparador sólo existe en la migración 2, y lo que se corrige es el esquema que produce Alembic; `create_all` probaría otra cosa. **Por qué esquema efímero y no una base aparte**: reutiliza la infraestructura de C-02, no requiere privilegio `CREATEDB` y aísla de los datos de desarrollo. Alembic crea `alembic_version` y la función en el primer esquema del `search_path` → todo queda dentro del esquema efímero.
- **Sincronía**: tras `upgrade head`, `alembic.autogenerate.compare_metadata(MigrationContext.configure(conexion, opts={"compare_type": True, "compare_server_default": True}), metadata)` debe devolver `[]`.
- **FK indexadas**: consulta a `pg_constraint (contype='f')` × `pg_index` del esquema: toda FK de una columna es `indkey[0]` de algún índice.
- **Violaciones**: `pytest.raises(IntegrityError)` + aserción sobre `constraint_name` (nombre de la convención D2) o sqlstate (`23505` unique, `23514` check, `23503` FK, `23502` not null); parametrizado por regla con el caso inválido y el borde válido (TDD: triangulación).
- **Navegación**: con `crear_fabrica_sesiones` de la app sobre la conexión migrada: `selectinload(Cliente.vehiculos)` devuelve vehículos y `vehiculo.cliente is cliente`; sin precarga, acceder lanza `InvalidRequestError`; `joinedload(Usuario.cliente)` devuelve un objeto; orden con 2 ítems vía relación persiste ambos. Un caso con `SoftDeleteRepository(session, Vehiculo)` confirma que los modelos encajan con los repositorios de C-02 (PK de una columna, `borrado_en`).

### D10 — `main.py`
Agrega `import app.modules.modelos  # noqa: F401` (mapeos completos al arrancar; sin efectos sobre la base). No crea tablas. `test/unit/test_main.py` (C-01) debe seguir verde: importar modelos no requiere configuración.

## Risks / Trade-offs

- [**Autogenerate omite o deforma algo** (índice parcial sin `WHERE`, `server_default` renderizado distinto, tipo `sqlmodel`)] → checklist de revisión (D6) + test de sincronía `compare_metadata == []` + tests de cada violación contra el esquema migrado.
- [**`compare_server_default` con falsos positivos** (`now()` vs `CURRENT_TIMESTAMP`, `'0'::integer`)] → si aparecen, se normaliza la expresión en el modelo (`text("now()")`, `text("0")`); como último recurso se desactiva sólo esa comparación y se documenta en el test.
- [**Convención de nombres fijada tarde** (si algún modelo se importa antes de `app/core/models.py`)] → cada `models.py` importa primero `app.core.models`; test unitario que verifica nombres de restricciones concretos (`ck_vehiculo_anio_rango`, `uq_usuario_email`).
- [**Ciclos o nombres duplicados entre módulos** al resolver relaciones por texto] → registro central + `configure_mappers()` en test unitario.
- [**`lazy="raise"` rompe código de C-05+ que olvide precargar**] → deseado (falla en tests, no en producción); documentado en docstrings de `models.py`.
- [**TRUNCATE no bloqueado**] → aceptado (discrepancia 1, D7); el C-14 de la KB sólo pide UPDATE/DELETE; anotado para C-11/C-12.
- [**Esquema de sesión huérfano** si pytest se interrumpe] → prefijo `c03_mig_` reconocible; borrarlo a mano es inocuo. Igual riesgo ya aceptado en C-02.
- [**`env.py` importa la app**] → la generación de migraciones depende de que los modelos importen sin efectos; garantizado por D1 (sin I/O al importar).
- [**`email` UNIQUE sensible a mayúsculas**] → la normalización es de C-05; si se quisiera en base, un índice único sobre `lower(email)` es aditivo (no rompe nombres).
- [**Migración 2 en un esquema distinto de `public`**] → la función se resuelve por `search_path` al crear el disparador (queda ligada por OID); probado en el esquema efímero.

## Migration Plan

1. Con la base de desarrollo **vacía** (`docker compose up -d postgres`): `alembic revision --autogenerate -m "esquema inicial"` → revisar (D6) → `alembic upgrade head`.
2. Escribir la migración 2 a mano → `alembic upgrade head` → `alembic downgrade base` → `alembic upgrade head` (verificación manual, además de los tests).
3. Rollback: `alembic downgrade base` deja la base sin tablas de la app; revertir código = borrar `models.py`, `app/core/models.py`, `app/modules/modelos.py`, las dos versiones y restaurar `env.py`/`main.py`/`conftest.py` de C-02.
4. No hay datos previos que preservar.

## Open Questions

- Ninguna bloqueante. Pendiente de **aprobación humana** (governance CRITICO): D1, D3, D5, D7 (TRUNCATE permitido), D8 y D9.
