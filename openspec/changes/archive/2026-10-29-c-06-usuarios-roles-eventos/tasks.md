# Tasks — C-06 `usuarios-roles-eventos`

> ⚠️ Governance **CRITICO**: NO empezar sin la aprobación humana explícita de `design.md` (D2–D7 y supuestos SU-C06-1..10).
> Strict TDD: en cada tarea de comportamiento, primero el test en ROJO (ejecutado y fallando), luego el mínimo código en VERDE, luego TRIANGULAR (≥ 2 casos por comportamiento) y REFACTOR con la suite en verde tras cada paso.
> Skills a cargar: `auth-implementation-patterns`, `fastapi`, `async-python-patterns`, `python-testing-patterns`, `sqlalchemy-alembic-expert-best-practices-code-review`. Referencias: `design.md` (D1..D12), `specs/*/spec.md`.
> Reglas: reutilizar lo de C-05 (`requiere_rol`, `UsuarioActualDep`, `PasswordNueva`, `EmailNormalizado`, `ServicioContrasenas`, `restriccion_violada`, `UsuariosUoW`, paginación) sin duplicarlo; bcrypt sólo por `ServicioContrasenas` y antes de abrir la transacción; repositorios sólo `flush()`; el router construye el UoW y el servicio lo abre; sin carga perezosa; `extra="forbid"` en toda entrada; SQL con parámetros ligados; integración contra PostgreSQL real; contraseñas de prueba generadas con `secrets` (nunca literales). Nunca leer ni imprimir el `.env`. Sin build, commit ni push. No crear migraciones. **No tocar `app/core/*`**; en `main.py` y `test/integration/conftest.py` sólo AGREGAR routers a las listas (D11: C-07/C-08 tocan los mismos archivos).

## 1. Safety net

- [x] 1.1 Ejecutar `pytest --exigir-db` con PostgreSQL levantado y registrar la línea base tras C-05 ("N passed, 0 skipped"); si algo falla, DETENER y reportar como falla preexistente (no corregir). Verificación: línea base anotada en el resumen del apply.

## 2. Contratos (`app/modules/usuarios/schemas.py`, specs `alta-personal`, `roles-usuario`)

- [x] 2.1 RED: `test/unit/test_schemas_usuarios.py` — `AltaPersonalEntrada`: sin `rol` → error; `rol` `CLIENTE` y `JEFE` → error; `ADMIN`/`RECEPCION`/`MECANICO` OK; campo extra `debe_cambiar_password` → error; `Nuevo@Taller.COM ` → `nuevo@taller.com`; contraseña de 7 caracteres y de 37 "ñ" (74 bytes) → error; `nombre` sólo espacios → error. Ejecutar y confirmar que FALLA (clase inexistente).
- [x] 2.2 GREEN: `AltaPersonalEntrada` (con `RolPersonal`) y `UsuarioCreadoRespuesta` (D2), reutilizando `_Entrada`, `EmailNormalizado`, `TextoNoVacio`, `PasswordNueva`; confirmar VERDE.
- [x] 2.3 RED → GREEN: `AsignarRolEntrada` (D3): sin `vence_en` OK; `vence_en` ingenuo (`2030-01-01T10:00:00`) → error; pasado con zona → error; futuro con `-03:00` OK y conserva el instante; `rol` inválido → error; campo extra → error. Agregar `AsignacionRespuesta`, `RolesUsuarioRespuesta`, `EventoRespuesta`; confirmar VERDE con `pytest test/unit/test_schemas_usuarios.py`.
- [x] 2.4 REFACTOR: `__all__` y docstring del módulo (por qué el vencimiento se valida en el contrato: 422 y no 409); `pytest test/unit` VERDE.

## 3. Repositorios (`app/modules/usuarios/repository.py`)

