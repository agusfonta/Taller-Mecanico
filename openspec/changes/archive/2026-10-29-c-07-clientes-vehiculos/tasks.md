# Tasks — C-07 `clientes-vehiculos`

> Governance **MEDIO**: implementar con checkpoints; antes de empezar, confirmar con el usuario los supuestos SU-C07-1..9 de `design.md` (cambian respuestas observables).
> Strict TDD: en cada tarea de comportamiento, primero el test en ROJO (ejecutado y fallando), luego el mínimo código en VERDE, luego TRIANGULAR (≥ 2 casos por comportamiento) y REFACTOR con la suite en verde tras cada paso.
> Skills a cargar: `fastapi`, `async-python-patterns`, `python-testing-patterns`, `sqlalchemy-alembic-expert-best-practices-code-review`, `postgres-patterns`. Referencias: `design.md` (D1..D12), `specs/clientes/spec.md`, `specs/vehiculos/spec.md`.
> Reglas: repositorios sólo `flush()`; el router construye el UoW (dependencia) y el servicio lo abre con `async with`; sin carga perezosa (toda relación leída se precarga en el repositorio); `extra="forbid"` en toda entrada; contratos separados de los modelos; unicidad sin consulta previa; SQL con parámetros ligados; integración contra PostgreSQL real. Sin migraciones, sin build, commit ni push. Nunca leer ni imprimir el `.env`.
> Archivos compartidos con C-06/C-08 (ver D11): `main.py` y, sólo si no existe aún el mecanismo, `test/integration/conftest.py`. Antes de tocarlos, releerlos y aplicar el cambio aditivo sobre la versión vigente. No tocar `app/core/*` ni `app/modules/usuarios/*`.

## 1. Safety net

- [x] 1.1 Ejecutar `pytest --exigir-db` con PostgreSQL levantado y registrar la línea base ("N passed, 0 skipped"); si algo falla, DETENER y reportar como falla preexistente (no corregir).

## 2. Contratos (`app/modules/clientes/schemas.py`, D3, D5)

- [x] 2.1 RED: `test/unit/test_schemas_clientes.py` — `ClienteEntrada`: campo extra (`usuario_id`) → `ValidationError`; `documento` sólo espacios → error; `"  30111222 "` → `30111222`; nombre de 121 caracteres → error. Ejecutar y confirmar que FALLA (módulo inexistente).
- [x] 2.2 GREEN: crear `schemas.py` con `_Entrada` (`extra="forbid"`), textos no vacíos con longitudes máximas (SU-C07-4) y `ClienteEntrada`; confirmar VERDE.
- [x] 2.3 RED → GREEN `VehiculoEntrada`: `anio` 1949 y 2101 → error; 1950 y 2100 → ok; `"2020"`, `2020.5` y `true` (vía `model_validate_json`) → error; extra `cliente_id` → error; `marca` vacía → error; confirmar VERDE.
- [x] 2.4 TRIANGULAR patente (parametrizado): `" ab-123 cd "` → `AB123CD`; `"aa000bb"` → `AA000BB`; `"AB*123"`, `"  - "`, `""` y 11 caracteres alfanuméricos → error; un número (no `str`) → error sin excepción no controlada; confirmar VERDE.
- [x] 2.5 RED → GREEN respuestas: `ClienteRespuesta`, `ClienteDetalleRespuesta` (con `vehiculos`), `VehiculoRespuesta`/`VehiculoResumen` construidas con `from_attributes` desde instancias de `Cliente`/`Vehiculo` sin sesión; ninguna expone `borrado_en`; confirmar VERDE.
- [x] 2.6 REFACTOR: `__all__`, docstrings (por qué se normaliza la patente, por qué `strict` en `anio`); `pytest test/unit/test_schemas_clientes.py` VERDE.

## 3. Repositorios y UoW (`repository.py`, `unit_of_work.py`, D1, D4, D6, D7, D9)

