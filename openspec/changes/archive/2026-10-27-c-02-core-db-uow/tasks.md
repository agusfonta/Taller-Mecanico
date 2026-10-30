# Tasks — C-02 `core-db-uow`

> ⚠️ **Governance CRITICO**: no empezar sin aprobación humana explícita de `design.md` (D3, D5, D7 en particular).
> Strict TDD: en cada tarea de comportamiento, primero el test en ROJO (ejecutado y fallando), luego el mínimo código en VERDE, luego TRIANGULAR (≥ 2 casos por comportamiento) y REFACTOR con la suite en verde tras cada paso.
> Skills a cargar: `fastapi`, `async-python-patterns`, `sqlalchemy-alembic-expert-best-practices-code-review`, `python-testing-patterns`, `postgres-patterns`. Referencias: `design.md` (D1..D7), `specs/*/spec.md`.
> Nunca leer ni imprimir el `.env`; los tests toman credenciales y puerto sólo vía `Settings`. Sin build, commit ni push.

## 1. Safety net

- [x] 1.1 Ejecutar `pytest -m "not integration"` y registrar la línea base de C-01 ("N passed"); si algo falla, DETENER y reportar como falla preexistente (no corregir).

## 2. Paginación (`app/core/paginacion.py`) — unitarios

- [x] 2.1 RED: `test/unit/test_paginacion.py` con `test_calcular_paginas_*` parametrizado: (45,20)→3, (40,20)→2, (0,20)→1, (1,1)→1, (101,100)→2; ejecutar y confirmar que FALLA (módulo inexistente).
- [x] 2.2 GREEN: crear `paginacion.py` con constantes (20/100) y `calcular_paginas` (D6); confirmar VERDE.
- [x] 2.3 RED → GREEN → TRIANGULAR `verificar_pagina`: (page=1,total=0)→1 OK; (page=2,total=0) y (page=2,total=1,size=1) → `PaginaFueraDeRangoError`; (page=3,total=45,size=20) OK; `ParametrosPaginacion(page=3,size=20).offset == 40`; confirmar VERDE.
- [x] 2.4 RED → GREEN `Pagina[T]`: `Pagina.crear(items, total, params)` serializa exactamente `{items,total,page,size,pages}` (comparar `set(model_dump())`) y `pages` coincide con `calcular_paginas`; confirmar VERDE.
- [x] 2.5 RED → GREEN dependencia HTTP: en `test/unit/test_paginacion_http.py`, app de prueba con una ruta que usa `PaginacionDep` (por ahora `FastAPI()` + handler registrado a mano; se migra a `crear_app` en 5.4): sin params → `page=1,size=20`; `size` 0/101/500, `page` 0/`abc` → 422 (parametrizado); ruta que lanza `PaginaFueraDeRangoError` → 422 con `detail` propio y sin traza; implementar `parametros_paginacion`, `PaginacionDep`, `manejar_pagina_fuera_de_rango`; confirmar VERDE.
- [x] 2.6 REFACTOR: `__all__`, docstrings (uso previsto count→verificar→list, D6); `pytest test/unit/test_paginacion*.py` VERDE.

## 3. Unit of Work (`app/core/unit_of_work.py`) — unitarios

- [x] 3.1 RED: `test/unit/test_unit_of_work.py` con una `SesionEspia` (métodos async `commit`/`rollback`/`close` que registran llamadas; `commit` configurable para lanzar): bloque sin error → `["commit"]`; ejecutar y confirmar que FALLA.
- [x] 3.2 GREEN: `UnitOfWork` con `__aenter__`/`__aexit__` (D5); confirmar VERDE.
- [x] 3.3 TRIANGULAR: excepción en el bloque → `["rollback"]` y `pytest.raises` recibe **la misma** instancia; `commit` que lanza → `["commit","rollback"]` y se propaga el error del commit; `asyncio.CancelledError` en el bloque → rollback y se propaga; en todos los casos `close` NO aparece; `__aenter__` devuelve la propia UoW; confirmar VERDE.
- [x] 3.4 RED → GREEN UoW de módulo: subclase de prueba que crea dos repositorios con la sesión recibida → ambos `repo.session is uow.session`; confirmar VERDE.
- [x] 3.5 Guarda estática: test que lee `app/core/unit_of_work.py` y verifica que no contiene `.close(`; REFACTOR (docstring "no reentrante, no cierra la sesión", `__all__`); VERDE.

