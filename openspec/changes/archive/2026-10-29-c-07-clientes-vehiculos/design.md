# Design — C-07 `clientes-vehiculos`

> Governance **MEDIO** (CHANGES.md §C-07): lógica de negocio. Se implementa con checkpoints y se exponen las decisiones no obvias; no requiere aprobación previa del diseño, pero los supuestos **SU-C07-1..9** conviene confirmarlos antes de `/opsx:apply` porque cambian respuestas observables.

## Context

- Motivación y alcance: `proposal.md`. Requisitos observables: `specs/clientes/spec.md` y `specs/vehiculos/spec.md`.
- Estado tras C-01..C-05 (observado en el código):
  - `app/modules/clientes/models.py` (C-03): `Cliente` (`uq_cliente_documento`, `uq_cliente_usuario_id`, `usuario_id` nulo) y `Vehiculo` (`ck_vehiculo_anio_rango`, índice único parcial **`uq_vehiculo_patente_vigente`** `WHERE borrado_en IS NULL`, `borrado_en` TIMESTAMPTZ nulo). Relaciones `Cliente.vehiculos`, `Vehiculo.cliente`, `Vehiculo.ordenes`, `Usuario.cliente` con `lazy="raise"`. `cliente` **no** tiene `borrado_en` (no hay baja de clientes).
  - `app/modules/clientes/repository.py` (C-05): `ClienteRepository(BaseRepository[Cliente])` **mínimo**, sin métodos propios; lo usa `UsuariosUoW.clientes` en el registro (RN-02). `test/unit/test_repository_estatico.py` ya vigila que ese archivo no confirme ni cierre.
  - `app/core/repository.py`: `BaseRepository` (`get_by_id`, `list`, `count`, `add`, `update`, `delete`, todo con `flush()`; punto de extensión `_consulta()`), `SoftDeleteRepository` (`_consulta()` filtra `borrado_en IS NULL`; `get_by_id_including_deleted`; `soft_delete` con `datetime.now(UTC)`).
  - `app/core/unit_of_work.py`: `UnitOfWork(session)` confirma al salir, revierte ante excepción, no cierra la sesión.
  - `app/core/errores.py`: `restriccion_violada(exc) -> str | None` (nombre de la restricción desde `orig`/`__cause__` de asyncpg).
  - `app/core/dependencies.py`: `UsuarioActual` (dataclass inmutable con `id`, `roles_vigentes`), `UsuarioActualDep`, `exigir_acceso` (montado una vez en el grupo protegido), `requiere_rol(*Rol)` (403, roles de la base).
  - `app/core/paginacion.py`: `Pagina[T]`, `PaginacionDep`, `verificar_pagina` (no se usa en este change, ver D7).
  - `main.py`: `crear_app(abiertos, protegidos)`; hoy `app = crear_app(abiertos=[router_health, router_auth])` — **no hay ningún router protegido todavía**.
  - `app/modules/usuarios/service.py`: patrón de errores de dominio (`ConflictoError` con `mensaje`, mapa restricción → clase) y de servicio que recibe el UoW sin abrir.
  - Tests: `test/integration/conftest.py` (C-05) ofrece `esquema_auth` (esquema migrado por Alembic, por sesión), `motor_auth` (TRUNCATE de las 13 tablas tras cada test), `db_auth` (`AyudantesAuth`: `crear_usuario`, `sembrar_cliente_sin_usuario`, `filas`, `ejecutar`, `contar`), `app_auth` (`crear_app(abiertos=[...], protegidos=[protegido_de_prueba])`) y `fabrica_http`/`http`. La sesión se obtiene en los tests con `emitir_token(uid, roles, settings_auth)` en la cookie (sin bcrypt por petición).
- Restricciones: reglas duras de `CLAUDE.md` (flush en repos, UoW construido por el router y abierto por el servicio, sin carga perezosa, `extra="forbid"`, contratos separados de los modelos, PostgreSQL real en integración); KB 03 (matriz RBAC), 04 (§cliente, §vehiculo, navegación), 05 (RN-01, RN-16, RN-17, RN-18, reglas de contrato), 06 (Épica 4), 07 (Flujo 9), 09 (DD-01, DD-03, DD-09, DD-11), 11 (C-01, C-06, C-19).

