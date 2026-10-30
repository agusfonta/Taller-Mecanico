# Design — C-10 `ordenes-ciclo-de-vida`

> Governance **ALTO** (stock y concurrencia) con partes **MEDIO** (rutas y permisos): las decisiones marcadas **[APROBAR]** completan huecos de la KB o son no obvias; el apply NO arranca sin el visto bueno del usuario (lista consolidada al final, §Decisiones a aprobar). Las ya decididas por el usuario se marcan **[DECIDIDA]**.

## Context

Ver `proposal.md` (Why) y `specs/{transiciones-orden,aviso-cliente,stock-repuestos}/spec.md` (requisitos). Estado de partida observado en el código:

- `app/modules/ordenes/` (C-09): `OrdenesUoW` expone sobre la misma sesión `estados`, `ordenes`, `items`, `historial`, `vehiculos`, `repuestos`, `movimientos` → cumple `ConStock`. `OrdenRepository.get_detalle(id)` carga en 3 sentencias fijas con `populate_existing`. Errores de dominio con `mensaje`, traducidos por una única `_http_desde` del router (`NoEncontradoError` → 404, `OrdenAjenaError` → 403, `ConflictoError` → 409). `EstadoOrdenCodigo(StrEnum)` en `models.py`. `crear_orden` nunca pre-asigna mecánico.
- `app/modules/repuestos/stock.py` (C-08): `mover_stock(uow, *, repuesto_id, cantidad, motivo, usuario_id, orden_id=None) -> int`. Aplica `UPDATE repuesto SET stock = stock + :delta` relativo y atómico (sin actualización perdida; DD-11 queda cubierta de hecho) e inserta el movimiento. El stock insuficiente se detecta por la violación de `ck_repuesto_stock_no_negativo` → `StockInsuficienteError(repuesto_id)`; tras ella la transacción de PostgreSQL queda abortada y la excepción **debe** atravesar el bloque. No filtra repuestos dados de baja. Exige iterar por `repuesto_id` ascendente.
- `VehiculoRepository.get_vigente_para_baja` (C-07) toma `FOR UPDATE` sobre el vehículo y `tiene_ordenes_abiertas` decide con `estado_orden.es_final`.
- Restricciones con nombre conocido: `fk_orden_trabajo_estado_estado_orden`, `fk_historial_estado_orden_hasta_estado_estado_orden`.
- `test/unit/test_main.py` afirma hoy "cinco rutas de órdenes": pasará a ocho.
- El seed (C-11) **no existe aún**: el escenario de la orden #2 (4 bujías, stock 2) se reproduce con ayudantes de test.

## Goals / Non-Goals

**Goals:**
- Tres transiciones con orden de evaluación determinista (401 → 403 grupo → 403 rol → 422 → 404 → 403 permiso → 409 estado) y sin escrituras ante cualquier rechazo.
- `terminar` como operación multi-escritura atómica que usa el punto único de stock sin modificarlo.
- Serializar transiciones concurrentes sobre la misma orden sin interbloqueos con altas, reposiciones ni bajas.
- Aviso en segundo plano estrictamente posterior al commit.

**Non-Goals:**
- Reasignar mecánico, desasignar, reabrir, cancelar EN_REPARACION (la KB no lo permite).
- Cambios de esquema, migraciones o de `mover_stock` (sólo una constante de motivo nueva).
- Seed (C-11), `.http` y evidencias (C-12), colas con reintento (cap. 8).

## Decisions

### D1 — Tabla de transiciones pura en `ordenes/transiciones.py`
```
class Accion(StrEnum): INICIAR, TERMINAR, CANCELAR
TRANSICIONES: Mapping[tuple[Accion, EstadoOrdenCodigo], EstadoOrdenCodigo] = {
  (INICIAR,  PENDIENTE):     EN_REPARACION,
  (TERMINAR, EN_REPARACION): TERMINADA,
  (CANCELAR, PENDIENTE):     CANCELADA,
}
def destino(accion, actual: str) -> EstadoOrdenCodigo   # TransicionInvalidaError si no está
```
Función pura, sin E/S: la matriz completa 3 acciones × 4 estados (12 casos) se prueba en unitarios. Es el "vocabulario de transiciones" del enum (DD-02). Un estado desconocido para el enum (fila de catálogo no declarada) también → `TransicionInvalidaError`.
*Alternativa descartada*: decidir con `es_final` del catálogo → el catálogo no describe aristas (sólo qué estados son finales); la tabla en código es lo que pide DD-02.
- **D1-a [APROBAR]**: coherencia catálogo↔tabla (RN-16): un test unitario verifica que los estados sin transiciones salientes en `TRANSICIONES` son exactamente los que el catálogo canónico (el que cargará `seed.py`: TERMINADA, CANCELADA) marca `es_final`. No se consulta `es_final` en tiempo de ejecución para decidir transiciones.

