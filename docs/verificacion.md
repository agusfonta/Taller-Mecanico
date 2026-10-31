# Verificación de la entrega (C-12)

Informe de la verificación de punta a punta del trabajo práctico: qué se probó, cómo, con qué resultado y qué se corrigió.
Fecha de la corrida: 2026-10-30. Ninguna contraseña, cookie ni clave de firma figura en este documento ni en las evidencias.

## 1. Cómo se verificó

Todo se corrió sobre una base **nueva y separada** (`taller_entrega`, en el mismo contenedor de PostgreSQL 16), para no tocar la
base de desarrollo (`taller_db`). Se pisó sólo el nombre de la base con la variable de entorno `POSTGRES_DB` en cada comando;
el resto de la configuración sale del `.env` de siempre.

> Las capturas PNG de C-14 y C-15 (`evidencias/*.png`) se tomaron después, sobre `taller_db` recién sembrada (la base `taller_entrega` ya no existe).

| Paso | Qué se hizo | Resultado |
|---|---|---|
| Base nueva | `docker compose exec postgres createdb -U <usuario> taller_entrega` | Creada |
| Migraciones | `alembic upgrade head` desde vacío, `alembic downgrade base`, `alembic upgrade head` | Los tres comandos terminaron bien; `alembic current` = `6f80b22e25d4 (head)` |
| Seed | `python seed.py` dos veces seguidas | Código 0 las dos veces, mismo resumen de filas (13 tablas), salida sin contraseñas ni URL |
| Servidor real | `uvicorn main:app` sobre `taller_entrega`; `GET /health/live` y `GET /health/ready` | 200 y 200 (`{"estado":"listo"}`) |
| 18 archivos `.http` | Cada uno con `python seed.py` antes, contra el servidor real en `http://localhost:8000`, con el intérprete de `test/integration/http_casos.py` | 18 archivos, 104 pedidos, **0 distintos del `# Esperado`** |
| C-14 con `psql` | `test/solo_agregado.sql` tras el seed | 6 errores del disparador + 1 de clave foránea; conteos finales iguales (3, 4, 1 y 2 filas). Salida en [`evidencias/c14_psql.txt`](evidencias/c14_psql.txt) |
| C-15 con `SQL_ECHO=true` | Servidor con `SQL_ECHO=true`, `test/c15_detalle_consultas.http` | 5 sentencias para la orden de 2 ítems y 5 para la de 4 ítems. Salida en [`evidencias/c15_sql_echo.txt`](evidencias/c15_sql_echo.txt) |
| Instalación desde cero | Entorno virtual temporal, `pip install -r requirements.txt`, `import main` con un entorno mínimo; luego `pip install -r requirements-dev.txt` y `pytest test/unit` | Sin dependencias faltantes (`requirements.txt` alcanza para la app y el seed; `requirements-dev.txt` para los tests) |
| Aviso en consola | `uvicorn main:app`, reponer 2 bujías y terminar la orden 2 | Una línea `INFO app.modules.ordenes.avisos: Aviso a cliente 2: orden 2 terminada` después de la línea de acceso 200; con `SQL_ECHO=false` no sale SQL |
| Suite completa | `pytest --exigir-db` en serie | Ver sección 4 |

Los códigos de estado de los `.http` se comprobaron dos veces: dentro de la suite (`test/integration/test_http_casos.py`, contra la
app en proceso sobre un esquema efímero) y a mano contra el servidor real. Lo que un código no puede mostrar (tiempos de C-04,
`Retry-After` de C-05, columnas de las respuestas) se miró en las respuestas reales: C-03 devolvió `Set-Cookie` con `HttpOnly`,
`Max-Age=1800` y `SameSite=lax` y un cuerpo sin token; C-04 devolvió el mismo cuerpo 401 en ambos casos con tiempos parecidos;
C-05 devolvió 429 con `Retry-After` en segundos y dejó cinco filas con `exito = false` en `intento_acceso`.

## 2. Matriz de trazabilidad

Cada fila: caso, artefacto manual, tests automáticos que lo cubren, resultado observado en la verificación real y estado.
Todos los `.http` además se ejecutan en `test/integration/test_http_casos.py::test_cada_pedido_responde_lo_que_dice_su_esperado`
(un caso de prueba por archivo).

