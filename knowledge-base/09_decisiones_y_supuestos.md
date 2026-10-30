# Decisiones y Supuestos

## Decisiones documentadas (impuestas por el PDF)

### DD-01 — Roles en tabla propia con vigencia
**Decisión**: `usuario` sin columna `rol`; roles = filas vigentes de `asignacion_rol` (no revocadas, sin vencer), consultadas en cada petición.
**Contexto**: la autorización debe poder revocarse sin esperar al vencimiento del token.
**Alternativas**: roles dentro del JWT; columna `rol` en usuario.
**Justificación**: la decisión se toma en la base, no en el token; queda historial de quién tuvo qué rol.
**Trade-offs**: una consulta extra por petición.

### DD-02 — Catálogo `estado_orden` en lugar de CHECK
**Decisión**: estados como filas de catálogo con FK; enum en código como contrato de API y vocabulario de transiciones.
**Justificación**: cada estado lleva datos propios (`es_final`, `posicion`) que la API puede mostrar y las consultas cruzar.
**Trade-offs**: enum y catálogo deben coincidir; agregar un estado obliga a tocar catálogo, enum y servicio. Si el catálogo está vacío no hay órdenes (409).

### DD-03 — Unicidad parcial para borrado lógico
**Decisión**: patente y código con índice único parcial `WHERE borrado_en IS NULL`.
**Justificación**: un UNIQUE común impediría registrar un auto vendido con la misma patente.

### DD-04 — Sólo-agregado por disparador
**Decisión**: disparador (migración 2, a mano) en `historial_estado_orden`, `movimiento_stock`, `historial_precio_repuesto`.
**Alternativas**: permisos del rol de base (no se pide; el TP usa un solo rol; tener ambos sería defensa en profundidad).

### DD-05 — `intento_acceso` en sesión y transacción propias
**Decisión**: única escritura fuera de la transacción de su petición.
**Justificación**: el fallo que se quiere contar es el mismo que revierte la petición.
**Trade-off aceptado**: deja filas aunque la petición falle (se declara en un comentario).

### DD-06 — Hash antes de abrir la transacción
bcrypt tarda ~300 ms; adentro retendría una conexión sin usar la base. Siempre `to_thread` + semáforo.

### DD-07 — Dos grupos de rutas en `main.py`
FastAPI suma dependencias y no las resta; el grupo protegido lleva el control de cambio obligatorio montado **una vez**; el abierto lo excluye.

### DD-08 — `iat` sin truncar
Comparación con `password_cambiada_en` en precisión completa; el token del propio cambio se emite **después** de anotar el cambio.

### DD-09 — `cancelar` sin `requiere_rol`
El dueño del vehículo no tiene rol de personal; el servicio decide (403 antes que 409).

### DD-10 — Aviso con `BackgroundTasks`
Aceptado a sabiendas: se pierde si el proceso se reinicia y no hay reintento (cap. 8 lo resuelve con colas).

### DD-11 — Concurrencia diferida
La actualización perdida del stock no se evalúa (cap. 7). Se acepta.

### DD-12 — Motor y fábrica en el lifespan
Evita recursos creados antes de que exista el bucle de eventos (EA-08, sec. 1.9).

## Decisiones del equipo (resolución de preguntas abiertas)