### D2 — Bloqueo de la orden: `OrdenRepository.bloquear(id)` + `get_detalle`
Cada transición, dentro del único `async with uow`, hace primero:
1. `bloquear(id)`: `SELECT * FROM orden_trabajo WHERE id = :id FOR UPDATE` con `populate_existing`, **sin** relaciones (una sentencia). `None` → 404.
2. Con la fila bloqueada se evalúan permiso y estado (D4). Para `cancelar` el dueño se conoce con `get_detalle(id)` (vehículo→cliente precargado, C-09).
3. Tras las escrituras, `get_detalle(id)` (con `populate_existing`) devuelve la respuesta con el historial nuevo.

En READ COMMITTED, una segunda transacción sobre la misma orden espera en el paso 1 y, al liberarse, lee la fila ya confirmada (estado nuevo) → 409 o 403 según corresponda. Resuelve "dos transiciones simultáneas".
*Alternativa descartada*: `get_detalle(...).with_for_update(of=OrdenTrabajo)` en una sola sentencia → el `joinedload` usa LEFT OUTER JOIN y la propagación del bloqueo a los `selectinload` no es evidente; dos sentencias simples son más claras y el detalle de transiciones no tiene requisito de conteo fijo.
*Alternativa descartada*: `UPDATE ... WHERE estado = :esperado` optimista → no permite distinguir 403/404/409 en el orden pedido sin otra lectura.
- **D2-a [APROBAR]**: se bloquea la fila de la orden aun cuando el resultado sea 403 (el permiso se decide después de leerla con bloqueo). El bloqueo dura lo que la transacción corta; aceptado.

### D3 — Orden global de bloqueos (sin interbloqueos)
Orden único: **orden_trabajo → repuestos por `repuesto_id` ascendente**. Ninguna ruta bloquea un repuesto y luego una orden: el alta (C-09) bloquea repuestos `FOR SHARE` por id sin bloquear órdenes existentes; reponer/PATCH bloquean un solo repuesto; la baja de vehículo bloquea el vehículo y sólo **lee** órdenes. Las transiciones no bloquean el vehículo.
- **[DECIDIDA]**: `terminar` procesa los ítems ordenados por `repuesto_id` (contrato de `mover_stock`).

### D4 — Flujo de cada transición (servicio, un único `async with uow`)
| Paso | `iniciar` | `terminar` | `cancelar` |
|---|---|---|---|
| Ruta | `requiere_rol(MECANICO)` → 403 | `requiere_rol(MECANICO, ADMIN)` → 403 | sin `requiere_rol` (DD-09) |
| 1 | `bloquear` → 404 | `bloquear` → 404 | `bloquear` → 404 |
| 2 permiso | — (la ruta ya exigió MECANICO) | ADMIN vigente **o** `orden.mecanico_id == actor` → si no `SinPermisoSobreOrdenError` (403) | RECEPCION/ADMIN vigente **o** dueño (`get_detalle` → `vehiculo.cliente.usuario_id == actor`) → si no 403 |
| 3 estado | `destino(INICIAR, estado)` → 409 | `destino(TERMINAR, estado)` → 409 | `destino(CANCELAR, estado)` → 409 |
| 4 | `mecanico_id` no nulo y ≠ actor → `OrdenAsignadaAOtroError` (409) | — | — |
| 5 catálogo | `estados.get_por_codigo(destino)` → `None` → `CatalogoSinCargarError` (409) | ídem | ídem |
| 6 escrituras | `ordenes.update(estado, mecanico_id=actor)` | ítems por `repuesto_id`: `mover_stock(-cantidad, MOTIVO_ORDEN_TERMINADA, actor, orden_id)`; `ordenes.update(estado)` | `ordenes.update(estado)` |
| 7 | `historial.add(desde, hasta, actor)` | ídem | ídem |
| 8 | `get_detalle` | `get_detalle` | `get_detalle` |

