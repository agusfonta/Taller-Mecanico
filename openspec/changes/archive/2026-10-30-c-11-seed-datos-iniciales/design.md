# Design — C-11 `seed-datos-iniciales`

> Governance **ALTO** (usuarios, contraseñas y borrado total de datos). Las decisiones marcadas al final requieren aprobación antes de `/opsx:apply`.

## Context

- La migración 1 crea `estado_orden` vacío; la 2 instala el disparador de sólo-agregado `BEFORE UPDATE OR DELETE ... FOR EACH ROW` en `historial_estado_orden`, `movimiento_stock` e `historial_precio_repuesto`. Su docstring ya anticipa que `seed.py` vacía con `TRUNCATE ... RESTART IDENTITY CASCADE` (los disparadores de fila no corren en `TRUNCATE`), y `test/integration/test_solo_agregado.py::test_truncate_cascade_esta_permitido_para_el_seed` lo prueba.
- Piezas reutilizables ya archivadas:
  - `app/core/config.py` (`Settings`, exige `JWT_SECRET_KEY` y `POSTGRES_PASSWORD`), `app/core/database.py` (`crear_motor`, `crear_fabrica_sesiones`), `app/core/unit_of_work.py` (`UnitOfWork`: commit al salir, rollback ante excepción, no cierra la sesión).
  - `app/core/security.py`: `ServicioContrasenas` (único punto que llama a bcrypt, `to_thread` + semáforo por instancia; su docstring ya prevé crearlo "en el lifespan o en `seed.py`") y `crear_servicio_contrasenas(settings)` con `BCRYPT_ROUNDS`.
  - Repositorios (`add` hace `flush`, nunca `commit`) de usuarios, clientes, repuestos y órdenes; `mover_stock` (`app/modules/repuestos/stock.py`), punto único de escritura de stock con `MOTIVO_STOCK_INICIAL = "Stock inicial"` y el protocolo `ConStock`.
  - `app/modules/modelos.py` (registra todos los mapeos), `EstadoOrdenCodigo`, `Rol`, `normalizar_patente`.
  - Tests: `test/integration/conftest.py` (`esquema_auth` migrado una vez por sesión, `motor_auth` que hace `TRUNCATE` de las 13 tablas al terminar, `settings_auth` con bcrypt de 4 rondas, `AyudantesAuth`), y `test/integration/ordenes/ayudantes.py::escenario_c11`, réplica a mano del seed que C-10 usó para probar la atomicidad de `terminar`.
- `POST /ordenes/{id}/terminar` ya responde 409 `Stock insuficiente para el repuesto {codigo}` revirtiendo todo, y procesa los ítems por `repuesto_id` ascendente (C-10 D3/D5-b).
- Base de desarrollo/test: el PostgreSQL 16 del `docker-compose.yml` (puerto del `.env`, 5433 en esta máquina). Los tests de integración nunca usan el esquema `public`: crean esquemas efímeros y migran con Alembic.

## Goals / Non-Goals

**Goals**
- `python seed.py` deja la base en el estado exacto de la spec `datos-iniciales`, atómica e idempotentemente, reutilizando el código existente (sin duplicar hashing, stock ni modelos).
- El núcleo del seed es invocable sobre cualquier fábrica de sesiones para probarlo contra PostgreSQL real en un esquema efímero.
- Guarda mínima contra correrlo por error sobre una base no local.

**Non-Goals**
- Archivos `.http`, `test/solo_agregado.sql`, README y evidencias C-14/C-15 (C-12).
- Cambios de esquema, migraciones, ni nuevas rutas o módulos en `app/`.
- Seed "incremental" o datos de volumen.

## Decisions

### D1 — Mecanismo: sesión ORM + repositorios existentes + `mover_stock`, en un único UoW

