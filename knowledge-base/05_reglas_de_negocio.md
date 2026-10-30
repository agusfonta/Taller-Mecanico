# Reglas de Negocio

El PDF numera las reglas **RN-01 a RN-20** de forma correlativa (sin dominio en el código). Se conservan los códigos originales porque los enunciados, ejercicios y casos de prueba los referencian. Agrupación por dominio añadida para navegación.

## Dominio: Unicidad y registro

- **RN-01** — El correo de un usuario y el documento de un cliente son únicos. La patente de un vehículo y el código de un repuesto son únicos **entre los que no están dados de baja**. *Garante*: UNIQUE e índices únicos parciales en la base; 409 con mensaje propio.
- **RN-02** — El auto-registro crea el usuario, su rol CLIENTE y su ficha de cliente: **o quedan las tres filas, o ninguna**. Si el documento ya es de un cliente del taller, el registro da 409 y **no se apropia de esa ficha**. *Garante*: un solo Unit of Work.

## Dominio: Roles y autorización

- **RN-03** — Un usuario tiene a lo sumo una asignación abierta por rol. *Garante*: índice único parcial; 409.
- **RN-04** — Los permisos se deciden con los roles vigentes **en la base, en cada petición**. Los roles que trae el token son informativos. *Garante*: dependencia que consulta `asignacion_rol`.
- **RN-05** — Un administrador no puede revocarse su propio rol ADMIN, y el sistema nunca queda sin administradores vigentes. *Garante*: comprobación en el servicio; 409.
- **RN-06** — Mientras un usuario tenga el cambio de contraseña pendiente, sólo puede usar las rutas de `/auth` y las de salud. *Garante*: dos grupos de rutas; 403.
- **RN-17** — Lo propio sólo pide estar autenticado: un cliente ve sus vehículos y las órdenes de sus vehículos, y ninguna otra. *Garante*: `/mis-*` y comprobación de dueño; 403.

## Dominio: Sesión y login

- **RN-07** — Al cambiar la contraseña, las sesiones emitidas antes dejan de valer, **aunque sean del mismo segundo** que el cambio; la que devuelve el propio cambio, no. *Garante*: comparación de `iat` con `password_cambiada_en` **sin truncar**; 401.
- **RN-08** — Después de **5 intentos fallidos** con el mismo correo desde la misma dirección en **60 segundos**, el login responde **429 sin verificar la contraseña**. Un login correcto reinicia la cuenta: los fallos anteriores siguen en la tabla pero dejan de contar. *Garante*: conteo sobre `intento_acceso`; `Retry-After`.
- **RN-09** — El login responde lo mismo, **y tarda lo mismo**, exista o no el correo. *Garante*: mismo mensaje; verificación contra un hash ficticio.

## Dominio: Órdenes de trabajo

- **RN-10** — Una orden nace PENDIENTE con **al menos un ítem** y sin repuestos repetidos. El precio de cada ítem se copia del repuesto y el total lo calcula el servidor. *Garante*: DTO; el precio y el total nunca viajan en el cuerpo.
- **RN-11** — Transiciones permitidas: PENDIENTE → EN_REPARACION (la inicia un mecánico, que queda asignado); EN_REPARACION → TERMINADA (la termina el mecánico asignado o un admin); PENDIENTE → CANCELADA. *Garante*: servicio; 409 si el estado no lo permite.
- **RN-12** — Cancelan una orden la recepción, el administrador o **el dueño del vehículo**. **El permiso se evalúa antes que el estado.** *Garante*: servicio; 403 antes que 409.
- **RN-13** — Terminar una orden descuenta el stock de cada ítem, deja un movimiento por cada salida y una línea de historial. Si un repuesto no alcanza, **no queda ninguna de esas escrituras**. *Garante*: un solo Unit of Work; 409.
- **RN-19** — Los estados posibles de una orden son las filas del catálogo `estado_orden`. El catálogo se consulta desde la API y **no se edita desde ella**. Si está vacío, crear una orden responde 409 con mensaje propio. *Garante*: clave foránea; repositorio de sólo lectura.

## Dominio: Inventario

- **RN-14** — El stock de un repuesto sólo cambia a través de movimientos: el alta con stock inicial, la reposición y la terminación de órdenes. **No se edita por PATCH.** *Garante*: punto único de escritura de stock.
- **RN-16** — Un vehículo o repuesto dado de baja deja de aparecer y no se puede usar en órdenes nuevas, pero sus datos se conservan. Un vehículo con **órdenes abiertas** (estado que el catálogo no marca como final) no se da de baja. *Garante*: borrado lógico; `es_final`; 409.
- **RN-20** — Cada cambio del precio de un repuesto deja una línea en `historial_precio_repuesto`, **en la misma transacción** que el cambio. Un PATCH que no cambia el precio no deja línea. *Garante*: un solo Unit of Work; CHECK `precio_nuevo <> precio_anterior`.

## Dominio: Integridad e inmutabilidad

- **RN-15** — `historial_estado_orden`, `movimiento_stock` e `historial_precio_repuesto` son de **sólo agregado**: nadie puede modificar ni borrar sus filas. *Garante*: disparador en la base, instalado por migración.

## Dominio: Errores (global)

- **RN-18** — Ningún error devuelve al cliente texto interno de la base (entregaría el mapa del esquema, sec. 4.13). **Ninguna entrada inválida termina en un 500.** *Garante*: traducción del `IntegrityError`; validación en el contrato.

## Reglas transversales (requisitos no funcionales del PDF)

| Requisito | Detalle |
|---|---|
| Asincronía | Todos los handlers `async def`; bcrypt siempre fuera del bucle |
| Credenciales | Ninguna contraseña ni clave de firma en el código (ni como default), ni en `alembic.ini`, ni en el repo |
| Token | Sólo en cookie HttpOnly; nunca en el cuerpo ni leído de la cabecera `Authorization` |
| Esquema | Sólo con Alembic; no se usa `create_all` |
| Transacciones | Ningún repositorio confirma; ningún servicio construye su UoW; el UoW no cierra la sesión |
| Carga perezosa | Prohibida: toda relación que se lee se precarga en el repositorio |
| SQL | Nunca armado por concatenación con datos del usuario |
| Errores | Mensajes propios; nunca texto de la base ni traza |
| Unicidad | Garantizada por la base; **no** se verifica con consulta previa |
| Diagnóstico | Consultas visibles en consola (`SQL_ECHO=true` o equivalente) |

## Reglas de contrato (Ejercicio 3)

- Entradas con `extra="forbid"`: nadie se registra con un rol ni edita stock por PATCH.
- Ninguna respuesta incluye `password_hash`.
- PATCH aplica sólo campos enviados (`exclude_unset`).
- Códigos: **201** crear, **204** baja, **404** recurso de la ruta inexistente, **409** choque con lo guardado, **422** contrato incumplido.
- Listados: `{items, total, page, size, pages}`; `page` desde 1; `size` 1–100 (default 20); página más allá de la última → **422**; `total` cuenta con los mismos filtros; con cero resultados hay **una página, vacía**; búsqueda de repuestos con parámetros ligados.
- Todo campo que termina en bcrypt (contraseña de login, registro y la actual del cambio) acepta **máximo 72 bytes** (bytes, no caracteres: "ñ" ocupa 2); si no, 422.