- **[DECIDIDA] DD-18 / D12-a**: `iniciar` asigna **siempre** al MECANICO que inicia; el alta nunca pre-asigna. El paso 4 sólo cubre órdenes pre-asignadas por SQL/seed: mismo usuario → se inicia; otro → 409.
- **[DECIDIDA] IN-02**: `iniciar` sólo MECANICO (un ADMIN sin MECANICO → 403). `terminar` admite ADMIN.
- **D4-a [APROBAR]**: `terminar` lleva `requiere_rol(MECANICO, ADMIN)` en la ruta **además** del control "asignado o ADMIN" del servicio. Así un CLIENTE/RECEPCION recibe 403 antes de 404 (no sondea ids) y la regla fina (asignado) vive en el servicio. La tabla de la KB lista 403 y 404 para `terminar`; esto fija su orden.
- **D4-b [APROBAR]**: en `terminar` y `cancelar` el orden es **404 → 403 → 409** (hay que leer la orden para conocer asignado/dueño; mismo criterio que D8-a de C-09). RN-12 ("permiso antes que estado") se cumple.
- **D4-c [APROBAR]**: un MECANICO sin RECEPCION/ADMIN que no es dueño recibe 403 al cancelar (la KB no lo incluye entre quienes cancelan).
- **D4-d [APROBAR]**: el paso 5 (catálogo) se valida con lectura explícita antes de escribir, como D5-a de C-09; la FK de `estado`/`hasta_estado` queda como red: un `IntegrityError` con `fk_orden_trabajo_estado_estado_orden` o `fk_historial_estado_orden_hasta_estado_estado_orden` se traduce a `CatalogoSinCargarError` fuera del bloque; restricción desconocida → `ConflictoError` genérico (nunca 500 ni texto de la base, RN-18).
- La actualización de la orden usa `BaseRepository.update` (sólo `flush`). `mecanico_id` se toma de la sesión, nunca del cuerpo (las rutas no tienen cuerpo).

### D5 — Stock insuficiente: confiar en `mover_stock` (sin pre-validación)
Dentro del bucle de ítems, `StockInsuficienteError(repuesto_id)` **no se captura dentro del bloque**: atraviesa el `async with` (el UoW revierte stock ya descontado, movimientos, estado e historial) y el servicio lo traduce **fuera** a `StockInsuficienteOrdenError` (409) con mensaje propio `"Stock insuficiente para el repuesto {codigo}"`, tomando `codigo` de un mapa `repuesto_id → codigo` armado antes del bucle (desde los ítems precargados por `get_detalle`, que en `terminar` se llama también antes del bucle). `StockFueraDeRangoError`/`RepuestoNoEncontradoError` no pueden ocurrir con salidas sobre FKs válidas; si ocurrieran → 409 genérico.
- **D5-a [APROBAR]**: no se pre-valida con `SELECT ... FOR UPDATE` de los repuestos (lo que sugiere SU-04): el `UPDATE` relativo ya toma el bloqueo de fila en orden y la CHECK `stock >= 0` es la verificación atómica; el error ya es un error de dominio tipado del punto único. Ahorra una sentencia y elimina la ventana entre lectura y escritura. *Alternativa*: pre-lectura con `FOR UPDATE` ordenada + comparación en Python (exactamente SU-04) y la CHECK como red.
- **D5-b [APROBAR]**: el 409 identifica el **primer** repuesto insuficiente en orden de `repuesto_id` (no la lista completa: la transacción queda abortada tras el primero).

### D6 — Motivo y autoría de las salidas
- **D6-a [APROBAR]**: nueva constante `MOTIVO_ORDEN_TERMINADA = "Terminación de orden"` en `repuestos/stock.py` (junto a `MOTIVO_STOCK_INICIAL`/`MOTIVO_REPOSICION`); `orden_id` identifica la orden, el motivo no la repite. `usuario_id` del movimiento y del historial = actor (mecánico asignado o ADMIN).
- **D6-b [APROBAR]**: se descuenta stock también de ítems cuyo repuesto fue dado de baja después del alta (RN-16 sólo impide usarlo en órdenes **nuevas**; `mover_stock` no filtra bajas).