- [x] 3.1 RED: ampliar `test/integration/test_repositorios_usuarios.py` (sobre `motor_auth`): `AsignacionRolRepository.abierta(usuario_id, rol)` devuelve la fila no revocada (vigente o vencida) y `None` si sólo hay revocadas; `historial(usuario_id)` devuelve todas las filas ordenadas por `desde`, `id`; `EventoSeguridadRepository.listar_recientes(offset, limit)` ordena por `cuando DESC, id DESC` (dos eventos con el mismo `cuando` → mayor id primero). Ejecutar y confirmar que FALLA.
- [x] 3.2 GREEN: implementar `abierta`, `historial` y `listar_recientes` con `select` ligado, sin relaciones; confirmar VERDE.
- [x] 3.3 RED → GREEN: `bloquear_admins_vigentes(ahora)` (D5): devuelve los `usuario_id` de ADMIN no revocados, no vencidos y de usuarios activos (casos: vigente, vencido, revocado, usuario inactivo, otro rol); y, con dos conexiones de `motor_auth`, una segunda transacción que llama al método queda esperando hasta que la primera confirma la revocación de una de las filas, y luego no la ve (`asyncio.wait_for` con tiempo acotado para detectar la espera). Confirmar VERDE.
- [x] 3.4 REFACTOR: el test estático existente (ningún repositorio llama `commit()`) sigue cubriendo el archivo; docstrings (por qué `FOR UPDATE OF` y `ORDER BY id`); confirmar VERDE.

## 4. Infraestructura de tests y registro de routers (archivos compartidos, D11)

- [x] 4.1 Crear `test/integration/sesiones.py` con ayudantes reutilizables (sin fixtures): `clave()` aleatoria con `secrets`, `entrar(http, email, password)` (login real y aserción 200) y `admin_con_sesion(db_auth, fabrica_http, email)` (siembra ADMIN, devuelve `(id, cliente_http)`); verificación: un test humo que obtiene un cliente con sesión ADMIN y llama `GET /auth/yo` → 200 con `ADMIN` vigente.
- [x] 4.2 RED: `test/integration/test_usuarios_permisos.py` — sin cookie `POST /usuarios`, `GET /usuarios/1/roles`, `POST /usuarios/1/roles`, `DELETE /usuarios/1/roles/MECANICO`, `GET /eventos` → 401; con sesión CLIENTE / RECEPCION / MECANICO → 403 "No tiene permiso para esta operación"; ADMIN con cambio pendiente → 403 de cambio pendiente; no-ADMIN con cuerpo inválido → 403 (no 422) y 0 llamadas a `hashear` (espía). Ejecutar y confirmar que FALLA (404 de rutas inexistentes).
- [x] 4.3 GREEN: en `app/modules/usuarios/router.py` crear `router_usuarios` y `router_eventos` con `dependencies=[Depends(requiere_rol(Rol.ADMIN))]` (D1) y handlers mínimos; en `main.py` AGREGAR ambos a `protegidos` de `crear_app` (sin reordenar lo existente); en `app_auth` de `test/integration/conftest.py` AGREGAR ambos a la lista `protegidos` (import local en la fixture). Confirmar VERDE de 4.2 y que `test/unit/test_main.py`, `test_grupos_rutas.py` y toda la suite de C-05 siguen VERDES.

## 5. Alta de personal (`POST /usuarios`, spec `alta-personal`)

- [x] 5.1 RED: `test/integration/test_usuarios_alta.py` — alta válida de MECANICO con correo en mayúsculas → 201 con cuerpo exacto `{id, email (minúsculas), nombre, debe_cambiar_password: true, roles: ["MECANICO"]}`, sin `Set-Cookie`, sin `password`/`password_hash`; en la base: usuario activo con `debe_cambiar_password` verdadero y hash bcrypt, asignación MECANICO abierta sin vencimiento con `otorgada_por` = id del admin, y una línea de `evento_seguridad` con actor = correo del admin y acción `Alta de personal: nuevo@taller.com con rol MECANICO`. Ejecutar y confirmar que FALLA.
- [x] 5.2 GREEN: `dar_alta_personal` y `_abrir_asignacion` en `service.py` (D2/D3: hash antes del bloque, un único `async with uow`, evento D6) y handler `POST /usuarios` con `UsuarioActualDep` + `ContrasenasDep` + `UsuariosUoWDep`; confirmar VERDE.
- [x] 5.3 TRIANGULAR: el creado inicia sesión con la provisoria → 200 con `debe_cambiar_password: true` y la ruta protegida de prueba → 403 de cambio pendiente; alta de `RECEPCION` y de `ADMIN` OK (el nuevo ADMIN, tras cambiar la contraseña, puede dar de alta); confirmar VERDE.
- [x] 5.4 TRIANGULAR conflictos y contrato: correo existente con otra capitalización → 409 "El correo ya está registrado", conteos de `usuario`/`asignacion_rol`/`evento_seguridad` sin cambios, el usuario existente intacto y el cuerpo sin `IntegrityError`/`duplicate key`/`uq_`/nombres de tabla; sin `rol`, `rol` CLIENTE, campo extra, contraseña de 7 caracteres o 74 bytes → 422 sin filas y 0 llamadas a `hashear`; confirmar VERDE.
- [x] 5.5 TRIANGULAR atomicidad: monkeypatch de `EventoSeguridadRepository.add` (o de `AsignacionRolRepository.add`) que lanza tras insertar el usuario → la petición falla y no queda ninguna fila nueva en las tres tablas; confirmar VERDE.
- [x] 5.6 REFACTOR: traducción de `ConflictoError`/`NoEncontradoError` centralizada en el router (D9); `pytest --exigir-db` VERDE.