## 4. Motor, fábrica y sesión (`app/core/database.py`) — unitarios

- [x] 4.1 RED: `test/unit/test_database.py`: con `Settings(_env_file=None, ...)` (secretos de `secretos_validos`) `crear_motor` devuelve `AsyncEngine` con `pool.size() == 5`, `pool._max_overflow == 10`, `echo is False` (y `await motor.dispose()` al final); ejecutar y confirmar que FALLA.
- [x] 4.2 GREEN: implementar `crear_motor` (D1: `pool_size`, `max_overflow`, `echo`, `pool_pre_ping=True`); confirmar VERDE.
- [x] 4.3 TRIANGULAR: `DB_POOL_SIZE=2`, `DB_MAX_OVERFLOW=0`, `SQL_ECHO=true` → 2 / 0 / `True`; `POSTGRES_HOST` inexistente → `crear_motor` no falla (no conecta); confirmar VERDE.
- [x] 4.4 RED → GREEN fábrica: `crear_fabrica_sesiones(motor)` produce `AsyncSession` ligadas a ese motor con `expire_on_commit is False` (inspeccionar `fabrica.kw`); confirmar VERDE.
- [x] 4.5 RED → GREEN `get_session`: con un `Request` falso cuyo `app.state.session_factory` es una fábrica espía: entrega la sesión, la cierra al agotar el generador y también cuando se lanza una excepción dentro (`agen.athrow`); dos llamadas → sesiones distintas; definir `SessionDep`; confirmar VERDE.
- [x] 4.6 Guarda de importación: test que importa `app.core.database` y verifica que no define atributos de módulo `engine`/`SessionLocal` ni instancias de `AsyncEngine`; REFACTOR (`__all__`); VERDE.

## 5. Lifespan y grupos de rutas (`main.py`, `app/core/dependencies.py`) — unitarios

- [x] 5.1 RED: `test/unit/test_lifespan.py`: con `secretos_validos` y `POSTGRES_HOST` inexistente, `async with main.lifespan(app)` publica `app.state.engine` (`AsyncEngine`) y `app.state.session_factory`; antes de entrar, `app.state` no los tiene; al salir, `dispose` se llamó exactamente una vez (espiar con `monkeypatch` sobre el motor creado o sobre `crear_motor`); ejecutar y confirmar que FALLA.
- [x] 5.2 GREEN: reescribir `main.py` (D2): conservar `settings = get_settings()` a nivel de módulo, agregar `lifespan` con `try/finally`, `crear_app(abiertos, protegidos)` y `app = crear_app()`; confirmar VERDE y que `test/unit/test_main.py` (C-01) sigue VERDE.
- [x] 5.3 TRIANGULAR: excepción lanzada dentro del bloque del lifespan → `dispose` igual se llama una vez; confirmar VERDE.
- [x] 5.4 RED → GREEN grupos: `test/unit/test_grupos_rutas.py` con `TestClient(crear_app(abiertos=[r_abierto], protegidos=[r_protegido]))`: ruta abierta → 200; ruta protegida (sin dependencias propias) → 401 con `detail` propio y el handler NO se ejecuta (bandera); con `app.dependency_overrides[exigir_acceso]` contando invocaciones → la ruta protegida responde 200 y el control corrió exactamente 1 vez; la abierta no lo invoca; crear `app/core/dependencies.py` con `exigir_acceso` que falla cerrado (D3); confirmar VERDE. Migrar 2.5 a `crear_app` (handler 422 registrado por la fábrica) y confirmar VERDE.
- [x] 5.5 REFACTOR: docstrings (punto de extensión de C-05 en lifespan y en `exigir_acceso`); `pytest -m "not integration"` VERDE completo.