### D7 — Aviso (`ordenes/avisos.py`, DD-10/DD-21)
```
DEMORA_AVISO = 0.5
logger = logging.getLogger("app.modules.ordenes.avisos")
async def avisar_cliente(cliente_id: int, orden_id: int) -> None:
    await asyncio.sleep(DEMORA_AVISO)
    logger.info("Aviso a cliente %s: orden %s terminada", cliente_id, orden_id)
```
El handler de `terminar` recibe `BackgroundTasks` y, **sólo después** de que `service.terminar_orden` retorna (el UoW ya confirmó al salir del bloque), hace `background_tasks.add_task(avisar_cliente, orden.vehiculo.cliente_id, orden.id)`. Si el servicio lanza (403/404/409 o falla del commit), la línea no se alcanza → no hay aviso. Starlette ejecuta la tarea después de enviar la respuesta.
- **[DECIDIDA] DD-21**: `logger.info` con texto fijo `Aviso a cliente {cliente_id}: orden {orden_id} terminada`, agendado tras el commit (no dentro de la transacción).
- **D7-a [APROBAR]**: el aviso usa `cliente_id` (no el usuario ni el correo): Jorge (cliente sin usuario) también recibe aviso. Una excepción dentro del aviso se registra con `logger.exception` y no se propaga (la orden ya está confirmada).
*Alternativa descartada*: agendar desde el servicio → el servicio no conoce la respuesta HTTP y podría agendar antes del commit.

### D8 — Errores de dominio nuevos y traducción
En `ordenes/service.py`: `SinPermisoSobreOrdenError(OrdenAjenaError)` ("No tiene permiso para operar esta orden", 403), `TransicionInvalidaError(ConflictoError)` (mensaje con estado y acción, p. ej. "La orden está TERMINADA y no admite cancelar", 409), `OrdenAsignadaAOtroError(ConflictoError)` (409), `StockInsuficienteOrdenError(ConflictoError)` (409). `_http_desde` no cambia (las jerarquías ya mapean). Mensajes sin texto de la base.

### D9 — Router y montaje
Tres handlers en `router_ordenes` (rutas absolutas `/ordenes/{orden_id}/iniciar|terminar|cancelar`, `status_code=200`, respuesta `OrdenDetalle`). Sin cuerpo. Ya están en `protegidos` porque el router lo está (no se toca `main.py`). `Iniciador = requiere_rol(MECANICO)`, `Terminador = requiere_rol(MECANICO, ADMIN)`, cancelar con `UsuarioActualDep`.

### D10 — Interacción con la baja de vehículo (C-07)
Sin código nuevo: `tiene_ordenes_abiertas` decide por `es_final`. Una baja concurrente con una cancelación/terminación en vuelo ve aún la orden abierta (sentencia en READ COMMITTED) → 409 conservador; nunca al revés (las transiciones no abren órdenes). Se cubre con tests HTTP (montar `router_clientes` en el `conftest.py` de órdenes).

### D11 — Tests (patrón C-09 + brechas cerradas en su verify)
- Unitarios: `test/unit/test_transiciones_ordenes.py` (matriz 12 casos + D1-a), `test/unit/test_ordenes_estatico.py` (async, sin `commit(`, `terminar_orden` llama `mover_stock` y no `sumar_stock` directo, ninguna escritura de `repuesto.stock` fuera de `stock.py`), `test/unit/test_avisos_ordenes.py` (formato, demora parcheada, excepción no propagada), `test/unit/test_main.py` (ocho rutas; las tres nuevas bajo `exigir_acceso` del grupo protegido y en ningún grupo abierto).
- Integración (`test/integration/ordenes/`, PostgreSQL real, sin mocks de la base): `conftest.py` propio (agrega `router_clientes`), `ayudantes.py` (+ `movimientos_de_orden`, `stock_de`, `escenario_c11`), `sesiones.py` para dos sesiones concurrentes. Por cada ruta nueva: 401, 403 por cambio pendiente, 403 por rol, 422 id no entero, 404, 403 permiso, 409 estado; y "sin filas nuevas" verificado con `conteos` en cada rechazo.
- Concurrencia con dos sesiones reales y `asyncio.gather` + un evento/`pg_sleep` para forzar el solapamiento (patrón de C-09 4.4).
- Aviso: `caplog` sobre `app.modules.ordenes.avisos` con `DEMORA_AVISO` parcheada a 0; uno solo tras 200, ninguno tras 409/403/404 ni en `iniciar`/`cancelar`; y test directo del handler con una instancia de `BackgroundTasks` que verifica que la tarea quedó **agendada** (no ejecutada) al retornar.