`seed.py` es su propia raíz de composición (como el lifespan): construye `Settings`, motor, fábrica de sesiones y `ServicioContrasenas`, abre **una** sesión y **un** `SeedUoW(UnitOfWork)` que agrega los repositorios existentes sobre esa sesión (`usuarios`, `asignaciones`, `eventos`, `clientes`, `vehiculos`, `repuestos`, `movimientos`, `precios`, `ordenes`, `items`, `historial`). `SeedUoW` cumple el protocolo `ConStock` (`repuestos` + `movimientos`), así el stock inicial pasa por `mover_stock`.

- **Por qué no SQL crudo**: duplicaría reglas que ya viven en código (stock + movimiento juntos, `Decimal`, nombres de motivo) y no ejercitaría los modelos; el SQL sólo se usa para lo que el ORM no expresa (`TRUNCATE`, `SET LOCAL lock_timeout`).
- **Por qué no los servicios**: cada servicio abre su propio UoW y exige un `UsuarioActual`; componer varios rompería la atomicidad (varias transacciones) y generaría eventos de seguridad que la KB no pide (sólo una línea `SISTEMA`). Los servicios tampoco crean órdenes ya en EN_REPARACION.
- El catálogo `estado_orden` no tiene repositorio de escritura (spec `estados-orden`: la app sólo lo lee); el seed lo inserta con `session.add_all` + `flush` dentro del mismo UoW. `seed.py` no es código de la app.
- Las reglas de capas se respetan: los repositorios sólo hacen `flush`; el único `commit` es el del `UnitOfWork` al salir del `async with`; el seed no cierra la sesión dentro del UoW (la cierra el `async with fabrica()` que la creó).

### D2 — Vaciado y carga en la misma transacción

Dentro del `async with uow`: (1) `SET LOCAL lock_timeout = '5s'`; (2) `TRUNCATE <13 tablas> RESTART IDENTITY CASCADE`; (3) carga. `TRUNCATE` es transaccional en PostgreSQL: si la carga falla, el rollback restaura datos y secuencias previos. La lista de tablas sale de `SQLModel.metadata.tables` tras importar `app.modules.modelos` (nunca de la entrada del usuario), entrecomillada; los identificadores no admiten parámetros ligados y no hay valores interpolados. `alembic_version` no se toca. El `lock_timeout` evita quedar colgado si el servidor tiene transacciones abiertas: falla con mensaje claro ("cerrar el servidor o reintentar").

### D3 — Hashes antes de la transacción

Las 7 contraseñas se hashean con `ServicioContrasenas.hashear` vía `asyncio.gather` (el semáforo de la instancia limita a `BCRYPT_MAX_CONCURRENCY`) **antes** de abrir la sesión/UoW: ninguna transacción queda abierta mientras corre bcrypt. Costo = `BCRYPT_ROUNDS` del entorno (12 por defecto; 4 en los tests vía `settings_auth`).

### D4 — Datos: constantes en `seed.py`, orden de inserción fijo

Todo el contenido vive en constantes de módulo de `seed.py` (tuplas/dataclasses inmutables). Con `RESTART IDENTITY` y orden de inserción fijo, los ids son deterministas (los usa C-12):

