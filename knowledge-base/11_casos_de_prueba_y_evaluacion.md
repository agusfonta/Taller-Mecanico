# Casos de Prueba y Evaluación

El proyecto incluye archivos `.http` en `test/` que demuestran estos casos, **cada uno con la respuesta esperada en un comentario**, y `test/solo_agregado.sql` para C-14. Antes de cada archivo se corre `python seed.py`.

> Varias sesiones a la vez (REST Client): nombrar cada login con `# @name loginAdmin` y usar `# @no-cookie-jar` + `Cookie: {{loginAdmin.response.headers.Set-Cookie}}` en los pedidos de esa sesión. Necesario para C-07.

| Caso | Qué se demuestra | Resultado esperado | Reglas |
|---|---|---|---|
| C-01 | Parámetro de ruta no entero, con sesión | 422, sin ejecutar el handler | RN-18 |
| C-02 | Registro; correo y documento repetidos | 201; 409 con mensaje propio; el rechazado no deja fila suelta | RN-01, RN-02 |
| C-03 | Cookie del login | `Set-Cookie` con HttpOnly, SameSite=Lax, Max-Age; cuerpo sin token; sin cookie o con `Authorization: Bearer` → 401 | — |
| C-04 | Correo existente con clave mala vs. inexistente | 401 con el mismo cuerpo y tiempo parecido | RN-09 |
| C-05 | Seis intentos fallidos seguidos | El 6.º, 429 con `Retry-After` en pocos ms; los 5 fallos están en `intento_acceso` | RN-08 |
| C-06 | 401 vs. 403, y lo propio | Sin rol → 403; el cliente ve su orden (200) y no la ajena (403) | RN-04, RN-17 |
| C-07 | Revocar un rol con sesión abierta; vencimientos inválidos | Misma cookie → 403 en la petición siguiente; `/auth/yo` muestra la diferencia; la fila revocada sigue; vencimiento pasado o sin zona → 422 | RN-04 |
| C-08 | Autoprotección | El admin no se revoca su ADMIN: 409 | RN-05 |
| C-09 | Cambio obligatorio | Bloqueado (403) salvo `/auth`; tras el cambio, cookie nueva vale y la anterior da 401, sin esperar entre login y cambio | RN-06, RN-07 |
| C-10 | Alta de orden con dos ítems | 201 con precios copiados, total e historial; repuesto inexistente → 409 y la orden no queda | RN-10 |
| C-11 | Terminar la orden 2 (pide más bujías de las que hay) | 409; estado, stock, movimientos e historial intactos | RN-13 |
| C-12 | Reponer y terminar la orden 2 | 200; baja el stock, aparecen movimientos y línea de historial; el aviso sale en el log **después** de la respuesta | RN-13, RN-14 |
| C-13 | Cancelar | Dueño cancela su pendiente (200); ajena 403; terminada 409 | RN-12 |
| C-14 | UPDATE/DELETE sobre las 3 tablas de sólo agregado en `psql`; orden con estado fuera del catálogo | Los seis, rechazados por el disparador; el último, por la FK | RN-15, RN-19 |
| C-15 | Detalle de orden con 2 y con 4 ítems | **La misma cantidad de consultas** en consola | Ej. 8 |
| C-16 | Búsqueda `' OR '1'='1`; paginación con filtro; PATCH parcial; PATCH del stock | Lista vacía, `total` 0; `q=freno&size=1` → total 1, pages 1; `page=2` → 422; `size=500` → 422; sólo cambia lo enviado; PATCH de stock → 422 | RN-14, Ej. 3 |
| C-17 | Catálogo de estados; filtrar órdenes por estado no declarado | Los cuatro por posición, TERMINADA y CANCELADA finales; sin sesión 401; estado inválido 422 | RN-19 |
| C-18 | Cambiar precio y luego sólo la descripción | Una línea nueva en `/repuestos/{id}/precios` (anterior y nuevo); el 2.º PATCH no agrega; la recepción recibe 403 | RN-20 |
| C-19 | Baja de vehículo sin órdenes y re-registro con la misma patente | 204 y 201; segunda patente vigente igual → 409 | RN-01, RN-16 |

## Puntaje por ejercicio

| Ejercicio | Tema | Puntos |
|---|---|---|
| 1 | Proyecto, configuración y ciclo de vida | 8 |
| 2 | Modelos, relaciones y migraciones | 14 |
| 3 | Contratos y CRUD | 10 |
| 4 | Autenticación | 16 |
| 5 | Autorización | 14 |
| 6 | Repositorios y Unit of Work | 20 |
| 7 | Integridad: sólo agregado e intento de acceso | 10 |
| 8 | Lecturas sin N+1 y asincronía | 8 |
| | **Total** | **100** |

## Qué mira cada criterio

- **Ej. 1**: estructura, `Settings` sin secretos por defecto, motor y fábrica en el lifespan, `get_session`, salud.
- **Ej. 2**: restricciones, índices únicos parciales, catálogo con FK, navegación, dos migraciones (una a mano), upgrade/downgrade.
- **Ej. 3**: contratos separados, `extra="forbid"`, códigos, nada en 500, PATCH parcial, envoltorio y paginación.
- **Ej. 4**: bcrypt fuera del bucle y con semáforo, orden del login, límite, hash ficticio, cookie HttpOnly.
- **Ej. 5**: 401 vs. 403, roles vigentes en base, autoprotección, dos grupos de rutas, `iat`, lo propio.
- **Ej. 6**: dos jerarquías, clase del modelo, `flush` y no `commit`, precarga en repositorio, quién crea/abre/confirma/cierra, operaciones multi-escritura.
- **Ej. 7**: disparador en las tres tablas; historial de precios en la misma transacción; intento de acceso en su propia sesión.
- **Ej. 8**: consultas fijas en el detalle; ninguna llamada bloqueante; aviso en segundo plano.

## Evidencias de entrega

- **C-15**: captura o fragmento de consola con las consultas del detalle de una orden de 2 ítems y de otra de 4.
- **C-14**: captura de `psql` con los seis rechazos del disparador y el de la clave foránea.