### Discrepancias detectadas con `CHANGES.md` / KB

1. **`GET /mis-vehiculos` sin paginación**: la tabla de endpoints (KB 06) lista sólo `200` y ningún `page`/`size`, a diferencia de `/mis-ordenes` (`page`, `size`, 422). La regla "Listados: `{items,total,page,size,pages}`" de KB 05 aplica a los listados paginados. Decisión D7: lista JSON simple (SU-C07-1).
2. **Listado / búsqueda de clientes**: no existe `GET /clientes` en la KB ni en CHANGES.md; no se agrega (ni búsqueda, ni filtros, ni paginación de clientes). La recepción llega al cliente por el id devuelto en el alta.
3. **"404 vs 403 para recursos ajenos"**: en este change no hay rutas de "dueño" con id: las rutas con id son sólo de personal (`requiere_rol` → 403 antes de mirar el recurso) y `/mis-vehiculos` no recibe id. El 403 de "ajeno" (RN-17) aparece recién en `GET /ordenes/{id}` y `cancelar` (C-09/C-10). Consecuencia: un CLIENTE recibe 403 aun en `GET /clientes/{su_id}` (la matriz de KB 03 no le da esa ruta).
4. **CHANGES.md scope** dice "`GET /clientes/{id}` con vehículos por precarga (`selectinload`)": se precargan **sólo los vigentes** (RN-16 "deja de aparecer"), con criterio en la opción de carga (D4).
5. **Tests del scope** ("unicidad parcial de patente, baja con orden abierta…") requieren órdenes, que no tienen API hasta C-09: se siembran por SQL ligado (estado del catálogo + `orden_trabajo`) en los tests.
6. **Normalización de la patente** no está en la KB; sin ella `AB123CD` y `ab 123 cd` serían dos vehículos vigentes con "la misma" patente (el índice es exacto). Se normaliza en el contrato (D5, SU-C07-2). **Impacta a C-11**: `seed.py` debe guardar patentes ya normalizadas.

## Goals / Non-Goals

**Goals:**
- Módulo `clientes` completo según la estructura obligatoria (KB 08) extendiendo, no duplicando, el `ClienteRepository` de C-05.
- Unicidad delegada a la base y traducida a 409 por nombre de restricción; ninguna entrada inválida termina en 500.
- Lecturas con número fijo de consultas (Ej. 8) y sin carga perezosa.
- Dejar a C-09 una forma segura de obtener un vehículo vigente para abrir una orden, coordinada con la baja.

**Non-Goals:**
- Editar o borrar clientes; editar vehículos o transferirlos de cliente; restaurar vehículos dados de baja.
- Vincular una ficha cargada por el personal con un usuario web (RN-02 lo prohíbe en el registro; no hay ruta para hacerlo).
- Validar el formato del documento (DNI/CUIT) o del teléfono.
- Listado, búsqueda o paginación de clientes y vehículos (fuera de la KB).
- Endpoints de órdenes, seed y `.http`.

## Decisions

### D1 — Estructura del módulo y extensión de `ClienteRepository`
```
app/modules/clientes/
  models.py        (C-03, sin cambios)
  schemas.py       ClienteEntrada, ClienteRespuesta, ClienteDetalleRespuesta, VehiculoEntrada, VehiculoRespuesta
  repository.py    ClienteRepository (C-05, extendido) + VehiculoRepository
  unit_of_work.py  ClientesUoW(clientes, vehiculos) + get_clientes_uow + ClientesUoWDep
  service.py       crear_cliente, obtener_cliente, crear_vehiculo, dar_de_baja_vehiculo, listar_mis_vehiculos + errores de dominio
  router.py        router (sin prefijo, tags=["clientes"]) con las 5 rutas
```
- `ClienteRepository` conserva su constructor y su herencia de `BaseRepository[Cliente]` (el registro sólo usa `add`): se le **agrega** `get_con_vehiculos_vigentes(id)` (D4). No se cambia a `SoftDeleteRepository` porque `cliente` no tiene `borrado_en`.
- `VehiculoRepository(SoftDeleteRepository[Vehiculo])`: hereda `get_by_id` (sólo vigentes), `get_by_id_including_deleted`, `soft_delete`; agrega `get_vigente_para_baja(id)` (D6), `tiene_ordenes_abiertas(id)` (D6) y `listar_vigentes_de_usuario(usuario_id)` (D7).
- Un solo `APIRouter` con rutas absolutas (`/clientes`, `/clientes/{cliente_id}/vehiculos`, `/vehiculos/{vehiculo_id}`, `/mis-vehiculos`): las cinco van al **mismo grupo** (protegido), así que no hace falta partirlo como `/auth` vs `/usuarios` en C-05.
- **Alternativas**: un módulo `vehiculos/` aparte → contradice la estructura obligatoria (KB 08: `clientes/  # Cliente, Vehiculo`); dos routers (`/clientes`, `/vehiculos`) → más registro en `main.py` (archivo compartido) sin ganancia.