- [x] 3.1 RED: `test/integration/test_repositorios_clientes.py` sobre `motor_auth` (sesión propia + `ClientesUoW`): `ClienteRepository.get_con_vehiculos_vigentes(id)` devuelve el cliente con `vehiculos` cargados (leerlos no lanza por `lazy="raise"`) y sólo los vigentes (sembrar 2 vigentes + 1 dado de baja); `None` si no existe. Ejecutar y confirmar que FALLA.
- [x] 3.2 GREEN: extender `ClienteRepository` (sin cambiar constructor ni herencia) con `get_con_vehiculos_vigentes` (`selectinload(Cliente.vehiculos.and_(Vehiculo.borrado_en.is_(None)))`); crear `VehiculoRepository(SoftDeleteRepository[Vehiculo])` y `ClientesUoW` + `get_clientes_uow` + `ClientesUoWDep`; confirmar VERDE y que `test_auth_registro.py` sigue VERDE (el registro usa `ClienteRepository.add`).
- [x] 3.3 RED → GREEN `listar_vigentes_de_usuario(usuario_id)`: dos usuarios con ficha y vehículos → cada uno sólo los suyos, ordenados por id; dado de baja excluido; usuario sin ficha → lista vacía; ficha sin usuario nunca aparece; confirmar VERDE.
- [x] 3.4 RED → GREEN `tiene_ordenes_abiertas(vehiculo_id)` (sembrar catálogo y órdenes con SQL ligado en `test/integration/ayudantes_clientes.py`): sin órdenes → False; PENDIENTE → True; EN_REPARACION → True; sólo TERMINADA y CANCELADA → False; estado de nombre arbitrario con `es_final=true` → False y con `es_final=false` → True; confirmar VERDE.
- [x] 3.5 RED → GREEN `get_vigente_para_baja(id)`: vigente → la entidad; dado de baja o inexistente → `None`; la sentencia compilada (capturada con `before_cursor_execute`) contiene `FOR UPDATE`; confirmar VERDE.
- [x] 3.6 REFACTOR + guarda estática: nuevo `test/unit/test_clientes_estatico.py` que verifica que `app/modules/clientes/{unit_of_work,service}.py` no contienen `.commit(`, `.rollback(` ni `.close(` (el `repository.py` ya lo cubre `test_repository_estatico.py`); confirmar VERDE.

## 4. Servicio (`service.py`, D5, D6, D8)

- [x] 4.1 RED: `test/integration/test_servicio_clientes.py` (UoW real sobre `motor_auth`): `crear_cliente` crea la ficha con `usuario_id` nulo; con documento existente lanza `DocumentoRepetidoError`, no deja filas y el mensaje no contiene `uq_`/`cliente`/`documento` de la base (sólo el texto propio); ejecutar y confirmar que FALLA.
- [x] 4.2 GREEN: errores de dominio (D8) con `mensaje`, mapa restricción → clase usando `app.core.errores.restriccion_violada`, `crear_cliente` y `obtener_cliente` (404 → `ClienteNoEncontradoError`; vehículos ordenados por id); confirmar VERDE.
- [x] 4.3 RED → GREEN `crear_vehiculo`: cliente inexistente → `ClienteNoEncontradoError` sin filas; patente vigente repetida (mismo y otro cliente) → `PatenteVigenteRepetidaError` sin filas; patente de un vehículo dado de baja → se crea; confirmar VERDE.
- [x] 4.4 RED → GREEN `dar_de_baja_vehiculo`: vigente sin órdenes → `borrado_en` no nulo y fila conservada; inexistente o ya dado de baja → `VehiculoNoEncontradoError`; con orden abierta → `VehiculoConOrdenesAbiertasError` y `borrado_en` sigue nulo; sólo órdenes finales → baja; confirmar VERDE.
- [x] 4.5 RED → GREEN `listar_mis_vehiculos(uow, usuario_id)`; confirmar VERDE.
- [x] 4.6 REFACTOR: un solo `async with uow:` por operación, `raise ... from None` al traducir `IntegrityError`; suite de servicio VERDE.

## 5. Router y registro en el grupo protegido (`router.py`, `main.py`, D2, D11)