## 6. Infraestructura de integración (`test/integration/`)

- [x] 6.1 Crear `test/integration/__init__.py`, `test/integration/modelos_prueba.py` (D7: `BasePrueba` con `registry()` propio; `ItemPrueba` con `nombre` UNIQUE DEFERRABLE INITIALLY DEFERRED y `precio NUMERIC(10,2)`/`Decimal`; `ItemBorrable` con `borrado_en TIMESTAMPTZ NULL`) y verificar con un test unitario que `SQLModel.metadata.tables` NO contiene esas tablas (si `registry=` no es soportado, aplicar el fallback de D7 y anotarlo en este archivo).
- [x] 6.2 Crear `test/integration/conftest.py` (D7): `pytest_addoption("--exigir-db")`; fixture de ping con `asyncio.timeout(3)` que hace `skip` (o falla con `--exigir-db`) si la base no responde o la configuración está incompleta; fixture `motor_prueba` con esquema efímero `c02_prueba_<hex>`, `NullPool`, `search_path` por `server_settings`, `create_all` sólo de `BasePrueba.metadata`, teardown `DROP SCHEMA ... CASCADE` + `dispose`; fixture `fabrica_prueba = crear_fabrica_sesiones(motor_prueba)`; marcar todo con `pytest.mark.integration`. Verificar levantando `docker compose up -d postgres` (puerto según `POSTGRES_PORT`) con un test humo `SELECT 1` en el esquema efímero → VERDE, y con el contenedor detenido → SKIPPED (y FAILED con `--exigir-db`).

## 7. Repositorio genérico — integración (PostgreSQL real)

- [x] 7.1 RED: `test/integration/test_repository.py`: `add` asigna `id` y la fila es visible con `get_by_id` en la misma sesión pero NO desde otra sesión de `fabrica_prueba`; ejecutar y confirmar que FALLA.
- [x] 7.2 GREEN: crear `app/core/repository.py` con `BaseRepository[T]` (`__init__(session, model)`, `_consulta`, `get_by_id`, `add`) (D4); confirmar VERDE.
- [x] 7.3 TRIANGULAR: `add` + `session.rollback()` → la base queda vacía; `get_by_id` inexistente → `None`; confirmar VERDE.
- [x] 7.4 RED → GREEN `list`/`count`: 5 filas, `list(offset=2, limit=2)` → 3.ª y 4.ª por `id`; `count() == 5`; `list(offset=10, limit=2) == []`; confirmar VERDE.
- [x] 7.5 RED → GREEN `update`: cambia sólo `nombre` y conserva `precio` (`Decimal`); clave desconocida → `ValueError` y ningún campo cambió (verificar también que la fila en la base no cambió tras `flush`); `update` + `rollback` restaura el valor; confirmar VERDE.
- [x] 7.6 RED → GREEN `delete`: tras `delete` + otra consulta en la misma sesión → `None`; tras `rollback` reaparece; confirmar VERDE.
- [x] 7.7 RED → GREEN PK: construir `BaseRepository` con un modelo de PK compuesta (definido en `modelos_prueba.py`) → `TypeError`; confirmar VERDE (puede ir a `test/unit/`, no necesita base).
- [x] 7.8 Guarda estática + REFACTOR: test unitario que lee `app/core/repository.py` y verifica que no contiene `.commit(` ni `.close(`; `__all__`, docstrings (sin carga perezosa; recomendación `lazy="raise"` para C-03); integración y unitarios VERDE.

## 8. Repositorio con borrado lógico — integración