### D2 — Autorización por ruta
| Ruta | Dependencia de ruta | Además (grupo) |
|---|---|---|
| `POST /clientes`, `GET /clientes/{id}`, `POST /clientes/{id}/vehiculos`, `DELETE /vehiculos/{id}` | `requiere_rol(Rol.RECEPCION, Rol.ADMIN)` | `exigir_acceso` (401 / 403 cambio pendiente) |
| `GET /mis-vehiculos` | `UsuarioActualDep` (para leer `usuario.id`) | `exigir_acceso` |
- `requiere_rol` va como dependencia de la ruta (`dependencies=[Depends(...)]`), por lo que FastAPI la resuelve **antes** del handler: el 403 por rol precede siempre al 404 del recurso (spec). FastAPI resuelve primero las subdependencias (que cortan con su `HTTPException`) y después valida los parámetros propios de la ruta; por eso `GET /clientes/abc` da 401 sin sesión, 403 con rol insuficiente y **422** con RECEPCION/ADMIN (caso C-01: "con sesión", sin ejecutar el handler). Los tests fijan el 422 con sesión de personal; el orden con sesión inválida no está en la KB y no se fija.
- `/mis-vehiculos` no usa `requiere_rol`: "lo propio sólo pide estar autenticado" (RN-17, KB 03). El dueño se determina por `cliente.usuario_id = usuario_actual.id` en la consulta, nunca por un parámetro.
- **Alternativa**: permitir a un CLIENTE ver su propio `GET /clientes/{id}` (comprobación de dueño en el servicio, como `cancelar`, DD-09) → la matriz de KB 03 no lo da y la tabla de endpoints lista sólo 200/404; se descarta (SU-C07-3).

### D3 — Contratos (`schemas.py`)
```python
class _Entrada(BaseModel): model_config = ConfigDict(extra="forbid")
TextoNoVacio = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=N)]
class ClienteEntrada(_Entrada):  nombre: Texto120; documento: Texto20; telefono: Texto30
class VehiculoEntrada(_Entrada): patente: Patente; marca: Texto60; modelo: Texto60
                                 anio: Annotated[int, Field(strict=True, ge=1950, le=2100)]
class ClienteRespuesta(BaseModel):        id, nombre, documento, telefono, usuario_id: int | None
class VehiculoRespuesta(BaseModel):       id, cliente_id, patente, marca, modelo, anio
class ClienteDetalleRespuesta(ClienteRespuesta): vehiculos: list[VehiculoResumen]   # sin cliente_id
```
- Separados de los modelos de tabla (regla dura); las respuestas se construyen desde la entidad con `model_validate(..., from_attributes=True)` **dentro** del servicio o del router sólo con atributos de columna o relaciones precargadas (nunca `borrado_en` ni relaciones no cargadas).
- `anio` con `strict=True`: en JSON rechaza `"2020"`, `2020.0` y `true` (en modo laxo `true` pasaría como 1 y fallaría el rango, pero `"2020"` se aceptaría). El CHECK `ck_vehiculo_anio_rango` queda como segunda barrera.
- Longitudes máximas (SU-C07-4): nombre 120, documento 20, teléfono 30, marca/modelo 60. Evitan payloads absurdos sobre columnas `TEXT` y no cambian el esquema.
- `TextoNoVacio` se **redefine localmente** (dos líneas) en vez de importarlo de `usuarios/schemas.py`: ese archivo lo edita C-06 en paralelo y un módulo de dominio no debería depender de los contratos de otro. Consolidar en `app/core` queda como refactor posterior.
- Respuesta del alta de cliente: sin `vehiculos` (recién creado no tiene); el detalle sí. `usuario_id` se expone al personal (indica si la ficha es de un cliente web).