- [x] 5.1 Releer `main.py` y `test/integration/conftest.py` (pueden haber cambiado por C-06/C-08). Si `app_auth` aún no monta los routers protegidos reales, introducir el mecanismo de D11 (constante de routers protegidos en `main.py` leída por `app_auth`) sin alterar las rutas `/prueba/*`; verificar con `pytest test/integration/test_auth_*.py test/unit/test_main.py test/unit/test_grupos_rutas.py --exigir-db` VERDE.
- [x] 5.2 RED: `test/integration/test_clientes_http.py` — acceso: sin cookie → 401; cambio pendiente → 403; CLIENTE (ficha propia) y MECANICO (id inexistente) → 403; rol RECEPCION revocado en la base con token que lo dice → 403; RECEPCION y ADMIN → 201. Ejecutar y confirmar que FALLA (rutas inexistentes → 404).
- [x] 5.3 GREEN: `router.py` con las 5 rutas (`requiere_rol(Rol.RECEPCION, Rol.ADMIN)` en las 4 de personal; `UsuarioActualDep` en `/mis-vehiculos`), traducción de errores de dominio a 404/409 con `{"detail": mensaje}`, `status_code` 201/204; registrar `router_clientes` en el grupo protegido de `main.py` (cambio aditivo); confirmar VERDE.
- [x] 5.4 TRIANGULAR clientes HTTP: extra → 422 sin filas; 409 documento contra cliente auto-registrado y contra alta previa del personal, sin filas nuevas y sin texto de la base; registro web posterior con el documento de una ficha del personal → 409 y la ficha sigue con `usuario_id` nulo; `GET` 200 con sólo vigentes ordenados; 404 inexistente; `GET /clientes/abc` con ADMIN → 422; confirmar VERDE.
- [x] 5.5 RED → GREEN sin N+1: listener `before_cursor_execute` sobre `motor_auth.sync_engine`; `GET /clientes/{id}` con 1 y con 4 vehículos ejecuta la misma cantidad de sentencias contra `cliente`/`vehiculo` (y exactamente 2); confirmar VERDE.
- [x] 5.6 RED → GREEN `test/integration/test_vehiculos_http.py`: 201 con patente normalizada y visible en el detalle; 404 cliente inexistente sin filas; 409 patente vigente (otro cliente; otra escritura `ab 123 cd`); 422 por `anio` fuera de rango, `"2020"`, patente inválida y campo extra; CLIENTE → 403 en baja y MECANICO → 403 en alta; confirmar VERDE.
- [x] 5.7 RED → GREEN baja HTTP: 204 sin cuerpo, `borrado_en` no nulo y desaparece del detalle; segunda baja → 404; inexistente → 404; con orden PENDIENTE y con EN_REPARACION → 409 con mensaje propio y `borrado_en` nulo; sólo TERMINADA/CANCELADA → 204 y órdenes conservadas; **C-19**: baja → misma patente en otro cliente 201 → tercera carga 409; confirmar VERDE.
- [x] 5.8 RED → GREEN `test/integration/test_mis_vehiculos_http.py`: dos clientes aislados; dado de baja oculto; ADMIN sin ficha → 200 `[]`; ficha sin usuario no aparece para otro CLIENTE; sin cookie → 401; cambio pendiente → 403; confirmar VERDE.
- [x] 5.9 REFACTOR: handlers `async def` delgados, sin lógica de negocio en el router; docstrings con el orden 401 → 403 → 422/404 → 409; suite del módulo VERDE.

## 6. Verificación integral y entrega

- [x] 6.1 `pytest --exigir-db` completo: VERDE y sin skips; comparar con la línea base de 1.1 (sólo tests nuevos agregados, ninguno roto).
- [x] 6.2 Revisión de reglas duras sobre los archivos del módulo: ningún `commit()` en repositorios, ningún UoW construido en el servicio, ninguna relación leída sin precarga, ningún SQL concatenado, toda entrada con `extra="forbid"`; anotar el resultado en el resumen del apply.
- [x] 6.3 Dejar anotado para C-09 (en el resumen del apply y en engram): contrato `get_vigente_para_orden` con `FOR SHARE` (D10), ubicación de `tiene_ordenes_abiertas`, y para C-11 que las patentes del seed deben ir normalizadas (D5).
