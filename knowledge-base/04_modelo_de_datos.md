# Modelo de Datos

**Los nombres de tablas y columnas son obligatorios**: los casos de prueba y la corrección los usan. Se pueden **agregar** columnas, pero **no quitar ni renombrar** las indicadas.

Convenciones: todas las fechas son `timestamptz`; el dinero es `NUMERIC` y en Python `Decimal` (nunca `float`); **cada clave foránea lleva un índice** (PostgreSQL no lo crea solo).

## Dominios

| Dominio | Tablas |
|---|---|
| Acceso y seguridad | `usuario`, `asignacion_rol`, `intento_acceso`, `evento_seguridad` |
| Clientes | `cliente`, `vehiculo` |
| Inventario | `repuesto`, `movimiento_stock`, `historial_precio_repuesto` |
| Órdenes | `estado_orden` (catálogo), `orden_trabajo`, `item_orden`, `historial_estado_orden` |

## ERD (según Figura 1 del PDF, pág. 4)

```
Cliente 1 ──── 0..* Vehiculo 1 ──── 0..* OrdenTrabajo
   │ 0..1                                  │ 1 ◆──── 1..* ItemOrden ──── 0..* ► Repuesto
   │ (1 a 1, usuario_id UNIQUE)            │ 1 ◆──── 0..* HistorialEstadoOrden «appendOnly»
Usuario 1 ── rol ── 0..* AsignacionRol     │ 0..* ──► EstadoOrden «catalog»   (FK estado)
   ▲ 0..1                                  └ 0..* ──► Usuario (mecanico_id, nulo)
   └─ mecánico de la orden
Repuesto 1 ── 0..* MovimientoStock «appendOnly»
Repuesto 1 ── 0..* HistorialPrecio «appendOnly»
IntentoAcceso, EventoSeguridad: sin relaciones
```

- `◆` = **composición** (un ítem no existe sin su orden; viaja dentro del alta de la orden).
- Asociaciones con `→`. `«catalog»` = tabla de referencia que carga `seed.py`. `«appendOnly»` = protegida por el disparador.
- Navegación declarada **en los dos extremos** de cada relación que se lea. `Usuario.cliente` devuelve **un objeto, no una lista**.

## Entidades

### `usuario`
- `id`, `email`, `nombre`, `password_hash`, `activo`, `debe_cambiar_password`, `password_cambiada_en` (con zona, nulo permitido).
- **Constraint**: `email` UNIQUE. **Sin columna `rol`.**

### `asignacion_rol`
- `id`, `usuario_id`, `rol`, `desde`, `vence_en` (nulo), `revocada_en` (nulo), `otorgada_por` (nulo).
- **CHECK** `rol` ∈ {ADMIN, RECEPCION, MECANICO, CLIENTE}.
- **Índice único parcial** (`usuario_id`, `rol`) `WHERE revocada_en IS NULL`.

### `intento_acceso`
- `id`, `cuando`, `email`, `ip`, `exito`. **Índice** (`email`, `ip`, `cuando`). Sin relación con otras tablas.

### `evento_seguridad`
- `id`, `cuando`, `actor` (**texto**), `accion`. Sin restricciones extra.

### `cliente`
- `id`, `usuario_id` (nulo permitido), `nombre`, `documento`, `telefono`.
- `usuario_id` UNIQUE (uno a uno opcional); `documento` UNIQUE.

### `vehiculo`
- `id`, `cliente_id`, `patente`, `marca`, `modelo`, `anio`, `borrado_en` (nulo).
- **Índice único parcial** (`patente`) `WHERE borrado_en IS NULL`; **CHECK** `anio BETWEEN 1950 AND 2100`.

### `repuesto`
- `id`, `codigo`, `descripcion`, `precio` NUMERIC(10,2), `stock`, `borrado_en` (nulo).
- **Índice único parcial** (`codigo`) `WHERE borrado_en IS NULL`; **CHECK** `precio > 0`; **CHECK** `stock >= 0`.

### `estado_orden` (catálogo)
- `codigo` (**PK**, texto), `descripcion`, `posicion`, `es_final`. `posicion` UNIQUE.
- La migración la crea **vacía**; `seed.py` carga las filas. `es_final` decide qué es una orden abierta (RN-16).