### D4 — Lectura del cliente con vehículos vigentes, sin N+1
```python
async def get_con_vehiculos_vigentes(self, id_: int) -> Cliente | None:
    consulta = (select(Cliente).where(Cliente.id == id_)
                .options(selectinload(Cliente.vehiculos.and_(Vehiculo.borrado_en.is_(None)))))
```
- 2 sentencias fijas (cliente + `SELECT … FROM vehiculo WHERE cliente_id IN (…) AND borrado_en IS NULL`), con 0 o N vehículos. El orden por `id` se aplica en el servicio (`sorted(..., key=id)`) porque la relación no declara `order_by` y modificar `models.py` (C-03) no es necesario.
- Desde la lista precargada **no** se navega `vehiculo.cliente` (con `lazy="raise"` fallaría; la KB exige encadenar `joinedload(Vehiculo.cliente)` para volver). Por eso `VehiculoResumen` no tiene `cliente_id` derivado de la relación: si se quisiera, se lee la columna `cliente_id`, no la relación.
- `populate_existing` no hace falta: el UoW es por petición y la sesión es nueva.
- **Alternativas**: `joinedload(Cliente.vehiculos)` → 1 sola sentencia pero duplica las columnas del cliente por cada vehículo y exige `unique()`; con colecciones `selectinload` es lo recomendado. Filtrar los dados de baja en Python → trae filas que RN-16 dice que "dejan de aparecer" y rompe si crecen; descartada.

### D5 — Alta de vehículo y normalización de patente
- Contrato: `Patente = Annotated[str, BeforeValidator(normalizar_patente), StringConstraints(pattern=r"^[A-Z0-9]{1,10}$")]` con `normalizar_patente(v) = re.sub(r"[\s-]", "", v).upper()` si `v` es `str` (si no, se deja pasar para que el tipo falle con 422). Ejemplos: `" ab-123 cd "` → `AB123CD`; `"AB*123"` → 422.
- Servicio `crear_vehiculo(uow, cliente_id, datos)`: en **un** bloque `async with uow:` → `clientes.get_by_id(cliente_id)` (si `None` → `ClienteNoEncontradoError` → 404) → `vehiculos.add(Vehiculo(cliente_id=..., **datos))`. La comprobación del cliente es una lectura de existencia (no de unicidad), así que no contradice "unicidad sin consulta previa"; además da un 404 claro. Como red, la FK `fk_vehiculo_cliente_id_cliente` también se mapea a 404 (no hay borrado de clientes, así que en la práctica no ocurre).
- Patente vigente repetida: el `flush` del `add` lanza `IntegrityError` con `uq_vehiculo_patente_vigente` → el UoW revierte → `PatenteVigenteRepetidaError` → 409. **Sin consulta previa** (sería una carrera, RN-01 "Unicidad garantizada por la base").
- **Alternativas**: no normalizar → duplicados lógicos (`AB123CD` / `ab123cd`) vigentes a la vez; índice funcional `upper(patente)` → requiere migración (C-03 cerrado) y no resuelve espacios/guiones; normalizar en el servicio → el 422 de patente inválida quedaría fuera del contrato.