| Tabla | Orden / ids |
|---|---|
| `estado_orden` | PENDIENTE 1, EN_REPARACION 2, TERMINADA 3 (final), CANCELADA 4 (final); descripciones "Pendiente", "En reparación", "Terminada", "Cancelada" |
| `usuario` | 1 admin, 2 admin2, 3 recepcion, 4 mecanico, 5 mecanico2, 6 cliente, 7 nuevo (`debe_cambiar_password=true`); `activo=true`, `password_cambiada_en` nulo; nombres de demo |
| `asignacion_rol` | una por usuario, `vence_en`, `revocada_en` y `otorgada_por` nulos (SU-06) |
| `cliente` | 1 Laura (usuario 6), 2 Jorge (sin usuario); documentos y teléfonos ficticios distintos |
| `vehiculo` | 1 y 2 de Laura, 3 de Jorge; patentes ya normalizadas (p. ej. `AB123CD`, `AC456DE`, `AD789EF`), anios válidos |
| `repuesto` | 1 `FIL-001` "Filtro de aceite" 8500.00; 2 `FRE-010` "Pastillas de freno" 25000.00; 3 `BUJ-001` "Bujía" 3000.00; 4 `ACE-530` "Aceite por litro" 6000.00; todos creados con stock 0 y luego `mover_stock(+N, "Stock inicial", usuario_id=1)` → 10, 4, 2, 20 |
| `historial_precio_repuesto` | repuesto 1, 8000.00 → 8500.00, usuario 1 |
| `orden_trabajo` | 1 PENDIENTE, vehículo 1, sin mecánico, ítems 1×`FIL-001` + 4×`ACE-530` (total 32500.00); 2 EN_REPARACION, vehículo 3, mecánico 4, ítems 1×`FIL-001` + 4×`BUJ-001` (total 20500.00) |
| `historial_estado_orden` | orden 1: `NULL→PENDIENTE` (usuario 3); orden 2: `NULL→PENDIENTE` (3), `PENDIENTE→EN_REPARACION` (4) |
| `evento_seguridad` | actor `SISTEMA`, acción "Carga de los datos iniciales" |
| `intento_acceso` | vacía |

- Precios unitarios copiados del repuesto y totales con `Decimal` (nunca `float`); un test verifica total = Σ cantidad × precio.
- El filtro (id 1) precede a la bujía (id 3): al terminar la orden 2, `mover_stock` descuenta primero el filtro y falla en la bujía, demostrando el rollback total del caso C-11 (mismo diseño que `escenario_c11` de C-10).
- Sólo `FRE-010` contiene "freno" (caso C-16: `q=freno&size=1` → total 1).
- Patentes: constantes ya normalizadas; un test unitario verifica `normalizar_patente(p) == p` y unicidad.
- Autoría de filas de sólo-agregado con `usuario_id` NOT NULL: movimientos e historial de precio → admin (1); historial de órdenes → recepción (alta) y mecánico (inicio), como habría ocurrido por la API.

### D5 — Contraseñas del seed (DD-15/DD-16)

Siete contraseñas fijas, ficticias, distintas, de 8 a 72 bytes, definidas **sólo** como constante en `seed.py` (diccionario email → contraseña). No se escriben en este diseño, en `env.example`, en el README ni en los tests: los tests importan la constante desde el módulo `seed` (sin duplicar el literal). La salida del seed lista los emails creados, nunca contraseñas ni hashes. C-12 podrá indicar en el README "credenciales de demo: ver `seed.py`".

### D6 — Estructura de `seed.py` (testeable sin tocar `public`)

```
seed.py
  DATOS (constantes: ESTADOS, USUARIOS, CONTRASENAS_SEED, CLIENTES, REPUESTOS, ORDENES, ...)
  class SeedUoW(UnitOfWork)                         # repositorios existentes, misma sesión
  async def cargar_datos_iniciales(fabrica, contrasenas) -> ResumenSeed   # núcleo: hash → UoW(truncate + carga)
  def destino_permitido(host: str, permitir_remoto: bool) -> bool         # pura
  async def main(argv: list[str] | None = None) -> int                    # CLI: Settings, guarda, motor, núcleo, dispose
  if __name__ == "__main__": raise SystemExit(asyncio.run(main()))
```

- `main` usa `argparse` (`--permitir-remoto`), construye `Settings()` (errores de configuración → mensaje y código 2), imprime `host:puerto/base`, aplica la guarda, crea motor con `crear_motor`, corre el núcleo, imprime el resumen y hace `engine.dispose()` en `finally`.
- Errores esperables → mensaje sin traza y código 1: tablas inexistentes (`UndefinedTableError` → "correr `alembic upgrade head`"), base inalcanzable, `lock_timeout`. Nunca se imprime `database_url` ni `model_dump()` de `Settings`.
- No hay `create_all` ni migraciones dentro del seed.