## 6. Consulta y asignación de roles (`GET`/`POST /usuarios/{id}/roles`, spec `roles-usuario`)

- [x] 6.1 RED: `test/integration/test_usuarios_roles.py` — `GET` de un usuario con MECANICO vigente, RECEPCION revocada y ADMIN vencida (sembradas con `db_auth.asignar_rol`) → 200 con `roles_vigentes == ["MECANICO"]` y las tres asignaciones con su `vigente`; id inexistente → 404 "Usuario no encontrado"; `/usuarios/abc/roles` → 422. Ejecutar y confirmar que FALLA.
- [x] 6.2 GREEN: `roles_de_usuario` (servicio, un bloque, mismo `ahora()` para `vigente` y `roles_vigentes`), `UsuarioNoEncontradoError` y handler `GET` (D8); confirmar VERDE.
- [x] 6.3 RED: `POST` RECEPCION sin vencimiento → 201 con `otorgada_por` = id del admin, `vence_en` nulo, `vigente` verdadero, y evento `Asignación de rol RECEPCION a {email}`; `POST` MECANICO con `vence_en` futuro con zona `-03:00` → 201, el usuario lo tiene vigente (`GET /auth/yo` con su sesión) y el evento incluye `hasta` con el instante en UTC. Ejecutar y confirmar que FALLA.
- [x] 6.4 GREEN: `asignar_rol` (D3, reutiliza `_abrir_asignacion`) y handler `POST`; confirmar VERDE.
- [x] 6.5 TRIANGULAR (C-07 vencimientos, RN-03): `vence_en` sin zona → 422 y pasado con zona → 422, ambos sin filas ni eventos; rol abierto y vigente → 409 "El usuario ya tiene ese rol asignado" sin filas nuevas ni evento; usuario inexistente con cuerpo válido → 404; reasignación de un MECANICO abierto y vencido → 201, la fila vieja intacta salvo `revocada_en` no nulo y una única MECANICO abierta (la nueva); confirmar VERDE.
- [x] 6.6 TRIANGULAR concurrencia: dos `POST` iguales lanzados con `asyncio.gather` desde dos clientes ADMIN → códigos `{201, 409}`, una sola asignación abierta de ese rol y un solo evento; el 409 sin texto de la base (traducción de `uq_asignacion_rol_abierta`); confirmar VERDE.
- [x] 6.7 REFACTOR; `pytest --exigir-db` VERDE.

## 7. Revocación y autoprotección (`DELETE /usuarios/{id}/roles/{rol}`, spec `roles-usuario`)