### D6 — Baja lógica con control de órdenes abiertas y bloqueo
Servicio `dar_de_baja_vehiculo(uow, vehiculo_id)`, todo en **un** bloque:
1. `vehiculo = await uow.vehiculos.get_vigente_para_baja(vehiculo_id)` → `SELECT … FROM vehiculo WHERE id = :id AND borrado_en IS NULL FOR UPDATE`. `None` (inexistente o ya dado de baja) → `VehiculoNoEncontradoError` → 404.
2. `if await uow.vehiculos.tiene_ordenes_abiertas(vehiculo_id)` → `VehiculoConOrdenesAbiertasError` → 409. Consulta:
   ```sql
   SELECT EXISTS (SELECT 1 FROM orden_trabajo o JOIN estado_orden e ON e.codigo = o.estado
                  WHERE o.vehiculo_id = :id AND e.es_final = false)
   ```
   (con `select(exists().where(...))` de SQLAlchemy sobre `OrdenTrabajo`/`EstadoOrden`; usa el índice de `orden_trabajo.vehiculo_id`). Con el catálogo vacío no puede haber órdenes (FK), así que da falso.
3. `await uow.vehiculos.soft_delete(vehiculo)` (flush) → al salir del bloque el UoW confirma → 204.
- **Bloqueo**: `FOR UPDATE` sobre la fila del vehículo serializa la baja con el alta de una orden **si C-09 lee el vehículo vigente con `FOR SHARE`** (D10). Sin bloqueo: baja y alta de orden concurrentes podrían ver "sin órdenes abiertas" / "vehículo vigente" a la vez y dejar una orden PENDIENTE sobre un vehículo dado de baja (viola RN-16). Costo: una cláusula; DD-11 difiere la concurrencia del **stock**, no esta. En READ COMMITTED, la transacción que espera re-evalúa el `WHERE borrado_en IS NULL` sobre la versión nueva de la fila y no la encuentra → 409 en C-09.
- `soft_delete` usa el reloj de la app (`datetime.now(UTC)`), coherente con C-05.
- **Alternativas**: comparar contra una lista fija (`estado IN ('PENDIENTE','EN_REPARACION')`) → contradice DD-02/RN-16 ("el catálogo decide"); contar órdenes cargando `vehiculo.ordenes` → carga perezosa prohibida y trae filas innecesarias; borrar físicamente → pierde datos e historial (RN-16).

### D7 — `GET /mis-vehiculos`: una consulta, lista simple
```python
async def listar_vigentes_de_usuario(self, usuario_id: int) -> Sequence[Vehiculo]:
    select(Vehiculo).join(Cliente, Cliente.id == Vehiculo.cliente_id)
        .where(Cliente.usuario_id == usuario_id, Vehiculo.borrado_en.is_(None)).order_by(Vehiculo.id)
```
- Una sola sentencia, sin relaciones (la respuesta usa la columna `cliente_id`). Un usuario sin ficha → `[]` (200), sin 404 (spec). `uq_cliente_usuario_id` garantiza a lo sumo una ficha por usuario.
- Respuesta: `list[VehiculoRespuesta]` (SU-C07-1). **Alternativa**: envoltorio `Pagina` con `page`/`size` → la KB no lo pide para esta ruta (sí para `/mis-ordenes`) y agregaría 422 no documentados; si la cátedra lo pide, es aditivo (`PaginacionDep` + `count`).
- **Alternativa**: buscar primero la ficha (`ClienteRepository.get_by_usuario_id`) y luego sus vehículos → 2 consultas sin ganancia.

### D8 — Errores de dominio y traducción a HTTP
En `clientes/service.py`, propios del módulo:
| Excepción | HTTP | Mensaje (SU-C07-5) |
|---|---|---|
| `ClienteNoEncontradoError` | 404 | "Cliente no encontrado" |
| `VehiculoNoEncontradoError` | 404 | "Vehículo no encontrado" |
| `DocumentoRepetidoError` (`uq_cliente_documento`) | 409 | "El documento ya pertenece a un cliente del taller" (mismo texto que el registro de C-05) |
| `PatenteVigenteRepetidaError` (`uq_vehiculo_patente_vigente`) | 409 | "Ya hay un vehículo vigente con esa patente" |
| `VehiculoConOrdenesAbiertasError` | 409 | "El vehículo tiene órdenes abiertas" |
| otra restricción no mapeada | 409 | "Los datos chocan con un registro existente" |
- Mapa `restricción → clase` como en C-05 (`_CONFLICTOS_POR_RESTRICCION`), usando `app.core.errores.restriccion_violada`; el `try/except IntegrityError` envuelve el `async with uow:` (el UoW ya revirtió al propagarse) y re-lanza con `from None` (sin cadena hacia el texto de la base, RN-18).
- El router traduce con `HTTPException(status, detail=mensaje)`; las respuestas 404/409 tienen la forma `{"detail": "..."}` como el resto de la API.
- **Alternativa**: mover `ConflictoError` y una base `NoEncontradoError` a `app/core/errores.py` para todos los módulos → mejor a largo plazo, pero `app/core/errores.py` es compartido con C-06/C-08 en paralelo; se difiere a un refactor (riesgo listado). Importar `ConflictoError` desde `usuarios.service` → acopla dominios; descartada.