### D7 — Guarda de destino (a aprobar)

`destino_permitido` acepta `localhost`, `127.0.0.1`, `::1` (sin distinguir mayúsculas). Cualquier otro host requiere `--permitir-remoto`; sin ella, el seed sale con código 3 **antes** de abrir conexión. Se descartó una confirmación interactiva (`¿Seguro? [s/N]`) porque la KB 11 indica correr `python seed.py` antes de cada archivo `.http` y C-12 lo automatiza; un prompt rompería ese flujo. Alternativa considerada: variable `SEED_PERMITIDO=true` — descartada porque el spec `configuracion` prohíbe variables `SEED_*`.

### D8 — Tests (Strict TDD, PostgreSQL real)

- **Unit (`test/unit/test_seed_datos.py`, `test_seed_cli.py`)**: coherencia de las constantes (7 usuarios con los roles de la KB, `nuevo` con cambio obligatorio, contraseñas 8..72 bytes distintas, patentes normalizadas y únicas, códigos únicos, totales = Σ con `Decimal`, sólo `FRE-010` contiene "freno", ningún `float`), `destino_permitido` (local/remoto/bandera), `main` con host remoto sin bandera → código 3 sin crear motor (se verifica con un `crear_motor` sustituido que falla si se llama), y que `env.example`/otros archivos versionados no contengan las contraseñas del seed.
- **Integración (`test/integration/seed/`)**: un `conftest.py` local sobrescribe `app_auth` montando todos los routers (patrón de `ordenes/conftest.py`), y un fixture `seed_cargado` que corre `cargar_datos_iniciales(crear_fabrica_sesiones(motor_auth), crear_servicio_contrasenas(settings_auth))` sobre el esquema efímero `esquema_auth` (migrado con Alembic; el `TRUNCATE` del teardown de `motor_auth` lo deja vacío). **Nunca se ejecuta el seed contra `public`.**
  - Estado conocido: conteos por tabla, ids, valores (catálogo, roles, stock = Σ movimientos, historial de precios, órdenes, totales, historiales, evento `SISTEMA`, `intento_acceso` vacía), hashes verificados con `ServicioContrasenas.verificar` contra la constante.
  - Idempotencia: snapshot (sin marcas de tiempo ni hashes) → modificar datos → re-seed → snapshot igual; además re-seed sobre datos con filas en las tablas de sólo-agregado (prueba que `TRUNCATE` las vacía pese al disparador).
  - Atomicidad: forzar una falla tras el `TRUNCATE` (p. ej. sustituir un dato por uno inválido vía `monkeypatch` de una constante) → excepción y los datos previos siguen.
  - Catálogo antes que órdenes: se verifica por éxito de la carga con FK + orden de inserción (los SQL capturados con un listener `before_cursor_execute`: el primer INSERT tras el TRUNCATE es en `estado_orden`).
  - Sólo-agregado intacto: UPDATE/DELETE sobre las 3 tablas tras el seed → rechazados.
  - HTTP sobre el seed (login real con las contraseñas del seed): login de los 7 + `/auth/yo` roles; `nuevo` → 403 fuera de `/auth` (C-09); cliente ve orden 1 (200) y no la 2 (403) (C-06); `mecanico2` no lista la orden 2 (DD-18); `GET /estados-orden` (C-17); `q=freno&size=1` (C-16); `/repuestos/1/precios` una línea (C-18); **C-11**: `mecanico` termina la orden 2 → 409 con `BUJ-001`, snapshot de orden/stock/movimientos/historial idéntico; **C-12**: admin repone bujías, `mecanico` termina → 200 con descuentos, 2 movimientos con `orden_id=2` y línea `EN_REPARACION→TERMINADA`.
