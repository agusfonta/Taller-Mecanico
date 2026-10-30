# Tasks — C-05 `auth-registro-login-sesion`

> ⚠️ Governance **CRITICO**: NO empezar sin la aprobación humana explícita de `design.md` (D2, D3, D5, D7, D8, D9 y supuestos SU-C05-1..8).
> Strict TDD: en cada tarea de comportamiento, primero el test en ROJO (ejecutado y fallando), luego el mínimo código en VERDE, luego TRIANGULAR (≥ 2 casos por comportamiento) y REFACTOR con la suite en verde tras cada paso.
> Skills a cargar: `auth-implementation-patterns`, `fastapi`, `async-python-patterns`, `python-configuration`, `python-testing-patterns`, `sqlalchemy-alembic-expert-best-practices-code-review`. Referencias: `design.md` (D1..D12), `specs/*/spec.md`.
> Reglas: bcrypt sólo por `ServicioContrasenas` (`to_thread` + semáforo) y antes de abrir transacción; repositorios sólo `flush()`; el router construye el UoW y el servicio lo abre; sin carga perezosa; `extra="forbid"` en toda entrada; sin secretos ni defaults de secretos; integración contra PostgreSQL real. Nunca leer ni imprimir el `.env`; credenciales sólo vía `Settings`. Sin build, commit ni push. No crear migraciones.

## 1. Safety net

- [x] 1.1 Ejecutar `pytest --exigir-db` con PostgreSQL levantado y registrar la línea base de C-04 ("N passed, 0 skipped"); si algo falla, DETENER y reportar como falla preexistente (no corregir).

## 2. Contraseñas: política, servicio bcrypt y hash ficticio (`app/core/security.py`, spec `contrasenas`)

- [x] 2.1 RED: `test/unit/test_security.py` — `PasswordNueva`/`PasswordIngresada` en un modelo de prueba: 7 caracteres → error (sólo `PasswordNueva`); 36 "ñ" (72 bytes) aceptado; 37 "ñ" (74 bytes) rechazado; `"\x00"` rechazado; vacío rechazado; ejecutar y confirmar que FALLA (módulo inexistente).
- [x] 2.2 GREEN: crear `app/core/security.py` con los tipos anotados y el validador de 72 bytes / nulo (D1); confirmar VERDE.
- [x] 2.3 RED → GREEN: `ServicioContrasenas(rondas=4, max_concurrencia=2)`: `hashear` produce un hash que declara costo `$2b$04$`, `verificar` True con la correcta y False con otra; `verificar` con hash corrupto → False sin excepción; `crear_servicio_contrasenas(settings)` toma `BCRYPT_ROUNDS`/`BCRYPT_MAX_CONCURRENCY`; confirmar VERDE.
- [x] 2.4 TRIANGULAR concurrencia: monkeypatch de `bcrypt.checkpw` con una función que registra entradas/salidas concurrentes y duerme 50 ms; 6 verificaciones con `asyncio.gather` y tope 2 → máximo simultáneo observado == 2 y todas terminan; y durante una verificación lenta, otra corrutina avanza (no bloquea el bucle); confirmar VERDE.
- [x] 2.5 RED → GREEN lifespan: ampliar `test/unit/test_lifespan.py`: dentro de `main.lifespan(app)` existen `app.state.contrasenas` y `app.state.hash_ficticio` con costo `BCRYPT_ROUNDS` (fijar 4 en el entorno); dos arranques → hashes distintos; implementar en `main.py` (D4) con `secrets.token_urlsafe(32)`; confirmar VERDE y que `test_main.py` (import sin base) sigue VERDE.
- [x] 2.6 REFACTOR: `__all__`, docstrings (por qué semáforo por instancia, por qué 72 bytes y nulo); `pytest test/unit` VERDE.

## 3. Token y cookie (`app/core/security.py`, spec `token-sesion`)