### D9 — Servicio y UoW
- `ClientesUoW(UnitOfWork)` con `self.clientes = ClienteRepository(session)` y `self.vehiculos = VehiculoRepository(session)`; `get_clientes_uow(session: SessionDep) -> ClientesUoW` y `ClientesUoWDep` en `unit_of_work.py` (mismo patrón que `usuarios`). El router recibe `ClientesUoWDep` y lo pasa al servicio; el servicio hace `async with uow:` una vez por operación.
- Lecturas (`obtener_cliente`, `listar_mis_vehiculos`) también dentro de `async with uow:` (confirman una transacción de sólo lectura y devuelven la conexión) y **construyen la respuesta dentro del bloque** o devuelven entidades con todo lo que se lee ya cargado (`expire_on_commit=False` en la fábrica, C-02).
- Nota: en `/mis-vehiculos` la petición usa dos UoW sobre la **misma** sesión de la petición: `UsuariosUoW` (en `get_usuario_actual`) y `ClientesUoW` (handler), en bloques secuenciales, nunca anidados. Es el mismo patrón que `cambiar_password` de C-05.

### D10 — Lo que C-09 necesitará de este change (contrato, sin endpoint)
- `VehiculoRepository` es público y C-09 lo instancia dentro de su `OrdenesUoW` sobre la misma sesión.
- **A implementar aquí** (lo usa la baja o es trivial y conviene fijarlo ya): `get_by_id` (vigente), `get_vigente_para_baja` (`FOR UPDATE`).
- **A implementar en C-09** (sólo se define el contrato): `get_vigente_para_orden(id) -> Vehiculo | None` con `FOR SHARE` (se bloquea frente a la baja de D6 y re-evalúa `borrado_en IS NULL`), devolviendo `None` si no existe o está dado de baja → 409 en `POST /ordenes` (CHANGES.md C-09: "vehículo inexistente o de baja → 409"). Para el dueño de una orden (`GET /ordenes/{id}`, `cancelar`, `/mis-ordenes`): navegar `orden → vehiculo → cliente` con `joinedload(OrdenTrabajo.vehiculo).joinedload(Vehiculo.cliente)` y comparar `cliente.usuario_id` con el usuario actual; eso vive en el repositorio de órdenes (C-09), no aquí.
- `tiene_ordenes_abiertas` vive hoy en `VehiculoRepository` porque C-07 la necesita antes de que exista el repositorio de órdenes; C-09 MAY moverla a su repositorio manteniendo la firma.

