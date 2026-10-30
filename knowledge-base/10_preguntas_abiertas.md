# Preguntas Abiertas

## Inconsistencias detectadas

### IN-01 — Rol requerido por `POST /repuestos/{id}/reponer` vs. rol "ADMIN" en el contexto
**Contexto del PDF**: "el administrador mantiene el catálogo y repone el stock". **Tabla de endpoints**: `reponer` = ADMIN. Coinciden; se deja como ADMIN. **Impacto**: ninguno; se anota por la ambigüedad de la extracción de texto original.

### IN-02 — `iniciar` sólo MECANICO
**Tabla**: `POST /ordenes/{id}/iniciar` = MECANICO (sin ADMIN). Mientras que `terminar` admite ADMIN. **Impacto**: un ADMIN sin rol MECANICO no puede iniciar. **Resolución propuesta**: respetar la tabla (sólo MECANICO).

### IN-03 — Códigos de `iniciar` sin 403
**Tabla**: `iniciar` lista 200, 404, 409. Pero la ruta lleva `requiere_rol(MECANICO)` y el grupo protegido responde 403 (rol insuficiente/cambio pendiente). **Resolución**: 403 por rol/cambio pendiente es implícito en el grupo protegido.

### IN-04 — `POST /auth/logout` "Cualquiera"
**Tabla**: grupo Abierto, quién = Cualquiera, 200. **Resolución**: logout idempotente sin exigir sesión.

### IN-05 — Nombre del módulo/tabla de historial de precios
El modelo usa `historial_precio_repuesto` (tabla) y `HistorialPrecio` (clase en la Figura 1). **Resolución**: tabla `historial_precio_repuesto`; clase `HistorialPrecio` (nombre de tabla es el obligatorio).

## Preguntas abiertas — RESUELTAS por el equipo

Todas las resoluciones están registradas como decisiones DD-13..DD-22 en [09_decisiones_y_supuestos.md](09_decisiones_y_supuestos.md).

| Prioridad | Pregunta | Resolución | Decisión |
|---|---|---|---|
| Alta | Nombres de variables de entorno (clave JWT, duración, bcrypt, semáforo, pool, Secure) | Nombres descriptivos con prefijo uniforme | DD-13 |
| Alta | Cuerpo de `POST /usuarios` y de `POST /usuarios/{id}/roles` | `POST /usuarios` con rol inicial **obligatorio**; `/roles` con `{rol, vence_en?}` | DD-14 |
| Alta | Contraseñas de los usuarios semilla | Fijas, de mentira, definidas sólo en `seed.py` | DD-15 |
| Media | Política de contraseña | Mínimo 8 caracteres + máximo 72 bytes | DD-16 |
| Media | Valores concretos (bcrypt, semáforo, pool, token) | bcrypt 12, semáforo 4, pool 5/10, token 30 min; todo configurable | DD-17 |
| Media | `GET /ordenes` del MECANICO | Asignadas a él + pendientes sin asignar | DD-18 (reemplaza SU-07) |
| Media | Forma de `GET /auth/yo` | Roles vigentes consultados a la base | DD-19 |
| Media | Cuerpo/respuesta de `reponer` | `{cantidad}` entero > 0; responde el repuesto actualizado | DD-20 |
| Baja | Formato del aviso simulado | `logger.info` con texto fijo | DD-21 |
| Baja | Formato de evidencia C-14/C-15 | PNG | DD-22 |

## Discovery inferido con baja confianza

- [DISCOVERY] `scale` se infirió como `public_multi_user (inferred, low confidence)`. **Resuelto**: se trata como proyecto académico, manteniendo igualmente las reglas duras de seguridad (ver SU-01).
