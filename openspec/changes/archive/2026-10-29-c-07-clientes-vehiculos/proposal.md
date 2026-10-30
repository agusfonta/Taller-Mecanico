# Proposal — C-07 `clientes-vehiculos`

## Why

Tras C-05 la API autentica y autoriza, y el auto-registro ya crea fichas de `cliente`, pero **el personal no puede cargar clientes ni vehículos** y un cliente no puede ver sus autos. Sin vehículos vigentes no hay órdenes de trabajo: C-09 (`POST /ordenes` recibe `vehiculo_id`) depende de este change y de C-08 (GATE 5). Además concentra puntaje evaluable: unicidad entre vigentes y borrado lógico (Ej. 2/6, caso C-19), contratos y CRUD (Ej. 3), "lo propio" de RN-17 (Ej. 5) y lectura sin N+1 (Ej. 8).

## What Changes

- **Módulo `app/modules/clientes/`** completo (hoy sólo tiene `models.py` y un `ClienteRepository` mínimo de C-05): `schemas.py`, `repository.py` (se **extiende** `ClienteRepository` sin romper el uso del registro y se agrega `VehiculoRepository` sobre `SoftDeleteRepository`), `unit_of_work.py` (`ClientesUoW` + dependencia que lo construye), `service.py` y `router.py`.
- **5 rutas en el grupo protegido** (KB 06 Épica 4, KB 03 matriz RBAC):
  - `POST /clientes` (RECEPCION, ADMIN; 201/409/422): ficha sin usuario; documento repetido → 409 con mensaje propio, sin consulta previa (lo garantiza `uq_cliente_documento`).
  - `GET /clientes/{id}` (RECEPCION, ADMIN; 200/404): el cliente con sus vehículos **vigentes** precargados (`selectinload`, número fijo de consultas, sin N+1).
  - `POST /clientes/{id}/vehiculos` (RECEPCION, ADMIN; 201/404/409/422): `anio` 1950–2100 (422 en el contrato), patente normalizada; patente **vigente** repetida → 409 (índice único parcial `uq_vehiculo_patente_vigente`, DD-03).
  - `DELETE /vehiculos/{id}` (RECEPCION, ADMIN; 204/404/409): borrado lógico (`borrado_en`); con órdenes abiertas (estado cuyo `estado_orden.es_final` es falso) → 409; la patente queda libre para un alta nueva (RN-16, Flujo 9, C-19).
  - `GET /mis-vehiculos` (cualquier autenticado; 200): sólo los vehículos vigentes de la ficha vinculada al usuario de la sesión; sin ficha → lista vacía (RN-17).
- **Traducción de `IntegrityError` a 409** por nombre de restricción reutilizando `app/core/errores.restriccion_violada` (C-05); nunca texto de la base (RN-18).
- **Contrato de lectura para C-09** (definido, no implementado como endpoint): búsqueda de un vehículo vigente para abrir una orden, con bloqueo compartido coordinado con el bloqueo de la baja.
- **`main.py`**: registra el router del módulo en el grupo protegido (archivo compartido con C-06/C-08; ver design).
- **Tests** (Strict TDD): unitarios de contratos/normalización y de integración HTTP contra **PostgreSQL real** con el esquema migrado (reutiliza la infraestructura `esquema_auth`/`app_auth` de C-05): unicidad parcial de patente, baja con orden abierta, reutilización de patente, aislamiento de `/mis-vehiculos`, 401/403 por rol, número fijo de consultas del detalle.

## Capabilities

### New Capabilities
- `clientes`: alta de clientes por el personal (contrato, 409 por documento) y consulta de un cliente con sus vehículos vigentes precargados.
- `vehiculos`: alta de vehículos de un cliente (contrato, normalización de patente, 409 entre vigentes), baja lógica con control de órdenes abiertas y reutilización de patente, y `GET /mis-vehiculos` con aislamiento por dueño.

### Modified Capabilities
- Ninguna. `registro-clientes` (C-05) no cambia: el auto-registro sigue usando `ClienteRepository.add` y su 409 por documento; `repositorios` y `modelo-de-datos` ya cubren el borrado lógico y la unicidad parcial que este change usa.

## Impact

- **Código nuevo**: `app/modules/clientes/{schemas,unit_of_work,service,router}.py`; tests `test/unit/test_schemas_clientes.py`, `test/integration/test_clientes_*.py`, `test/integration/test_vehiculos_*.py` y un módulo de ayudantes de siembra propio del change.
- **Código modificado**: `app/modules/clientes/repository.py` (extensión compatible), `main.py` (registro del router, compartido), `test/integration/conftest.py` (sólo si hace falta un punto de extensión para montar routers protegidos reales en `app_auth`; compartido).
- **APIs**: 5 rutas nuevas en el grupo protegido.
- **Datos**: sin migraciones; usa `cliente`, `vehiculo`, `orden_trabajo` y `estado_orden` tal como las dejó C-03.
- **Dependencias**: ninguna nueva.
- **Desbloquea**: C-09 (junto con C-08).
- **Fuera de alcance**: listado/búsqueda de clientes (no figura en la KB), edición de clientes o vehículos, vincular una ficha cargada por el personal con un usuario web, `seed.py` (C-11), archivos `.http` (C-12), órdenes (C-09/C-10).
- **Governance**: **MEDIO** — implementar con checkpoints y exponer las decisiones no obvias (supuestos SU-C07-*); no requiere banner de aprobación previa.
