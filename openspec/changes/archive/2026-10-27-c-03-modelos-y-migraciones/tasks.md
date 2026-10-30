# Tasks — C-03 `modelos-y-migraciones`

> ⚠️ **Governance CRITICO**: no empezar sin aprobación humana explícita de `design.md` (D1, D3, D5, D7, D8, D9 en particular).
> Strict TDD: en cada tarea de comportamiento, primero el test en ROJO (ejecutado y fallando), luego el mínimo código en VERDE, luego TRIANGULAR (≥ 2 casos por comportamiento: violación + borde válido) y REFACTOR con la suite en verde tras cada paso.
> Skills a cargar: `postgresql-table-design`, `postgres-patterns`, `sqlalchemy-alembic-expert-best-practices-code-review`, `database-migration` (traducir a Alembic), `python-testing-patterns`, `sql-optimization-patterns`. Referencias: `design.md` (D1..D10), `specs/*/spec.md`, `knowledge-base/04_modelo_de_datos.md` (nombres obligatorios).
> Nunca leer ni imprimir el `.env`; credenciales y puerto sólo vía `Settings`. Sin build, commit ni push. No crear `seed.py` (C-11) ni schemas de API (C-05+).

## 1. Safety net

- [x] 1.1 Ejecutar `pytest -m "not integration"` y `pytest -m integration --exigir-db` (con `docker compose up -d postgres`) y registrar la línea base de C-01/C-02 ("N passed, 0 skipped"); si algo falla, DETENER y reportar como falla preexistente (no corregir).

## 2. Base común de modelos (`app/core/models.py`) — unitarios

- [x] 2.1 RED: `test/unit/test_modelos_base.py`: tras importar `app.core.models`, `SQLModel.metadata.naming_convention` contiene las claves `ix`, `uq`, `ck`, `fk`, `pk` con los patrones de D2; y una tabla de prueba declarada en un `registry()` propio con `CheckConstraint(..., name="x")` NO recibe la convención (aislamiento de `BasePrueba`); ejecutar y confirmar que FALLA.
- [x] 2.2 GREEN: crear `app/core/models.py` con la convención (D2) y los helpers `pk_identidad`, `fk`, `fecha`, `dinero`, `texto` (D3); confirmar VERDE.
- [x] 2.3 TRIANGULAR helpers: `dinero(10,2)` → `Numeric(10,2)` con `asdecimal=True` y `python_type is Decimal`; `fecha()` → `DateTime(timezone=True)`; `texto()` → `Text` (no `AutoString`); `pk_identidad()` → `BigInteger` con `Identity(always=False)`; `fk("usuario.id", nullable=True)` nulo permitido; confirmar VERDE. REFACTOR: `__all__`, docstrings; VERDE.

## 3. Modelos por módulo y registro — unitarios (sin base)

- [x] 3.1 RED: `test/unit/test_modelos.py`: importar `app.modules.modelos` y verificar que `metadata.tables` es **exactamente** el conjunto de las 13 tablas de KB 04 (sin `c02_*`); ejecutar y confirmar que FALLA.
- [x] 3.2 GREEN: crear `app/modules/usuarios/models.py` (`Rol` StrEnum, `Usuario`, `AsignacionRol`, `IntentoAcceso`, `EventoSeguridad`), `clientes/models.py`, `repuestos/models.py`, `ordenes/models.py` (sólo columnas, PK y FK; sin relaciones todavía) y `app/modules/modelos.py` (registro, D1); confirmar VERDE.
- [x] 3.3 RED → GREEN columnas: test parametrizado por tabla con la lista de columnas de KB 04 ⊆ columnas reales; `usuario` sin `rol`; `estado_orden` con PK `codigo` de tipo texto y el resto con PK `id`; confirmar VERDE.
- [x] 3.4 RED → GREEN tipos y nulabilidad: columnas de dinero (`precio`, `precio_unitario`, `precio_anterior`, `precio_nuevo` → (10,2); `total` → (12,2)) con `python_type is Decimal`; todas las fechas `timezone=True`; columnas nulas exactamente las de D3 (parametrizado: nulas y una muestra de obligatorias por tabla); `ip` es `Text`; confirmar VERDE.
- [x] 3.5 RED → GREEN restricciones declaradas: nombres esperados presentes en la metadata (`uq_usuario_email`, `uq_cliente_documento`, `uq_cliente_usuario_id`, `uq_estado_orden_posicion`, `uq_item_orden_orden_id_repuesto_id`, `uq_vehiculo_patente_vigente`, `uq_repuesto_codigo_vigente`, `uq_asignacion_rol_abierta` con su `postgresql_where`, los 10 `ck_*` de D4, `ix_intento_acceso_email_ip_cuando` con columnas en orden); el CHECK de rol se arma desde `Rol` (agregar un valor al enum de prueba cambiaría el texto — verificar que contiene los 4 valores); confirmar VERDE.
- [x] 3.6 RED → GREEN FK: `orden_trabajo.estado`, `historial_estado_orden.desde_estado`/`hasta_estado` referencian `estado_orden.codigo`; cada FK de la tabla de D4 existe y apunta a la tabla correcta; ninguna con `ondelete` (`NO ACTION`); confirmar VERDE.
- [x] 3.7 Guarda estática: test que recorre `app/**/*.py` y `main.py` y verifica que ningún archivo contiene `create_all` (spec migraciones §Arranque no crea tablas); y que `test_estructura.py` (importar módulos sin secretos) sigue VERDE.