- [x] 3.1 RED: en `test_security.py`, `emitir_token(7, ["CLIENTE"], settings, ahora=1700000000.123456)` → decodificado con PyJWT: `sub == "7"`, `iat == 1700000000.123456` (flotante, sin truncar), `exp == iat + 1800`, `roles == ["CLIENTE"]`; `decodificar_token` devuelve claims con `sub` int; ejecutar y confirmar que FALLA.
- [x] 3.2 GREEN: `emitir_token`/`decodificar_token`/`ClaimsToken`/`TokenInvalidoError` (D2: HS256 fijo, `require` sub/iat/exp, leeway 0); confirmar VERDE.
- [x] 3.3 TRIANGULAR rechazos (parametrizado): otra clave, `alg=none`, HS512, vencido (`ahora` en el pasado), sin `sub`, `sub` no numérico, basura → `TokenInvalidoError`; confirmar VERDE.
- [x] 3.4 RED → GREEN cookie: con una `Response` de Starlette, `poner_cookie_sesion` produce `Set-Cookie` con `access_token=`, `HttpOnly`, `SameSite=lax`, `Path=/`, `Max-Age=1800` y SIN `Secure` (`COOKIE_SECURE=false`), y CON `Secure` (`true`); `borrar_cookie_sesion` produce `Max-Age=0` con los mismos `Path`/`HttpOnly`/`SameSite`; confirmar VERDE.
- [x] 3.5 REFACTOR; `pytest test/unit/test_security.py` VERDE.

## 4. Infraestructura de integración HTTP (`test/integration/conftest.py`)

- [x] 4.1 Agregar fixtures (D12): `esquema_auth` (scope sesión, `c05_auth_<hex>` migrado a `head` con `aplicar_migraciones`, borrado al final), `settings_auth` (`settings_db.model_copy(update={"bcrypt_rounds": 4})`), `motor_auth` (`search_path`), limpieza `TRUNCATE` de las 13 tablas `RESTART IDENTITY CASCADE` tras cada test, y ayudantes de siembra (`crear_usuario(email, password, roles, activo, debe_cambiar_password)`, `insertar_intento(email, ip, exito, cuando)`) y de conteo de filas; verificar con un test humo `test_auth_infra.py` que el esquema tiene las 13 tablas vacías y que la limpieza deja `intento_acceso` vacío entre dos tests; confirmar VERDE con `--exigir-db`.

## 5. Repositorios y UoW del módulo `usuarios` (+ `ClienteRepository`)

- [x] 5.1 RED: `test/integration/test_repositorios_usuarios.py` sobre `motor_auth`: `UsuarioRepository.get_by_email` encuentra por correo exacto y devuelve None si no existe; `AsignacionRolRepository.roles_vigentes(usuario_id, ahora)` devuelve sólo roles no revocados y no vencidos (casos: abierta sin vencimiento, vencida, revocada, con vencimiento futuro); ejecutar y confirmar que FALLA.
- [x] 5.2 GREEN: `app/modules/usuarios/repository.py` (`UsuarioRepository`, `AsignacionRolRepository`, `IntentoAccesoRepository`, `EventoSeguridadRepository`, todos sobre `BaseRepository` con parámetros ligados), `app/modules/clientes/repository.py` (`ClienteRepository` mínimo) y `app/modules/usuarios/unit_of_work.py` (`UsuariosUoW` con los cinco repos sobre la misma sesión); confirmar VERDE.
- [x] 5.3 TRIANGULAR `fallos_bloqueantes` (D7): 5 fallos recientes → 5 filas ordenadas desc; 5 fallos de hace > 60 s → 0; 4 fallos + éxito + 4 fallos → 4; fallos de otra IP u otro correo no cuentan; confirmar VERDE.
- [x] 5.4 REFACTOR: ningún repositorio llama `commit()` (test estático estilo `test_repository_estatico.py` sobre los archivos nuevos); confirmar VERDE.