### D11 — Registro del router: archivos compartidos con C-06 / C-08
Este change toca archivos que C-06 (usuarios) y C-08 (repuestos) también modifican en paralelo. Para secuenciar el apply:
| Archivo | Cambio de C-07 | Conflicto esperado | Regla de integración |
|---|---|---|---|
| `main.py` | `from app.modules.clientes.router import router as router_clientes` y `protegidos=[..., router_clientes]` en `crear_app` | C-06 y C-08 agregan sus routers a la misma lista | Cambio aditivo de una línea en la lista; quien aplique después rebasa sobre la versión vigente. Si un change previo extrajo las listas a constantes (`ROUTERS_ABIERTOS` / `ROUTERS_PROTEGIDOS`), agregarse ahí. |
| `test/integration/conftest.py` | `app_auth` debe montar también los routers protegidos reales. Propuesta mínima: `protegidos=[protegido, *ROUTERS_PROTEGIDOS]` leyendo la constante de `main.py`, para que los tests usen el mismo registro que producción | C-06 y C-08 necesitan lo mismo | El primero en aplicar introduce el mecanismo; los siguientes sólo agregan su router en `main.py`. Si el mecanismo ya existe, C-07 **no** toca `conftest.py`. |
| `test/unit/test_repository_estatico.py` | nada (ya cubre `clientes/repository.py`) | — | La guarda estática del `unit_of_work.py` de clientes va en un archivo nuevo propio para no competir por el `parametrize`. |
| `app/core/*` | **ningún cambio** (sólo se importan `errores`, `dependencies`, `repository`, `unit_of_work`, `database`) | — | — |
| `app/modules/usuarios/*` | **ningún cambio** (`UsuariosUoW` sigue usando `ClienteRepository` con la misma API) | — | — |
- Ayudantes de siembra propios (`test/integration/ayudantes_clientes.py`: crear cliente, vehículo, estados del catálogo y orden con SQL ligado sobre `db_auth.ejecutar/filas`) en lugar de ampliar `AyudantesAuth` en el `conftest.py` compartido.

### D12 — Estrategia de pruebas (Strict TDD, PostgreSQL real)
- **Unitarios** (`test/unit/test_schemas_clientes.py`): `extra` → error; textos vacíos/espacios; recorte; longitudes máximas; `anio` 1949/1950/2100/2101, `"2020"`, `2020.5`, `true`; normalización de patente (`" ab-123 cd "` → `AB123CD`) y rechazos (`"AB*123"`, `"  - "`, 11 caracteres). Guarda estática: `clientes/unit_of_work.py` y `service.py` sin `.commit(`/`.close(` (archivo nuevo).
- **Integración de repositorios** (`test/integration/test_repositorios_clientes.py`, sobre `motor_auth` con sesión propia y UoW): `get_con_vehiculos_vigentes` excluye dados de baja y no dispara `lazy="raise"` al leer `cliente.vehiculos`; `listar_vigentes_de_usuario` aísla por usuario; `tiene_ordenes_abiertas` con estados finales/no finales del catálogo sembrado (incluido un estado de nombre arbitrario con `es_final=true`); `get_vigente_para_baja` emite `FOR UPDATE` (se inspecciona la sentencia compilada) y devuelve `None` para dados de baja.
- **Integración HTTP** (`test_clientes_http.py`, `test_vehiculos_http.py`, `test_mis_vehiculos_http.py`) con `http` + cookies de `emitir_token` y usuarios de `db_auth.crear_usuario(roles=...)`:
  - Acceso: 401 sin cookie; 403 con cambio pendiente; 403 CLIENTE/MECANICO (incluido id inexistente y ficha propia); 201/200 RECEPCION y ADMIN; rol revocado en la base → 403.
  - Clientes: 201 + fila sin usuario; extra → 422 sin filas; 409 documento (vs. auto-registrado y vs. alta del personal) sin filas nuevas ni texto de la base; registro web posterior con ese documento → 409 y ficha intacta; `GET` 200 con vigentes ordenados, 404, `abc` → 422.
  - **Sin N+1**: listener `before_cursor_execute` sobre `motor_auth.sync_engine` (patrón de `test_auth_sesion.py`); misma cantidad de sentencias que tocan `FROM cliente`/`FROM vehiculo` con 1 y con 4 vehículos.
  - Vehículos: 201 con patente normalizada; 404 cliente inexistente; 409 patente vigente (otro cliente y otra escritura); 422 contrato; baja 204 con `borrado_en` no nulo y fila conservada; 2.ª baja 404; 409 con orden PENDIENTE/EN_REPARACION (estado sin cambio); 204 con sólo TERMINADA/CANCELADA; **C-19**: baja → re-registro en otro cliente 201 → tercera carga 409.
  - `/mis-vehiculos`: dos clientes aislados; dado de baja oculto; ADMIN sin ficha → `[]`; ficha sin usuario no aparece.
- Concurrencia baja vs. alta de orden: **no** se prueba con dos transacciones reales en C-07 (no existe aún el alta de orden); se verifica la cláusula `FOR UPDATE` y C-09 prueba la interacción con su `FOR SHARE`.