### DD-13 — Nombres de variables de entorno
**Decisión**: además de `POSTGRES_*` y `SQL_ECHO` (dados por el PDF): `JWT_SECRET_KEY`, `JWT_EXPIRE_MINUTES`, `BCRYPT_ROUNDS`, `BCRYPT_MAX_CONCURRENCY`, `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `COOKIE_SECURE`. Todas en `Settings` (pydantic-settings); `JWT_SECRET_KEY` y la contraseña de la base sin valor por defecto.
**Trade-off**: si la cátedra espera otros nombres hay que renombrar en `Settings`, `env.example` y tests (costo bajo).

### DD-14 — Cuerpos de `POST /usuarios` y `POST /usuarios/{id}/roles`
**Decisión**: `POST /usuarios` recibe `{email, nombre, password, rol}` con **rol inicial obligatorio** (el usuario nunca queda sin rol; crea la fila de `asignacion_rol` en la misma transacción). `POST /usuarios/{id}/roles` recibe `{rol, vence_en?}` (`vence_en` opcional, debe ser futuro). Ambos con `extra="forbid"`.
**Trade-off**: la lógica de asignación de rol se comparte entre los dos endpoints (extraer a una función del servicio).

### DD-15 — Contraseñas del seed viven sólo en `seed.py`
**Decisión**: las contraseñas de los usuarios semilla son de mentira y están definidas **únicamente en `seed.py`** (como dice el PDF). No van en variables de entorno, `env.example` ni otro archivo. Cumplen el mínimo de 8 caracteres (DD-16).
**Contexto**: no viola la regla dura de secretos, que apunta a la clave JWT y la contraseña de la base; estas son datos de demostración sin valor real. **Revierte** la primera versión de esta decisión (variables `SEED_*_PASSWORD`).
**Trade-off**: las contraseñas de demo quedan en el repo; se acepta porque son ficticias y el seed sólo corre en desarrollo/corrección.

### DD-16 — Política de contraseña
**Decisión**: mínimo 8 caracteres y máximo 72 bytes (límite de bcrypt). Las contraseñas del seed deben cumplir el mínimo.

### DD-17 — Valores por defecto de rendimiento y seguridad
**Decisión**: bcrypt 12 rondas, semáforo 4, pool 5 + overflow 10, token **30 min** (`JWT_EXPIRE_MINUTES=30`, coincide con `expira_en_segundos: 1800` del PDF, SU-03). Todos configurables por entorno; la suite de tests puede bajar `BCRYPT_ROUNDS` (p. ej. 4) para no demorar.

### DD-18 — `GET /ordenes` para MECANICO
**Decisión**: ve las órdenes con `mecanico_id` = su id **más** las que no tienen mecánico asignado (`mecanico_id IS NULL`). ADMIN y RECEPCION ven todas. **Reemplaza SU-07.**
**Trade-off**: requiere un filtro condicional por rol en el repositorio. Con el seed, `mecanico2@example.com` no ve la orden #2 (asignada a `mecanico@example.com`).
**Pendiente a definir al proponer el change de órdenes**: si `iniciar` sobre una orden sin mecánico la asigna al que la inicia (hoy el PDF no lo explicita).

### DD-19 — `GET /auth/yo`
**Decisión**: devuelve los roles **vigentes consultados a la base** en cada llamada, coherente con DD-01 (no los del token).

### DD-20 — `POST /repuestos/{id}/reponer`
**Decisión**: cuerpo `{cantidad}` (entero > 0, `extra="forbid"`); registra un `movimiento_stock` con cantidad positiva y devuelve el repuesto actualizado. El `motivo` del movimiento lo fija el servicio (p. ej. "Reposición").

### DD-21 — Aviso simulado al cliente
**Decisión**: `logger.info` con formato estable, p. ej. `Aviso a cliente {cliente_id}: orden {orden_id} terminada`, ejecutado en `BackgroundTasks` (ver DD-10).

### DD-22 — Evidencia C-14/C-15
**Decisión**: capturas en PNG con el comando y la respuesta visibles.

## Supuestos inferidos

### SU-01 — Escala "pública multiusuario"
**Supuesto**: `scale = public_multi_user`. **Origen**: los clientes se auto-registran en la web. **Riesgo si es falso**: sobredimensionar pool/límites. **Validar**: confirmar con la cátedra (es un TP académico, uso real acotado).

### SU-02 — Nombres de variables de entorno no fijados
**Supuesto**: sólo `POSTGRES_*` y `SQL_ECHO` vienen dados; el resto (clave JWT, duración, costo bcrypt, semáforo, Secure, pool) se nombra libremente. **Riesgo**: que la corrección espere nombres concretos. **Validar**: revisar `env.example` esperado.

### SU-03 — Duración del token = 1800 s
**Origen**: ejemplo de respuesta de login (`expira_en_segundos: 1800`). El PDF no la fija como requisito.

### SU-04 — Terminar con stock insuficiente
**Supuesto**: la validación explícita en el servicio da el 409 (el CHECK `stock >= 0` es la red de seguridad). **Origen**: RN-13 + caso C-11.

### SU-05 — Movimiento de salida con cantidad negativa
**Supuesto**: salidas = `cantidad < 0`, entradas/reposición > 0 (CHECK `cantidad <> 0`). **Origen**: el CHECK admite signo; el PDF no lo explicita.

### SU-06 — Autoría de `otorgada_por`
**Supuesto**: id del admin que asigna; nulo para datos de seed/registro. **Origen**: columna nula permitida sin más detalle.

### SU-07 — `GET /ordenes` del mecánico (REEMPLAZADO por DD-18)
~~Los roles de personal ven todas las órdenes.~~ El equipo decidió que el MECANICO ve sólo las asignadas a él más las sin asignar (DD-18). ADMIN y RECEPCION siguen viendo todas.

### SU-08 — PATCH de repuestos
**Supuesto**: sólo `descripcion` y `precio`; `codigo` y `stock` fuera. **Origen**: "PATCH /repuestos/{id} (descripción y precio)" + RN-14.

### SU-09 — Lectura de las 22 páginas
**Supuesto**: la KB refleja el PDF **leído como imagen** (incluida la Figura 1), no sólo el texto extraído, que mezclaba tablas (roles de endpoints y códigos).