- El resto de los casos C-01..C-19 ya tiene cobertura por módulo (C-05..C-10) con datos propios; C-12 los reproducirá en `.http` sobre este seed.
- **Prueba manual (Verify, con aprobación del usuario)**: `python seed.py` dos veces contra la base Docker de desarrollo — destruye los datos de desarrollo, por eso se pide confirmación.

## Risks / Trade-offs

- **Correr el seed sobre datos reales** → borra todo. Mitigación: guarda D7 + impresión del destino; riesgo residual con una base "local" que no sea de desarrollo (aceptado: proyecto académico).
- **`TRUNCATE` necesita `ACCESS EXCLUSIVE`**: con el servidor corriendo y transacciones abiertas puede esperar → `lock_timeout` 5 s y mensaje.
- **Contraseñas de demo en el repo** (DD-15, aceptado): ficticias, sólo para desarrollo/corrección.
- **Acoplamiento a ids fijos** (C-12, tests) → depende del orden de inserción y `RESTART IDENTITY`; los tests de estado conocido fijan los ids.
- **Desfase con `escenario_c11` de C-10** (réplica manual del seed): queda como está; se puede reemplazar en C-12 por el seed real. No se toca en este change.
- **Costo de bcrypt 12** → ~7 hashes, ~1–2 s con concurrencia 4: aceptable.
- **`Settings()` exige `JWT_SECRET_KEY`** aunque el seed no lo use: se mantiene (mismo `.env` que la app; no se relaja la validación).

## Migration Plan

Sin cambios de esquema. Puesta en marcha (KB 07/08): `alembic upgrade head` → `python seed.py` → `uvicorn`. Rollback: no aplica (el seed es repetible; para volver a un estado previo hay que restaurar un respaldo propio).

## Decisiones a aprobar (resumen)

1. **D1** — Seed con sesión ORM + repositorios existentes + `mover_stock` dentro de un único `SeedUoW` (no SQL crudo, no servicios); catálogo insertado con `session.add_all`.
2. **D2** — `TRUNCATE` de las 13 tablas + carga en la **misma** transacción (atómico, restaura si falla) con `SET LOCAL lock_timeout = '5s'`.
3. **D3** — Los 7 hashes con `ServicioContrasenas` (`BCRYPT_ROUNDS`) concurrentes bajo su semáforo, antes de abrir la transacción.
4. **D4-a** — Código de la bujía `BUJ-001` (la KB no lo fija) y precios de demo: filtro 8500.00, pastillas 25000.00, bujía 3000.00, aceite 6000.00.
5. **D4-b** — Orden 2 con **1 filtro + 4 bujías** (la KB sólo exige las 4 bujías; el filtro demuestra que el rollback también deshace un descuento ya aplicado). Orden 1 con 1 filtro + 4 litros de aceite.
6. **D4-c** — Ids fijos (usuarios 1..7, clientes 1..2, vehículos 1..3, repuestos 1..4, órdenes 1..2) como contrato para C-12.
7. **D4-d** — Autoría: movimientos e historial de precio → `admin@example.com`; historial de órdenes → recepción (alta) y mecánico (inicio); `otorgada_por` nulo en las asignaciones.
8. **D4-e** — Una sola línea de `evento_seguridad` (la de `SISTEMA`): el seed no registra eventos por cada alta de usuario/rol.
9. **D5** — Contraseñas fijas, distintas, ≥ 8 caracteres, sólo en `seed.py`; los tests las importan del módulo; la salida nunca las imprime. Los valores concretos los elige `apply` y se revisan en el diff.
10. **D7** — Guarda: host no local requiere `--permitir-remoto` (código 3 sin conectar); sin prompt interactivo ni variable `SEED_*`.
11. **D8** — Tests de integración sobre el esquema efímero `esquema_auth` (nunca `public`); la corrida manual contra la base Docker de desarrollo queda en Verify y requiere tu aprobación porque borra sus datos.