## 4. Relaciones (`lazy="raise"`, ambos extremos) — unitarios

- [x] 4.1 RED: en `test/unit/test_modelos.py`, test parametrizado con los 11 pares de D5: `configure_mappers()` sin error, cada relación existe con `back_populates` recíproco y `lazy == "raise"`; `Usuario.cliente` con `uselist is False`; `AsignacionRol.usuario` usa `usuario_id` (no `otorgada_por`); ejecutar y confirmar que FALLA.
- [x] 4.2 GREEN: declarar las relaciones con `Relationship(back_populates=..., sa_relationship_kwargs={"lazy": "raise", ...})`, referencias en texto e imports bajo `TYPE_CHECKING` (sin `from __future__ import annotations`); confirmar VERDE.
- [x] 4.3 TRIANGULAR: un objeto `OrdenTrabajo` transitorio con `items=[ItemOrden(...), ItemOrden(...)]` deja `item.orden is orden` (back_populates en memoria, sin base); REFACTOR (docstrings: "precargar en el repositorio con selectinload/joinedload"); `pytest -m "not integration"` VERDE completo.

## 5. `migrations/env.py` y `main.py`

- [x] 5.1 RED: `test/unit/test_env_migraciones.py`: leer `migrations/env.py` y verificar que importa la metadata del registro (`app.modules.modelos`) y no contiene `target_metadata = None`; ejecutar y confirmar que FALLA.
- [x] 5.2 GREEN: editar `env.py` (D8): `target_metadata = metadata`, `compare_type=True`, `compare_server_default=True` en ambos modos, rama de conexión inyectada (`config.attributes.get("connection")`), `fileConfig(..., disable_existing_loggers=False)`, URL desde `Settings` sólo si no hay conexión inyectada; confirmar VERDE. El comportamiento real se prueba en la sección 6.
- [x] 5.3 Agregar a `main.py` el import del registro de modelos (D10); verificar que `test/unit/test_main.py` y `test_lifespan.py` siguen VERDE.

## 6. Infraestructura de integración para migraciones (`test/integration/conftest.py`)

- [x] 6.1 Agregar helpers `aplicar_migraciones(settings, esquema, destino)` y `revertir_migraciones(...)` (motor `NullPool` con `search_path`, `conexion.run_sync` + `cfg.attributes["connection"]`, `Config(RAIZ / "alembic.ini")`), fixture `esquema_migrado` (sesión, síncrona con `asyncio.run`, `c03_mig_<hex>`, `DROP SCHEMA ... CASCADE` al final) y `conexion_migrada` (función, transacción externa revertida) según D9. Sin migraciones todavía, verificar con un test humo que `aplicar_migraciones(..., "head")` sobre un esquema efímero deja sólo `alembic_version` sin errores y que el esquema queda borrado al terminar → VERDE con `--exigir-db`.

## 7. Migración 1 (autogenerada) — integración