| Caso | Artefacto manual | Tests automáticos | Resultado observado (base `taller_entrega`) | Estado |
|---|---|---|---|---|
| C-01 | `test/c01_parametro_ruta.http` | `test/integration/test_usuarios_revocar.py::test_rol_fuera_del_vocabulario_o_id_no_entero_en_la_ruta_dan_422`; `test/integration/test_entradas_invalidas.py::test_id_fuera_de_rango_bigint_en_la_ruta_da_422_y_no_500` | 6 pedidos con los códigos esperados: ids no enteros y fuera de BIGINT dan 422; un id válido inexistente, 404 | Aprobado |
| C-02 | `test/c02_registro.http` | `test/integration/test_auth_registro.py::test_correo_repetido_409_sin_filas_sueltas`; `test/integration/test_auth_registro.py::test_documento_de_cliente_sin_usuario_409_y_la_ficha_queda_intacta` | 201 y tres 409 (correo, documento y correo con otras mayúsculas), con mensaje propio | Aprobado |
| C-03 | `test/c03_cookie.http` | `test/integration/test_auth_login.py::test_login_correcto_200_con_cuerpo_exacto_y_cookie`; `test/integration/test_auth_yo_cambio.py::test_yo_ignora_authorization_bearer_sin_cookie` | Cookie `HttpOnly`, `SameSite=lax`, `Max-Age=1800`; cuerpo sin token; sin cookie y con `Authorization: Bearer` dan 401 | Aprobado |
| C-04 | `test/c04_anti_enumeracion.http` | `test/integration/test_auth_login.py::test_tres_fallos_distintos_dan_el_mismo_401_sin_cookie`; `test/integration/test_auth_login.py::test_correo_inexistente_verifica_contra_el_hash_ficticio` | Mismo 401 y mismo cuerpo para correo existente y no existente; tiempos del mismo orden | Aprobado |
| C-05 | `test/c05_limite_intentos.http` | `test/integration/test_auth_login.py::test_sexto_intento_429_con_retry_after_sin_verificar_y_cinco_filas` | Cinco 401 y el sexto 429 con `Retry-After` (segundos); cinco filas en `intento_acceso` | Aprobado |
| C-06 | `test/c06_401_403_propio.http` | `test/integration/ordenes/test_detalle_http.py::test_cliente_ajeno_recibe_403_sin_datos_de_la_orden_caso_c06`; `test/integration/seed/test_seed_http_acceso.py::test_cliente_ve_su_orden_y_no_la_ajena_c06` | Sin sesión 401; sin rol 403; orden propia 200; ajena 403 | Aprobado |
| C-07 | `test/c07_revocar_rol.http` | `test/integration/test_usuarios_revocar.py::test_revocar_recepcion_corta_el_permiso_en_la_peticion_siguiente_con_la_misma_cookie`; `test/integration/test_usuarios_roles.py::test_vencimiento_sin_zona_o_pasado_da_422_sin_filas_ni_eventos` | Con dos sesiones: 200, revocación 200, misma cookie 403, `/auth/yo` con `roles_vigentes` vacío y `roles_token` con RECEPCION, fila revocada conservada, dos vencimientos inválidos 422 | Aprobado |
| C-08 | `test/c08_autoproteccion.http` | `test/integration/test_usuarios_revocar.py::test_el_admin_no_puede_revocarse_su_propio_admin_y_sigue_siendo_admin` | Autorrevocarse el ADMIN da 409 y sigue siendo administrador; revocar a otro administrador da 200 | Aprobado |
| C-09 | `test/c09_cambio_obligatorio.http` | `test/integration/test_auth_yo_cambio.py::test_login_y_cambio_inmediatos_invalidan_la_cookie_vieja_y_la_nueva_vale`; `test/integration/seed/test_seed_http_acceso.py::test_usuario_con_cambio_obligatorio_recibe_403_fuera_de_auth_c09` | Bloqueo 403 fuera de `/auth`; tras el cambio la cookie nueva vale y la anterior da 401 | Aprobado |
| C-10 | `test/c10_alta_orden.http` | `test/integration/ordenes/test_alta_http.py::test_alta_con_dos_items_responde_201_con_detalle_completo`; `test/integration/ordenes/test_alta_http.py::test_repuesto_inexistente_o_dado_de_baja_es_409` | 201 (orden 3), precios copiados (25000.00 y 6000.00), total 37000.00 e historial; repuesto inexistente 409 y la orden 4 no existe (404) | Aprobado |
| C-11 | `test/c11_terminar_sin_stock.http` | `test/integration/seed/test_seed_http_c11_c12.py::test_terminar_la_orden_2_sin_stock_da_409_con_la_bujia_y_no_cambia_nada_c11` | 409 que nombra BUJ-001; la orden sigue EN_REPARACION y los stocks (2 y 10) no cambian | Aprobado |
| C-12 | `test/c12_reponer_y_terminar.http` | `test/integration/seed/test_seed_http_c11_c12.py::test_reponer_bujias_y_terminar_la_orden_2_da_200_con_descuentos_c12`; `test/integration/ordenes/test_aviso_http.py::test_un_solo_aviso_con_cliente_y_orden_correctos_tras_el_200` | Reponer 200, terminar 200, stock de bujías en 0, movimientos y línea de historial; el aviso salió una vez en la consola del servidor | Aprobado |
| C-13 | `test/c13_cancelar.http` | `test/integration/ordenes/test_cancelar_http.py::test_el_dueno_cancela_su_pendiente_con_200_y_sin_tocar_el_stock`; `test/integration/ordenes/test_cancelar_http.py::test_cliente_ajeno_recibe_403_y_la_orden_queda_igual` | El dueño cancela (200); la orden ajena 403; terminada y ya cancelada 409 | Aprobado |
| C-14 | `test/solo_agregado.sql` | `test/integration/test_solo_agregado_sql.py::test_las_siete_sentencias_fallan_como_se_espera_y_los_conteos_no_cambian`; `test/integration/test_solo_agregado.py::test_update_es_rechazado_y_la_fila_queda_igual` | `psql`: 6 errores del disparador y 1 de clave foránea; conteos iguales (`evidencias/c14_psql.txt`, `evidencias/c14_psql.png`) | Aprobado |
| C-15 | `test/c15_detalle_consultas.http` | `test/integration/ordenes/test_consultas_detalle.py::test_el_detalle_ejecuta_la_misma_cantidad_de_sentencias_con_2_y_con_4_items` | 5 sentencias con 2 ítems y 5 con 4 ítems (`evidencias/c15_sql_echo.txt`, `evidencias/c15_sql_echo_2items.png`, `evidencias/c15_sql_echo_4items.png`) | Aprobado |
| C-16 | `test/c16_busqueda_paginacion_patch.http` | `test/integration/seed/test_seed_http_catalogo.py::test_busqueda_freno_con_size_1_da_total_1_y_una_pagina_c16` | Búsqueda con inyección: 0 resultados; `q=freno&size=1`: total 1; `page=2` y `size=500`: 422; PATCH parcial 200; PATCH de stock 422 | Aprobado |
| C-17 | `test/c17_estados.http` | `test/integration/ordenes/test_estados_http.py::test_cuatro_estados_por_posicion_con_es_final_para_un_cliente_caso_c17`; `test/integration/seed/test_seed_http_catalogo.py::test_estados_orden_los_cuatro_por_posicion_c17` | Sin sesión 401; los cuatro estados por posición con `es_final` sólo en TERMINADA y CANCELADA; estado inventado 422 | Aprobado |
| C-18 | `test/c18_historial_precios.http` | `test/integration/seed/test_seed_http_catalogo.py::test_historial_de_precios_del_filtro_tiene_una_linea_c18` | Cambiar el precio agrega una línea (8500.00 a 9000.00); cambiar la descripción no; la recepción recibe 403 | Aprobado |
| C-19 | `test/c19_baja_vehiculo.http` | `test/integration/test_vehiculos_http.py::test_c19_baja_libera_la_patente_para_otro_cliente`; `test/integration/test_vehiculos_http.py::test_baja_con_orden_abierta_es_409_y_no_modifica` | Baja 204, re-registro 201, tercer registro 409; baja de un vehículo con órdenes 409 | Aprobado |