## 6. Usuario actual y autorización (`app/core/dependencies.py`, specs `sesion-usuario`, `autorizacion`, `grupos-de-rutas`)

- [x] 6.1 RED: `test/unit/test_dependencies.py` con `crear_app(protegidos=[router con ruta contadora])` SIN lifespan: sin cookie → 401 `{"detail": "Se requiere iniciar sesión"}` y la ruta no corre (sin `app.state.session_factory`, prueba el orden de D5); cookie con token inválido → 401 sin tocar la base; `Authorization: Bearer <token válido>` sin cookie → 401; ejecutar y confirmar que FALLA donde corresponda.
- [x] 6.2 GREEN: `leer_claims`, `get_usuario_actual` (D5, `UsuarioActual` inmutable, bloque de lectura con `UsuariosUoW`, comparación `iat` vs `password_cambiada_en` en microsegundos), `exigir_acceso` (403 cambio pendiente) y `requiere_rol(*roles)` (D6); `get_usuarios_uow` en `app/modules/usuarios/router.py`; confirmar VERDE y que `test_grupos_rutas.py` sigue VERDE sin cambios.
- [x] 6.3 TRIANGULAR unitario: con `dependency_overrides[get_usuario_actual]` → usuario sin cambio pendiente y con ADMIN: ruta `requiere_rol(Rol.ADMIN)` corre; con sólo CLIENTE → 403 "No tiene permiso para esta operación"; con cambio pendiente y ADMIN → 403 "Debe cambiar la contraseña antes de continuar" (antes que el rol); `requiere_rol()` sin roles o con un texto no `Rol` → error al declararse; confirmar VERDE.
- [x] 6.4 RED → GREEN integración `test/integration/test_auth_sesion.py` (token emitido a mano con `emitir_token` + usuario sembrado): `sub` inexistente → 401; usuario inactivo → 401; `password_cambiada_en` posterior al `iat` por 1 ms (mismo segundo) → 401; igual o anterior → 200 en la ruta protegida de prueba; rol revocado o vencido en la base con el token aún diciendo ADMIN → 403; ruta con `requiere_rol` resuelve el usuario con una sola consulta a `usuario` por petición (contar con un evento `before_cursor_execute`); confirmar VERDE.
- [x] 6.5 REFACTOR: alias `UsuarioActualDep`, `__all__`, docstring del módulo (reemplaza el gancho de C-02, orden de dependencias); `pytest` VERDE.

## 7. Registro (`POST /auth/registro`, spec `registro-clientes`)

- [x] 7.1 RED: `test/unit/test_schemas_auth.py` — `RegistroEntrada`: campo `rol` → error; `Ana@Example.COM ` → `ana@example.com`; `documento` "   " → error; correo inválido → error; ejecutar y confirmar que FALLA.
- [x] 7.2 GREEN: `app/modules/usuarios/schemas.py` (`EmailNormalizado`, `RegistroEntrada`, `RegistroRespuesta`, `extra="forbid"`); confirmar VERDE.
- [x] 7.3 RED: `test/integration/test_auth_registro.py` — registro válido → 201 con `{id, email, nombre, cliente_id, roles: ["CLIENTE"]}`, sin `Set-Cookie`, sin `password_hash` ni la contraseña en el cuerpo; en la base: usuario activo con hash bcrypt, asignación CLIENTE abierta con `otorgada_por` nulo, cliente vinculado y una línea de `evento_seguridad` (actor = correo, acción "Registro de cliente"); ejecutar y confirmar que FALLA.
- [x] 7.4 GREEN: `errores.restriccion_violada` (`app/core/errores.py`), `registrar_cliente` en `service.py` (D8: hash antes del bloque, un único `async with uow`), `router_auth` con `POST /auth/registro` y registro de `router_auth` en el grupo abierto de `main.py`; confirmar VERDE.
- [x] 7.5 TRIANGULAR conflictos: correo repetido (también con otra capitalización) → 409 "El correo ya está registrado"; documento de un cliente sin usuario sembrado por SQL → 409 "El documento ya pertenece a un cliente del taller", la ficha sigue con `usuario_id` nulo; en ambos casos los conteos de `usuario`, `asignacion_rol`, `cliente` y `evento_seguridad` no cambian y el cuerpo no contiene `IntegrityError`, `duplicate key`, `uq_` ni nombres de tablas; campo `rol` → 422 sin filas; 7 caracteres → 422; 37 "ñ" → 422; espía de `hashear`: en 422 no se llamó; confirmar VERDE.
- [x] 7.6 TRIANGULAR atomicidad: forzar un fallo después de insertar el usuario (monkeypatch de `ClienteRepository.add` que lanza) → la petición no deja filas en ninguna tabla; confirmar VERDE.
- [x] 7.7 REFACTOR; `pytest -m integration --exigir-db` VERDE.