### `orden_trabajo`
- `id`, `vehiculo_id`, `mecanico_id` (nulo), `estado`, `falla`, `creada_en`, `total` NUMERIC(12,2).
- `estado` **FK → `estado_orden.codigo`** (no un CHECK con lista); **CHECK** `total >= 0`.

### `item_orden`
- `id`, `orden_id`, `repuesto_id`, `cantidad`, `precio_unitario` NUMERIC(10,2).
- **CHECK** `cantidad > 0`; **CHECK** `precio_unitario > 0`; **UNIQUE** (`orden_id`, `repuesto_id`).

### `historial_estado_orden` — sólo agregado
- `id`, `orden_id`, `desde_estado` (nulo), `hasta_estado`, `usuario_id`, `cuando`.
- `desde_estado` y `hasta_estado` son FK → `estado_orden.codigo`.

### `movimiento_stock` — sólo agregado
- `id`, `repuesto_id`, `orden_id` (nulo), `usuario_id`, `cantidad`, `motivo`, `cuando`. **CHECK** `cantidad <> 0`.

### `historial_precio_repuesto` — sólo agregado
- `id`, `repuesto_id`, `usuario_id`, `precio_anterior` NUMERIC(10,2), `precio_nuevo` NUMERIC(10,2), `cuando`.
- **CHECK** `precio_nuevo > 0`; **CHECK** `precio_nuevo <> precio_anterior`.

## Garantías delegadas a la base

| Garantía | Mecanismo |
|---|---|
| Unicidad de email / documento | UNIQUE |
| Unicidad de patente / código entre vigentes | Índice único parcial `WHERE borrado_en IS NULL` |
| Una asignación abierta por rol | Índice único parcial `WHERE revocada_en IS NULL` |
| Estado de orden válido | FK al catálogo |
| Sólo-agregado | **Disparador** (migración 2, escrita a mano) rechaza UPDATE/DELETE en las 3 tablas |
| Valores válidos | CHECKs (precio, stock, cantidad, anio, total, rol…) |

## Migraciones (Alembic, plantilla asincrónica; sin `create_all`)

1. **Migración 1** — `--autogenerate`, todas las tablas (catálogo vacío). Se lee antes de aplicar y lleva comentario que lo diga.
2. **Migración 2** — **escrita a mano**: función + disparador de sólo-agregado sobre `historial_estado_orden`, `movimiento_stock`, `historial_precio_repuesto` (autogenerate no ve funciones ni disparadores). Lleva comentario.
3. `alembic upgrade head` → `downgrade base` → `upgrade head` deben funcionar.

## Seed data inicial (`seed.py`)

`seed.py` **vacía las tablas** y carga como mínimo (el catálogo **primero**; es parte de la puesta en marcha, no un extra):

| Qué | Datos |
|---|---|
| Catálogo de estados | PENDIENTE (pos. 1), EN_REPARACION (2), TERMINADA (3, final), CANCELADA (4, final), cada uno con descripción |
| Usuarios | `admin@example.com`, `admin2@example.com` (ADMIN); `recepcion@example.com` (RECEPCION); `mecanico@example.com`, `mecanico2@example.com` (MECANICO); `cliente@example.com` (CLIENTE); `nuevo@example.com` (MECANICO, **con cambio de contraseña obligatorio**) |
| Clientes | **Laura** (con usuario `cliente@example.com`, dos vehículos); **Jorge** (sin usuario, un vehículo) |
| Repuestos | Filtro de aceite (stock 10, `FIL-001`), pastillas de freno (4, `FRE-010`), bujía (2), aceite por litro (20, `ACE-530`); cada stock cargado como movimiento "Stock inicial" |
| Órdenes | #1 PENDIENTE, primer vehículo de Laura. #2 EN_REPARACION, vehículo de Jorge, asignada a `mecanico@example.com`, con **4 bujías cuando hay 2** (para el caso C-11) |
| Historial de precios | Una línea del filtro de aceite: 8000 → 8500 |
| Historial de seguridad | Una línea con actor `SISTEMA`: "Carga de los datos iniciales" |

Las contraseñas de seed son de mentira y **viven sólo en `seed.py`** (DD-15). Cumplen el mínimo de 8 caracteres (DD-16).