## 3. Hallazgos y correcciones

| Hallazgo | Cómo se confirmó | Corrección |
|---|---|---|
| **El aviso al cliente no se veía en la consola** de `uvicorn main:app` (el logger raíz queda en WARNING) | Servidor real: se terminó la orden 2 y no apareció ninguna línea `Aviso a cliente ...` | `app/core/logs.py` agrega un handler propio al logger `app` (INFO), idempotente, sin tocar `sqlalchemy.*` ni `uvicorn.*`; se llama desde `crear_app`. Tests: `test/unit/test_logging_app.py` |
| **Un id de ruta mayor que un BIGINT terminaba en 500** (`DataError` de asyncpg) en las rutas con `{id}` | `GET /ordenes/99999999999999999999` y las otras cuatro rutas pedidas terminaron en excepción/500 en los tests escritos antes de la corrección: los 5 casos explícitos y 45 de las 48 combinaciones del barrido (las 3 restantes eran el 403 de la fila siguiente) | `app/core/tipos.py::IdRuta` (rango BIGINT) usado en los parámetros de ruta de los cinco routers: ahora 422; los ids 0 y negativos siguen dando 404. Tests: `test/unit/test_tipos_id.py` y `test/integration/test_entradas_invalidas.py` |
| El resto del barrido (campo extra, tipo incorrecto, JSON mal formado, ids del cuerpo fuera de rango, paginación inválida) | Los 99 tests de `test_entradas_invalidas.py` sobre los endpoints de la KB 06 | Ya respondían 4xx sin texto de la base: quedan como tests de regresión |
| La KB 11 dice "`Retry-After` en pocos ms" para C-05 | `Retry-After` real: segundos hasta el fin del bloqueo; lo que tarda pocos ms es la respuesta 429 (no calcula bcrypt) | Documentado en el comentario de `c05_limite_intentos.http`; no cambia el código |
| `POST /ordenes/{id}/iniciar` con un id fuera de rango responde 403 a un ADMIN | El control de rol (sólo MECANICO) precede a la validación del id | Comportamiento correcto; el test del barrido usa una sesión de mecánico para esa ruta |