- [x] 7.1 RED: `test/integration/test_migraciones.py::test_upgrade_head_crea_las_13_tablas`: en un esquema efímero propio, `upgrade head` → `information_schema.tables` del esquema contiene las 13 tablas + `alembic_version`, y `estado_orden` (y el resto) con 0 filas; ejecutar y confirmar que FALLA (no hay migraciones).
- [x] 7.2 GREEN: con la base de desarrollo vacía, `alembic revision --autogenerate -m "esquema inicial"`; **revisar** el archivo con el checklist de D6 y anotar el resultado en el encabezado de la migración (comentario "generada con --autogenerate y revisada antes de aplicar"); sólo ediciones cosméticas (si algo está mal, corregir el modelo y regenerar); confirmar VERDE.
- [x] 7.3 RED → GREEN sincronía: `test_modelos_y_migraciones_sin_diferencias`: tras `upgrade head`, `compare_metadata(...) == []` con `compare_type` y `compare_server_default`; si hay falsos positivos de defaults, normalizar en el modelo (Riesgos de design) y regenerar; confirmar VERDE.
- [x] 7.4 TRIANGULAR: `test_downgrade_base_no_deja_nada` (tras `downgrade base`, ninguna de las 13 tablas ni índices de la app; `alembic_version` vacía) y `test_ida_vuelta_ida` (`upgrade head → downgrade base → upgrade head` sin error y mismo conjunto de tablas/índices/restricciones que la primera vez, comparando consultas a `pg_indexes` y `pg_constraint`); confirmar VERDE.
- [x] 7.5 Verificación manual con la CLI contra la base de desarrollo: `alembic upgrade head`, `alembic downgrade base`, `alembic upgrade head` sin errores; registrar la salida resumida en la tarea.

## 8. Restricciones del esquema migrado — integración (PostgreSQL real)

- [x] 8.1 RED: `test/integration/test_restricciones.py` (usa `conexion_migrada`, inserciones con `text()` y parámetros ligados, cada violación en `begin_nested`): unicidad de `email` → `IntegrityError` con `constraint_name == "uq_usuario_email"`; ejecutar y confirmar que FALLA si el esquema no lo garantiza (o, si ya pasa por la migración 1, documentar que el ROJO fue 7.1).
- [x] 8.2 TRIANGULAR unicidad (parametrizado, violación + caso válido): `documento`; `cliente.usuario_id` (dos nulos aceptados); `posicion`; ítem repetido en la misma orden vs. mismo repuesto en otra orden; confirmar VERDE.
- [x] 8.3 Unicidad parcial: patente vigente repetida → `uq_vehiculo_patente_vigente`; patente de un vehículo con `borrado_en` no nulo + otra vigente → aceptada; idem `codigo` de repuesto; asignación abierta duplicada → `uq_asignacion_rol_abierta`, y aceptada si la previa tiene `revocada_en`; confirmar VERDE.
- [x] 8.4 CHECKs (parametrizado con el nombre esperado de D4): rol `SUPERUSUARIO`/`CLIENTE`; `anio` 1949/1950/2100/2101; `precio` 0/0.01; `stock` -1/0 (por UPDATE); `total` -0.01/0; `cantidad` 0/1; `precio_unitario` 0/0.01; `movimiento_stock.cantidad` 0/-3/5; `precio_nuevo` 0; `precio_nuevo = precio_anterior`; confirmar VERDE.
- [x] 8.5 FK al catálogo y NOT NULL: catálogo vacío → orden rechazada por `fk_orden_trabajo_estado_estado_orden`; con `PENDIENTE` cargado en la transacción del test → aceptada; `estado = 'INEXISTENTE'` → rechazada; `historial_estado_orden` con `hasta_estado` inexistente → rechazada y `desde_estado` nulo aceptado; vehículo sin `patente` → sqlstate `23502`; orden sin `mecanico_id` y cliente sin `usuario_id` aceptados; borrar un repuesto con movimientos → rechazado (`23503`); confirmar VERDE.
- [x] 8.6 Tipos reales: insertar repuesto con precio `Decimal("8500.10")` y leerlo con la fábrica de sesiones de la app → `== Decimal("8500.10")` y tipo `Decimal`; consulta a `information_schema.columns` confirma `timestamp with time zone` en todas las fechas y `numeric` con precisión/escala de KB 04; confirmar VERDE.
- [x] 8.7 FK indexadas: `test_toda_fk_tiene_indice` con la consulta a `pg_constraint`/`pg_index` de D9 sobre el esquema migrado (lista vacía de FK sin índice) y `ix_intento_acceso_email_ip_cuando` con columnas `(email, ip, cuando)` en ese orden; confirmar VERDE. REFACTOR: helpers de inserción mínima por tabla (fábricas de filas válidas) en el propio módulo de test; VERDE.

## 9. Migración 2 (sólo-agregado, a mano) — integración