## Risks / Trade-offs

- [Capturar `StockInsuficienteError` dentro del bloque y seguir usando la sesión abortada → `InFailedSQLTransactionError`/500] → traducir sólo fuera del `async with`; test C-11 verifica 409 y conteos intactos; test estático busca `except StockInsuficienteError` sólo fuera del bloque (revisión en verify).
- [Interbloqueo terminar vs. alta/terminar con repuestos compartidos] → orden global D3 + test de dos terminaciones que comparten repuestos en orden inverso de ítems.
- [`populate_existing` olvidado en `bloquear` → se decide con un estado viejo del mapa de identidad] → siempre `populate_existing`; test de concurrencia lo detecta.
- [El aviso se pierde si el proceso se reinicia] → aceptado (DD-10).
- [Test de "después de la respuesta" frágil con `ASGITransport` (ejecuta las tareas antes de devolver)] → se afirma "agendado y no ejecutado" llamando al handler con `BackgroundTasks` propio; el HTTP sólo afirma "exactamente uno tras 200".
- [El seed aún no existe: el caso C-11 depende de ayudantes] → `escenario_c11` replica los datos de la KB 04 (bujía stock 2, 4 en la orden, asignada a `mecanico`); C-12 lo repetirá sobre el seed real.
- [Baja de vehículo concurrente con cancelación da 409 aunque al instante se pudiera] → aceptado (conservador, D10).
- [404 antes que 403 en `cancelar`/`terminar` revela existencia de ids a no-personal] → aceptado (D4-b), igual que C-09.

## Migration Plan

Sin migraciones. Despliegue: código nuevo en `app/modules/ordenes/` y una constante en `repuestos/stock.py`; `main.py` no cambia. Rollback: quitar los tres handlers (las tablas y el resto de rutas quedan intactas).

## Decisiones a aprobar (resumen)

1. **D1-a** — Tabla de transiciones en código; test de coherencia con `es_final` del catálogo canónico (no se consulta `es_final` en runtime para transicionar).
2. **D2-a** — Bloqueo `FOR UPDATE` de la orden antes de decidir permiso (también cuando termina en 403).
3. **D4-a** — `terminar` con `requiere_rol(MECANICO, ADMIN)` en la ruta + "asignado o ADMIN" en el servicio (CLIENTE/RECEPCION → 403 antes de 404).
4. **D4-b** — Orden 404 → 403 → 409 en `terminar` y `cancelar`; en `iniciar` 403 (rol) → 422 → 404 → 409.
5. **D4-c** — MECANICO que no es dueño no cancela (403).
6. **D4-d** — Catálogo sin el estado destino → 409 `CatalogoSinCargarError` (lectura previa + traducción de FK por nombre).
7. **D5-a** — Stock insuficiente detectado por `mover_stock` (CHECK + error tipado), sin pre-lectura `FOR UPDATE` (desvío menor de SU-04).
8. **D5-b** — El 409 nombra el primer repuesto insuficiente por `repuesto_id` (`codigo`).
9. **D6-a** — Motivo `"Terminación de orden"` (constante en `stock.py`); autor del movimiento e historial = actor.
10. **D6-b** — Se descuenta también un repuesto dado de baja después del alta.
11. **D7-a** — Aviso por `cliente_id` (también clientes sin usuario); excepciones del aviso se registran y no se propagan.
12. **SU-C10-1** — Pendiente pre-asignada (sólo por SQL/seed): mismo mecánico la inicia; otro → 409 `OrdenAsignadaAOtroError`.
13. **SU-C10-2** — Las rutas de transición no tienen cuerpo; un cuerpo enviado se ignora (no hay contrato que validar).