## 4. Suite completa de tests

`pytest --exigir-db` en serie, sin paralelismo, tras los cambios del grupo 1-7: **1949 passed, 1 failed** en 10 min 44 s.
La falla es `test/integration/test_auth_login.py::test_tiempo_de_login_similar_exista_o_no_el_correo`, un test de tiempos
(compara duraciones con una tolerancia relativa) que es sensible a la carga de la máquina; vuelto a correr solo pasó 2 de 3
veces. No toca código de este change. `pytest test/unit`: 958 tests, sin base de datos.

## 5. Pendientes que sólo puede hacer el usuario

- Correr en VS Code (extensión REST Client) al menos `c07_revocar_rol.http` y `c12_reponer_y_terminar.http`, re-sembrando antes de cada uno.
- Decidir si se borra la base `taller_entrega` (`docker compose exec postgres dropdb -U <usuario> taller_entrega`). Por ahora se conserva.

## 6. Auditoría de entrega

| Punto | Resultado |
|---|---|
| Estructura obligatoria (KB 08) | Presentes `main.py`, `seed.py`, `requirements.txt`, `alembic.ini`, `env.example`, `README.md`, `migrations/`, `test/`, `app/core/` y un paquete por módulo (`health`, `usuarios`, `clientes`, `repuestos`, `ordenes`); `test/` tiene los 18 `.http` y `solo_agregado.sql` (`test/unit/test_estructura.py`, `test/unit/test_entrega.py`) |
| `env.example` | Tiene las 13 variables de `Settings`, ni una más ni una menos; `JWT_SECRET_KEY` y `POSTGRES_PASSWORD` sin valor |
| `alembic.ini` | Sin credenciales ni URL de conexión |
| `.gitignore` | Cubre `.env`, `.venv/`, `__pycache__/`, `.pytest_cache/`, `.atl/`, `.claude/`; `git status --short --ignored` lista `.env` como ignorado |
| Contraseñas del seed | Sólo en `seed.py`; `test/unit/test_seed_secretos.py` recorre el repositorio (README, `.http`, SQL y evidencias incluidos) y no encuentra ninguna |
| `CLAUDE.md` y `AGENTS.md` | Idénticos entre sí y sin deriva respecto del código entregado: no se editaron |
| `TP_Cap1a6_Consigna.pdf` en la raíz | Es copia idéntica de `docs/TP_Cap1a6_Consigna.pdf`; no se tocó (decisión pendiente: quitarla de la raíz antes del primer commit) |
| Repositorio git | Sin commits todavía; no se hizo ninguno |