- [x] 9.1 RED: `test/integration/test_solo_agregado.py` parametrizado por (tabla × {UPDATE, DELETE}) sobre `conexion_migrada`: insertar fila válida (con sus padres), intentar la operación en `begin_nested` → `DBAPIError` cuyo mensaje contiene la tabla y la operación, y la fila sigue igual; ejecutar y confirmar que FALLA (los 6 casos).
- [x] 9.2 GREEN: crear a mano `migrations/versions/<rev>_solo_agregado.py` (D7) con encabezado "escrita a mano: autogenerate no detecta funciones ni disparadores", `down_revision` = migración 1, `upgrade` (función + 3 disparadores `BEFORE UPDATE OR DELETE ... FOR EACH ROW`) y `downgrade` (3 `DROP TRIGGER` + `DROP FUNCTION`); confirmar VERDE (el esquema de sesión se recrea en la próxima corrida).
- [x] 9.3 TRIANGULAR: INSERT aceptado en las 3 tablas; UPDATE de `repuesto.stock` aceptado (otras tablas no afectadas); `DELETE FROM movimiento_stock` sin condición con filas → rechazado; `TRUNCATE movimiento_stock, ... CASCADE` (en esquema efímero propio) → aceptado y tabla vacía (discrepancia 1); confirmar VERDE.
- [x] 9.4 Migraciones con la 2: `test_revertir_solo_la_segunda` (desde head, `downgrade -1` → tablas presentes, UPDATE en `movimiento_stock` aceptado, función inexistente en `pg_proc`); ampliar `test_downgrade_base_no_deja_nada` (sin función ni disparadores) y `test_historial_tiene_dos_migraciones` (`ScriptDirectory`: 2 revisiones, la 2.ª con `down_revision` = 1.ª, encabezados con los comentarios "autogenerada y revisada" / "escrita a mano"); re-ejecutar 7.3 (sincronía sigue `[]`) e ida/vuelta/ida; confirmar VERDE.

## 10. Navegación sobre la base — integración

- [x] 10.1 RED: `test/integration/test_navegacion.py` con `crear_fabrica_sesiones` sobre el esquema migrado: cliente con 2 vehículos leído con `selectinload(Cliente.vehiculos)` → 2 vehículos y `v.cliente is cliente`; ejecutar y confirmar que FALLA si falta algo (o documentar el ROJO de 4.1).
- [x] 10.2 TRIANGULAR: sin precarga, `cliente.vehiculos` → `InvalidRequestError` (lazy raise) y ninguna consulta emitida (contar con un listener `before_cursor_execute`); usuario con cliente leído con `joinedload(Usuario.cliente)` → objeto `Cliente` (no lista) y usuario sin cliente → `None`; orden nueva con 2 ítems agregada por la relación y confirmada con `UnitOfWork` → 2 filas en `item_orden` con su `orden_id`; `SoftDeleteRepository(session, Vehiculo)`: `soft_delete` y `get_by_id` → `None`, `get_by_id_including_deleted` → la fila; confirmar VERDE.

## 11. Verificación final

- [x] 11.1 Correr la suite completa: `pytest -m "not integration"` y `pytest -m integration --exigir-db` → todo VERDE y **0 skipped**; registrar los conteos frente a la línea base de 1.1.
- [x] 11.2 Revisión contra reglas duras y KB: nombres de tablas/columnas idénticos a KB 04; sin `float` para dinero; sin `create_all` en la app; sin secretos ni URL en `alembic.ini`/migraciones; modelos de tabla sin schemas de API; catálogo vacío tras migrar; anotar en este archivo cualquier desviación respecto de `design.md`.

## Notas de verificacion (11.1 / 11.2)

- Linea base 1.1: `pytest -m "not integration"` = 135 passed; `pytest --exigir-db` = 159 passed, 0 skipped.
- Final: `pytest -m "not integration"` = 305 passed; `pytest --exigir-db` = 390 passed, 0 skipped (85 de integracion).
- Migracion 1 autogenerada: la revision (checklist D6) no requirio correcciones; solo se agrego el comentario de encabezado.
- Desviaciones menores respecto de design.md: (a) helpers extra `entero` y `booleano` en `app/core/models.py` (ademas de los 5 de D3); (b) `test/integration/filas.py` (filas validas y `rechaza`/`acepta`) y `test_infra_migraciones.py` como infraestructura de tests; (c) `env.py` hace `connection.commit()` explicito tras `run_sync` en el camino asincronico; (d) gotcha de `lazy="raise"`: `selectinload(Cliente.vehiculos)` NO puebla `vehiculo.cliente`; para volver a la madre hay que encadenar `joinedload(Vehiculo.cliente)` (probado en `test_navegacion.py`).
- 11.2: sin `float` para dinero, sin `create_all` en la app, sin URL/secretos en `alembic.ini` ni migraciones, catalogo vacio tras migrar, nombres de KB 04 intactos.