## 8. Login y logout (spec `inicio-sesion`)

- [x] 8.1 RED: `test/integration/test_auth_login.py` — login correcto → 200 con cuerpo exacto `{"mensaje": "Sesión iniciada", "debe_cambiar_password": false, "expira_en_segundos": 1800}`, `Set-Cookie` con los atributos de D3 y sin token en el cuerpo; `GET /auth/yo` con esa cookie → 200; usuario con cambio pendiente → 200 con `debe_cambiar_password: true`; correo en mayúsculas → 200; una fila `exito=true` confirmada en `intento_acceso`; ejecutar y confirmar que FALLA.
- [x] 8.2 GREEN: `LoginEntrada`/`LoginRespuesta`, `get_registro_intentos` (sesión y transacción propias, comentario con su costo), `iniciar_sesion` (D7 pasos 1–4) y `POST /auth/login`; confirmar VERDE.
- [x] 8.3 TRIANGULAR anti-enumeración: clave mala con correo existente, correo inexistente y usuario inactivo → 401 con cuerpos idénticos, sin `Set-Cookie`; espía de `verificar`: exactamente 1 llamada por intento y, con correo inexistente, contra `app.state.hash_ficticio`; espía de `hashear`: 0 llamadas; las tres filas `exito=false` confirmadas; confirmar VERDE.
- [x] 8.4 TRIANGULAR límite (con `service.ahora` controlado): 6 fallos seguidos → 5×401 y el 6.º 429 con `Retry-After` entero en [1, 60], 0 llamadas a `verificar` en el 6.º, exactamente 5 filas de fallo; mismo correo desde otra IP (`ASGITransport(client=...)`) y otro correo desde la misma IP → 401 normal; con 5 fallos insertados hace 61 s → se verifica; 4 fallos + login OK + 4 fallos → ningún 429 y 8 fallos en la tabla; `Retry-After` = segundos hasta que el 5.º fallo más reciente sale de la ventana; confirmar VERDE.
- [x] 8.5 TRIANGULAR contrato: campo extra, correo inválido, contraseña vacía o de 74 bytes → 422 y ninguna fila nueva en `intento_acceso`; confirmar VERDE.
- [x] 8.6 TRIANGULAR tiempo parecido (RN-09): con `bcrypt_rounds=10` sólo en este test, 5 logins fallidos con correo existente y 5 con inexistente → la diferencia de medianas es menor que la mitad de la mediana de una verificación medida aparte; confirmar VERDE.
- [x] 8.7 RED → GREEN logout: `POST /auth/logout` con sesión → 200 `{"mensaje": "Sesión cerrada"}` y `Set-Cookie` que borra `access_token` (`Max-Age=0`, `Path=/`); luego `GET /auth/yo` sin cookie → 401; sin cookie dos veces y con cookie basura → 200 con el mismo cuerpo; confirmar VERDE.
- [x] 8.8 TRIANGULAR concurrencia del bucle: durante un login en curso, `GET /health/live` concurrente responde antes de que termine el login (con `verificar` ralentizado por monkeypatch); confirmar VERDE.
- [x] 8.9 REFACTOR: constantes `MAX_FALLOS`/`VENTANA`, traducción de errores centralizada en el router; `pytest --exigir-db` VERDE.