- [x] 8.1 RED: en `test/integration/test_soft_delete_repository.py`: tras `soft_delete`, `get_by_id` → `None`, `list` no la incluye y `count` la descuenta; ejecutar y confirmar que FALLA.
- [x] 8.2 GREEN: `SoftDeleteRepository[T]` con `_consulta()` filtrando `borrado_en IS NULL` y `soft_delete` (`datetime.now(UTC)` + `flush`) (D4); confirmar VERDE.
- [x] 8.3 TRIANGULAR: `get_by_id_including_deleted` devuelve la fila con `borrado_en` no nulo y con zona horaria; tras `soft_delete` + `commit`, una consulta SQL directa (`text("SELECT borrado_en FROM c02_item_borrable WHERE id = :id")` con parámetro ligado) desde otra sesión ve la fila con `borrado_en` no nulo (no se eliminó); `soft_delete` + `rollback` → reaparece en `get_by_id`, `list` y `count`; una fila no borrada sigue visible; confirmar VERDE.
- [x] 8.4 REFACTOR: docstrings (`borrado_en` requerido en el modelo; índice único parcial en C-03/DD-03); VERDE.

## 9. Unit of Work — integración

- [x] 9.1 RED: `test/integration/test_unit_of_work.py`: `async with UnitOfWork(sesion)` + `repo.add` sin error → la fila es visible desde otra sesión; con excepción en el bloque → la excepción llega al test y la fila NO es visible; ejecutar y confirmar estado (debe pasar si 3.x y 7.x están bien; si pasa sin cambios, documentar que el RED se dio en 3.1 y que esto es verificación contra la base real).
- [x] 9.2 TRIANGULAR "falla al confirmar": dos `ItemPrueba` con el mismo `nombre` (UNIQUE diferido) → el `flush` pasa, el `commit` lanza `IntegrityError` que se propaga; ninguna fila visible desde otra sesión; la misma sesión sigue usable (nuevo bloque UoW con otra fila confirma OK); confirmar VERDE.
- [x] 9.3 TRIANGULAR "no cierra la sesión" y "atributos tras confirmar": tras un bloque confirmado, leer `item.id` y `item.nombre` sin error (`expire_on_commit=False`, sin `MissingGreenlet`) contando con un listener `before_cursor_execute` que no se emitió ninguna consulta; luego abrir un segundo bloque con la misma sesión y confirmar otra fila → OK.
- [x] 9.4 TRIANGULAR UoW de módulo: subclase de prueba con `BaseRepository[ItemPrueba]` y `SoftDeleteRepository[ItemBorrable]` sobre la misma sesión; ambos escriben y luego se lanza excepción → ninguna escritura visible desde otra sesión; sin excepción → ambas visibles; confirmar VERDE.
- [x] 9.5 RED → GREEN sesión por petición (integración HTTP): `crear_app` con un router abierto de prueba que usa `SessionDep` y una UoW de prueba; sustituir en `app.state` motor/fábrica por los de prueba dentro del lifespan (o vía `dependency_overrides[get_session]` apuntando a `fabrica_prueba`); `POST` crea una fila → 200 y la fila es visible desde otra sesión; una ruta que lanza tras escribir → 500 controlado del test y la fila NO persiste; confirmar VERDE.

## 10. Verificación integral

- [x] 10.1 Con PostgreSQL de `docker compose` levantado: `pytest --exigir-db` completo → todo VERDE y **0 skipped**; con el contenedor detenido: `pytest -m "not integration"` VERDE y `pytest -m integration` → SKIPPED con mensaje claro.
- [x] 10.2 Con un `.env` válido: `fastapi dev main.py` arranca sin base disponible (motor perezoso) y al detenerlo no hay advertencias de conexiones sin cerrar; con la base arriba, arranca igual. Sin `JWT_SECRET_KEY` sigue abortando (C-01).
- [x] 10.3 Revisión de reglas duras: `grep -n "commit()" app/core/repository.py` vacío; `grep -n "close(" app/core/unit_of_work.py` vacío; ningún `create_async_engine`/`async_sessionmaker` fuera de funciones; ninguna credencial ni puerto fijo en `test/`; `SQLModel.metadata` sin tablas de prueba; no se hizo build, commit ni push.