- [x] 7.1 RED: `test/integration/test_usuarios_revocar.py` (C-07) — usuario RECEPCION con sesión llama con éxito a una ruta de prueba que exige RECEPCION (`requiere_rol(Rol.RECEPCION)` en un router protegido de prueba definido en el propio archivo de test, montado en una app derivada de `app_auth` sin modificar `conftest.py`), un ADMIN revoca RECEPCION → 200 con `revocada_en` y `vigente: false`; la misma cookie del usuario → 403; `GET /auth/yo` → RECEPCION sólo en `roles_token`; la fila sigue en `asignacion_rol` con `revocada_en`; evento `Revocación de rol RECEPCION a {email}`. Ejecutar y confirmar que FALLA.
- [x] 7.2 GREEN: `revocar_rol` (D4), `AsignacionNoEncontradaError` y handler `DELETE` con `rol: Rol` en la ruta; confirmar VERDE.
- [x] 7.3 TRIANGULAR 404/422: revocar dos veces → 200 y luego 404 "El usuario no tiene ese rol asignado" con una sola fila revocada y un solo evento; rol nunca asignado → 404 sin evento; usuario inexistente → 404; `rol` `JEFE` en la ruta → 422; revocar una asignación abierta pero vencida → 200; confirmar VERDE.
- [x] 7.4 RED → GREEN autoprotección (C-08, D5): el ADMIN se revoca su ADMIN → 409 "No puede revocarse su propio rol ADMIN", su asignación sigue abierta, sin evento y puede seguir llamando `GET /eventos` (200); con dos ADMIN, uno revoca al otro → 200 y el revocado recibe 403 en `GET /eventos`; un ADMIN se revoca su propio MECANICO → 200; implementar `AutoRevocacionAdminError`, `UltimoAdminError` y el uso de `bloquear_admins_vigentes`; confirmar VERDE.
- [x] 7.5 TRIANGULAR último admin: con exactamente dos ADMIN (A y B), lanzar a la vez A revoca B y B revoca A (`asyncio.gather`) → códigos `{200, 409}` con el mensaje "El sistema debe conservar al menos un administrador" o el de auto-revocación según el orden, y exactamente un ADMIN vigente al final; con un ADMIN inactivo además de A, el inactivo no cuenta (A no puede quedar como "último" protegido por un inactivo: verificar con el método de repositorio); si la carrera HTTP no es determinística, cubrirla con el test de dos transacciones de 3.3 y dejar el HTTP como verificación adicional sin intermitencias (repetir N veces); confirmar VERDE.
- [x] 7.6 REFACTOR: precedencia de errores de D9 documentada en el docstring del servicio; `pytest --exigir-db` VERDE.

## 8. Historial de seguridad (`GET /eventos`, spec `historial-seguridad`)

- [x] 8.1 RED: `test/integration/test_eventos.py` — un cliente se registra (`POST /auth/registro`), cambia su contraseña y un ADMIN le asigna MECANICO; `GET /eventos` → 200 con `total` 3 e `items` en orden asignación → cambio → registro, cada uno con `{id, cuando, actor, accion}`; `?page=2&size=2` → 1 elemento (el registro), `total` 3, `pages` 2. Ejecutar y confirmar que FALLA.
- [x] 8.2 GREEN: `listar_eventos` (servicio, `count` + `verificar_pagina` + `listar_recientes` en un bloque) y handler `GET /eventos` con `PaginacionDep` y `Pagina[EventoRespuesta]` (D7); confirmar VERDE.
- [x] 8.3 TRIANGULAR: `size=500`, `size=0`, `page=0` → 422; página más allá de la última → 422 "La página solicitada no existe"; sin eventos → 200 con `items` vacío y `pages` 1; un evento insertado por SQL con actor `SISTEMA` aparece; CLIENTE → 403; peticiones rechazadas de las secciones 5–7 (409, 404, 422) no agregaron eventos (verificar conteo antes/después en un test que encadena varias); confirmar VERDE.
- [x] 8.4 REFACTOR; `pytest --exigir-db` VERDE.

## 9. Verificación integral

- [x] 9.1 Con PostgreSQL levantado: `pytest --exigir-db` completo → todo VERDE y 0 skipped (incluida la línea base de 1.1); con el contenedor detenido: `pytest -m "not integration"` VERDE.
- [x] 9.2 Revisión estática contra reglas duras: sin `commit(` en `app/modules/**/repository.py`; sin `bcrypt.` fuera de `app/core/security.py`; toda clase de entrada nueva hereda `_Entrada` (`extra="forbid"`); ningún schema de respuesta con `password`/`password_hash`; sin contraseñas literales en `app/`, `main.py` ni en los tests nuevos; `app/core/*` sin cambios respecto de C-05; en `main.py` y `conftest.py` sólo se agregaron elementos a las listas de routers. Documentar el resultado en el resumen del apply.
- [x] 9.3 Manual con `.env` válido: sembrar un ADMIN por SQL (no hay seed hasta C-11), `fastapi dev main.py`; en `/docs` aparecen las 5 rutas nuevas bajo `usuarios` y `eventos`; alta de un MECANICO → 201; su login → `debe_cambiar_password: true`; asignar y revocar un rol con la sesión del usuario abierta → su siguiente petición 403; `GET /eventos` muestra las acciones en orden descendente.