## 9. Yo y cambio de contraseña (spec `sesion-usuario`)

- [x] 9.1 RED: `test/integration/test_auth_yo_cambio.py` — `GET /auth/yo` → 200 con `{id, email, nombre, debe_cambiar_password, roles_vigentes, roles_token}` sin hash; tras revocar en la base (UPDATE `revocada_en`) un rol del usuario, `roles_vigentes` ya no lo tiene y `roles_token` sí; rol vencido no figura; con cambio pendiente → 200; ejecutar y confirmar que FALLA.
- [x] 9.2 GREEN: `YoRespuesta` y `GET /auth/yo` (grupo abierto, `UsuarioActualDep`); confirmar VERDE.
- [x] 9.3 RED: cambio exitoso → 200 `{"mensaje": "Contraseña actualizada"}` con `Set-Cookie` nuevo; login con la vieja → 401 y con la nueva → 200; `password_cambiada_en` no nulo, `debe_cambiar_password` falso, una línea de `evento_seguridad` "Cambio de contraseña"; ejecutar y confirmar que FALLA.
- [x] 9.4 GREEN: `CambioPasswordEntrada` (`password_actual: PasswordIngresada`, `password_nueva: PasswordNueva`), `cambiar_password` (D9: lectura → verificar + hashear fuera de transacción → escritura en un bloque → token después del commit) y `POST /auth/cambiar-password`; confirmar VERDE.
- [x] 9.5 TRIANGULAR RN-07 (C-09): login y cambio inmediato SIN `sleep` → cookie vieja 401 en `/auth/yo`, cookie nueva 200; dos sesiones abiertas, cambio desde una → la otra 401; contraseña actual incorrecta → 401 "La contraseña actual no es correcta" sin cambios en hash, `password_cambiada_en` ni eventos; sin cookie → 401; nueva de 7 caracteres o 74 bytes, o campo extra → 422; confirmar VERDE.
- [x] 9.6 TRIANGULAR bloqueo/desbloqueo (C-09, spec `autorizacion`): usuario con cambio pendiente y ADMIN → ruta protegida de prueba 403 cambio pendiente; `/auth/yo`, `/auth/cambiar-password` y `/health/live` no responden 403; tras el cambio, con la cookie nueva, la ruta `requiere_rol(ADMIN)` corre; confirmar VERDE.
- [x] 9.7 REFACTOR; `pytest --exigir-db` VERDE.

## 10. Verificación integral

- [x] 10.1 Con PostgreSQL levantado: `pytest --exigir-db` completo → todo VERDE y 0 skipped (incluida la línea base de 1.1); con el contenedor detenido: `pytest -m "not integration"` VERDE.
- [x] 10.2 Revisión estática contra reglas duras: `grep` sin `commit(` en `app/modules/**/repository.py`, sin `bcrypt.` fuera de `app/core/security.py`, sin `Authorization` leído en `app/`, sin `password_hash` en `schemas.py` de respuesta, sin secretos ni contraseñas literales en `app/` y `main.py`, todas las entradas con `extra="forbid"`; documentar el resultado en el resumen del apply.
- [x] 10.3 Manual con `.env` válido y `BCRYPT_ROUNDS=12`: `fastapi dev main.py`; en `/docs` aparecen las 5 rutas `/auth/*`; registro → 201; login → 200 con cookie HttpOnly visible en DevTools y sin token en el cuerpo; 6 logins fallidos → 429 con `Retry-After` en pocos ms; `/auth/yo` con la cookie → 200; logout → cookie borrada.
