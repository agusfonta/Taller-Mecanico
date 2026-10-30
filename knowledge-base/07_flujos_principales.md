# Flujos Principales

## Flujo 1: Registro de cliente
**Disparador**: `POST /auth/registro`. **Actor**: visitante.

1. Router valida el contrato (`extra="forbid"`, contraseña ≤ 72 bytes).
2. Servicio calcula el hash bcrypt **antes** de abrir la transacción (`to_thread` + semáforo).
3. Abre el UoW (`async with`): inserta `usuario`, `asignacion_rol` (CLIENTE) y `cliente`.
4. Al salir del bloque el UoW confirma las **tres** filas; ante excepción revierte las tres.
5. Se registra el evento de seguridad; responde 201.

**Errores**: correo o documento repetido → `IntegrityError` traducido a 409 con mensaje propio (la base garantiza la unicidad, sin consulta previa); contraseña > 72 bytes → 422.

## Flujo 2: Login
**Disparador**: `POST /auth/login`.

```
Cliente → Router → Servicio
  1. ¿≥5 fallos (email, ip) en 60 s desde el último éxito?  ── sí ─► 429 + Retry-After (sin hash)
  2. Busca usuario; si no existe usa el hash ficticio (calculado en el lifespan)
  3. bcrypt.verify (to_thread + semáforo)
  4. Anota intento_acceso en SESIÓN y TRANSACCIÓN PROPIAS (se confirma siempre)
  5. Éxito: emite JWT {sub, iat (fraccional), exp, roles} → Set-Cookie access_token
     (HttpOnly, SameSite=Lax, Max-Age, Secure configurable); cuerpo sin token
```

**Errores**: correo inexistente o clave mala → 401 con el mismo cuerpo y tiempo parecido. Un login correcto reinicia la cuenta de fallos (las filas siguen, dejan de contar).
**Nota**: es la **única** escritura fuera de la transacción de su petición; el código lo declara en un comentario con su costo (deja filas aunque la petición falle).

## Flujo 3: Petición autenticada y autorizada
1. `get_usuario_actual` lee `request.cookies["access_token"]`; **401** si falta, es inválido/vencido, el usuario no existe/está inactivo, o `iat` < `password_cambiada_en` (sin truncar).
2. El grupo protegido aplica el control de cambio obligatorio (**403** si pendiente).
3. `requiere_rol(...)` consulta `asignacion_rol` vigentes **en la base** → **403** si no alcanza.
4. El router construye el UoW y llama al servicio.

Revocar un rol corta el permiso en la petición siguiente, con la misma cookie.

## Flujo 4: Cambio obligatorio de contraseña
1. Usuario con `debe_cambiar_password` inicia sesión (login normal; el cuerpo informa `debe_cambiar_password: true`).
2. Todo fuera de `/auth/*` y `/health/*` → 403.
3. `POST /auth/cambiar-password` (valida la actual, nueva ≤ 72 bytes): anota `password_cambiada_en`, **después** emite el token nuevo.
4. Cookie nueva vale; la anterior da 401 (aun en el mismo segundo).

## Flujo 5: Alta de una orden de trabajo
**Disparador**: `POST /ordenes {vehiculo_id, falla, items[]}`. **Actor**: recepción/admin.

1. Valida contrato (≥ 1 ítem, sin repuesto repetido, cantidad > 0).
2. UoW único: verifica catálogo de estados (vacío → 409), vehículo vigente, repuestos vigentes.
3. Crea `orden_trabajo` (PENDIENTE), `item_orden` con **precio copiado**, calcula `total`, agrega la primera línea de `historial_estado_orden` (`desde_estado = null`).
4. Confirma; responde 201 con ítems/subtotales e historial.

**Errores**: repuesto/vehículo inexistente o de baja → 409 y no queda nada.

## Flujo 6: Ciclo de vida de la orden

```
            iniciar (MECANICO, queda asignado)       terminar (asignado o ADMIN)
PENDIENTE ────────────────────────► EN_REPARACION ─────────────────────────► TERMINADA (final)
    │ cancelar (RECEPCION, ADMIN, dueño)
    └──────────────────────────────► CANCELADA (final)
```
Cualquier otra transición → 409. En `cancelar` el permiso (403) se evalúa **antes** que el estado (409).

## Flujo 7: Terminar una orden (operación multi-escritura)
1. Servicio abre un único UoW. Verifica permiso (mecánico asignado o ADMIN → 403) y estado (EN_REPARACION → 409).
2. Para cada ítem: descuenta stock mediante el **punto único de escritura de stock**; inserta `movimiento_stock` (cantidad negativa, `orden_id`).
3. Cambia el estado y agrega línea en `historial_estado_orden`.
4. Si algún repuesto no alcanza (CHECK `stock >= 0` / validación) → 409 y **se revierte todo**: estado, stock, movimientos e historial quedan como estaban (caso C-11).
5. Al confirmar, `BackgroundTasks` agenda el aviso al cliente (`await asyncio.sleep(0.5)` + log), que corre **después** de enviar la respuesta y sólo si hubo commit.

## Flujo 8: Reposición de stock y cambio de precio
- `reponer`: UoW → movimiento positivo + stock en el punto único.
- `PATCH /repuestos/{id}`: si cambia el precio, escribe `historial_precio_repuesto` en la **misma** transacción; si no cambia, no deja línea.

## Flujo 9: Baja de vehículo
`DELETE /vehiculos/{id}`: si tiene órdenes con estado no final → 409; si no, `borrado_en = now()` → 204. La patente queda libre (índice único parcial).

## Flujo 10: Arranque y apagado (lifespan)
Arranque: lee `Settings` → crea motor y fábrica de sesiones en `app.state` → calcula el hash ficticio. Apagado: `engine.dispose()`.
Puesta en marcha del proyecto: `alembic upgrade head` → `python seed.py` → `uvicorn`.