## Risks / Trade-offs

- [**Carrera baja vs. orden nueva** si C-09 no usa `FOR SHARE`] → contrato explícito en D10; checklist en tasks para que C-09 lo tome.
- [**Normalización de patente no prevista por la KB**] → puede diferir de lo que espere la corrección (p. ej. aceptar guiones guardados) → SU-C07-2 a confirmar; el seed (C-11) debe guardar patentes normalizadas o `GET /mis-vehiculos` mostraría formatos mezclados.
- [**`/mis-vehiculos` sin paginación**] → un cliente con muchos vehículos devuelve todo; aceptable para el dominio (pocos autos por cliente). Cambio aditivo si se pide.
- [**Excepciones de dominio duplicadas por módulo** (C-05, C-07, C-08 cada uno con su `ConflictoError`)] → coste de mantenimiento bajo; consolidar en `app/core/errores.py` cuando los tres changes estén cerrados.
- [**Archivos compartidos** (`main.py`, `conftest.py`)] → cambios aditivos de una línea; orden de apply indiferente si se rebasa sobre la última versión (D11).
- [**Orden de 422 vs 401/403** cuando el id del path es inválido y además falta sesión] → depende de cómo FastAPI resuelva dependencias y validación; no está fijado en la KB. Los tests sólo fijan 422 **con** sesión válida (caso C-01).
- [**`FOR UPDATE` dentro de `SoftDeleteRepository`**] → se hace en un método propio de `VehiculoRepository` (no se toca `app/core/repository.py`, compartido).
- [**Mensaje del 409 de documento igual al del registro**] → coherencia deliberada; si C-06/C-05 lo cambian, alinear.

## Supuestos (confirmar antes de `/opsx:apply`)

- **SU-C07-1**: `GET /mis-vehiculos` devuelve una **lista JSON simple** (sin `page`/`size` ni envoltorio), ordenada por `id`.
- **SU-C07-2**: la patente se normaliza (sin espacios ni guiones, mayúsculas) y debe quedar en `^[A-Z0-9]{1,10}$`; otro formato → 422.
- **SU-C07-3**: un CLIENTE recibe **403** en `GET /clientes/{id}` aunque sea su propia ficha (KB 03 sólo da la ruta a RECEPCION/ADMIN); su vía es `/mis-vehiculos`.
- **SU-C07-4**: longitudes máximas: nombre 120, documento 20, teléfono 30, marca/modelo 60; sin validación de formato de documento ni teléfono; documento sólo recortado (no se quitan puntos ni guiones).
- **SU-C07-5**: textos de los mensajes 404/409 de D8.
- **SU-C07-6**: `POST /clientes` responde `{id, nombre, documento, telefono, usuario_id}` (sin `vehiculos`); `GET /clientes/{id}` agrega `vehiculos: [{id, patente, marca, modelo, anio}]` sólo vigentes; `POST /clientes/{id}/vehiculos` y `/mis-vehiculos` usan `{id, cliente_id, patente, marca, modelo, anio}`. `borrado_en` nunca se expone.
- **SU-C07-7**: baja de un vehículo ya dado de baja → **404** (no 204 idempotente): el recurso "vigente" ya no existe y KB 06 lista 204/404/409.
- **SU-C07-8**: un usuario sin ficha de cliente (personal) recibe `200 []` en `/mis-vehiculos`, no 404 (KB 06 lista sólo 200).
- **SU-C07-9**: la baja usa `FOR UPDATE` sobre el vehículo y C-09 deberá leer el vehículo con `FOR SHARE` (D6/D10).

## Migration Plan

Sin migraciones de esquema ni de datos (usa las tablas de C-03 tal cual). Despliegue: agregar el módulo y registrar el router en el grupo protegido. Rollback: quitar el router de `main.py` y los archivos nuevos, y revertir `clientes/repository.py` a la versión mínima de C-05 (el registro sigue funcionando porque sólo usa `add`).

## Open Questions

- Ninguna bloqueante. Los supuestos SU-C07-1..9 pueden confirmarse o ajustarse sin cambiar la arquitectura (sólo contratos/mensajes).
