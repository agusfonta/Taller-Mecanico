# Design — C-12 `verificacion-y-entrega`

## Context

Motivación en `proposal.md` §Why. Estado observado del repositorio (2026-10-30):

- Existen `main.py`, `seed.py`, `alembic.ini`, `env.example` (las 13 variables, secretos vacíos, comando para generar la clave), `requirements.txt` / `requirements-dev.txt`, `docker-compose.yml` (postgres:16 con healthcheck; el puerto publicado sale de `POSTGRES_PORT`, en este equipo 5433 vía `.env`), `migrations/` (dos versiones: `acf6d613aa1c_esquema_inicial`, `6f80b22e25d4_solo_agregado` a mano) y `test/` con ~1675 tests pytest.
- **No existen** `README.md`, ningún `test/*.http` ni `test/solo_agregado.sql`, ni `docs/evidencias/`.
- `test/unit/test_seed_secretos.py` recorre todos los `.py/.md/.sql/.http/.json/...` del repo (salvo `seed.py`/`.env`) y falla si alguno contiene una contraseña de `CONTRASENAS_SEED` (DD-15). Los `.http` necesitan loguearse, así que **no pueden llevar las contraseñas escritas**.
- El seed deja ids fijos: usuarios 1..7 (`admin`=1, `admin2`=2, `recepcion`=3, `mecanico`=4, `mecanico2`=5, `cliente`=6, `nuevo`=7), clientes Laura=1 / Jorge=2, vehículos 1..3, repuestos 1..4 (`BUJ-001`=3, stock 2), orden 1 PENDIENTE (2 ítems, vehículo de Laura), orden 2 EN_REPARACION (2 ítems, 4 bujías, vehículo de Jorge, mecánico 4). Ninguna orden tiene 4 ítems: C-15 necesita crearla.
- `app/modules/ordenes/avisos.py` emite el aviso con `logger.info` en `app.modules.ordenes.avisos`, y **nada configura logging** (`main.py` ni `app/core/`). Bajo `uvicorn` sólo se configuran los loggers `uvicorn.*`; el raíz queda en WARNING y el `lastResort` sólo muestra WARNING+, así que el aviso no se vería en consola (a confirmar en la tarea 2.1 antes de tocar código).
- Los parámetros de ruta `{id}` son `int` sin cota (p. ej. `orden_id: int`). Un id mayor que 2^63-1 pasa la validación y llega a asyncpg como `BIGINT` fuera de rango; no hay manejador para `DBAPIError`/`DataError`, por lo que **probablemente** responde 500 (a confirmar con un test en la tarea 3.1).
- Los tests de integración usan esquemas efímeros `c02_prueba_<hex>` y nunca tocan `public`. `test/integration/conftest.py` hace ping con timeout de 3 s.

## Goals / Non-Goals

**Goals:**
- Dejar el repo cumpliendo el "Formato de entrega" del PDF y la estructura de la KB 08.
- Que los `.http` y `solo_agregado.sql` estén **probados automáticamente** (no sólo escritos) y además se corran una vez a mano contra el servidor real.
- Una verificación de punta a punta reproducible sobre una base nueva, sin destruir la base de desarrollo.

**Non-Goals:**
- Nuevos endpoints, cambios de esquema o migraciones.
- CI, Dockerfile de la app, despliegue.
- El primer commit de git (sólo se prepara un plan, si se aprueba D11).
- Reescribir tests verdes existentes (ver D9).

## Decisions

### D1 — Un `.http` por caso, en `test/`, numerados
`test/c01_parametro_ruta.http`, `test/c02_registro.http`, … `test/c19_baja_vehiculo.http` (18 archivos; C-14 es SQL). El PDF dice "antes de cada archivo se corre `python seed.py`": un archivo por caso hace que cada uno sea independiente del estado que dejan los otros (C-05 bloquea el login 60 s, C-09 cambia la contraseña de `nuevo`, C-12 termina la orden 2, C-13 cancela la 1). Cada archivo arranca con `@base = http://localhost:8000` y un comentario de cabecera (caso, reglas, precondición "correr `python seed.py`").
Formato de cada pedido:
```
### C-06 · cliente ve la orden ajena
# Esperado: 403 Forbidden — {"detail": "..."}
GET {{base}}/ordenes/2
```
La línea `# Esperado: <código>` es obligatoria y parseable (la usa D3).
*Alternativas*: un archivo por tema (auth/órdenes/…) — menos archivos, pero los casos se pisan y hay que re-sembrar a mitad de archivo; subcarpeta `test/http/` — el PDF pide los `.http` "en `test/`".

### D2 — Contraseñas de los logins: `# @prompt` de REST Client (a aprobar)
Cada login declara `# @prompt clave_admin Contraseña de admin@example.com (CONTRASENAS_SEED en seed.py)` y usa `{{clave_admin}}` en el cuerpo. REST Client la pide al enviar; nada queda escrito. Cumple DD-15 y el test de secretos sin cambios.
*Alternativas*: (a) escribir las contraseñas en los `.http` — lo más cómodo para el corrector, pero revierte DD-15 y obliga a cambiar `test_seed_secretos.py`; (b) archivo de variables ignorado por git (`.vscode/settings.json` / `http-client.env.json`) generado desde `seed.py` — cómodo, pero agrega un script y un archivo local que el test de secretos también encontraría (habría que excluirlo); (c) `{{$dotenv ...}}` — exige variables `SEED_*`, prohibidas por `configuracion`.

### D3 — Los `.http` se ejecutan en la suite (a aprobar)
`test/integration/test_http_casos.py`: un intérprete mínimo del subconjunto de REST Client que usamos (`@var = valor`, `###`, `# @name`, `# @prompt`, `# @no-cookie-jar`, `{{var}}`, `{{nombre.response.headers.Set-Cookie}}`, línea `# Esperado: NNN`) que, por cada archivo parametrizado: carga el seed (`cargar_datos_iniciales`) en un esquema efímero migrado, resuelve cada `@prompt clave_*` con `seed.CONTRASENAS_SEED` (sólo en memoria), envía los pedidos en orden contra la app ASGI (mismo montaje que `test/integration/seed/conftest.py`) y compara el código con `# Esperado`. Además, `test/unit/test_entrega.py` (estático, sin base): un archivo por caso, cada pedido con `# Esperado`, sin `Authorization` real ni cookies literales.
Así un `.http` mal escrito falla en `pytest` (TDD: el test del caso se escribe antes que el archivo). Lo que no es código de estado (tiempo parecido en C-04, `Retry-After` "en pocos ms" en C-05, el aviso después de la respuesta en C-12) se comprueba en la corrida manual (D7) y ya lo cubren los tests existentes.
*Alternativa*: sólo validación estática + corrida manual — menos código, pero los `.http` pueden desalinearse del comportamiento sin que nada falle.

### D4 — `test/solo_agregado.sql`
Sin `BEGIN`: `psql` en autocommit ejecuta cada sentencia sola y sigue tras un error (no se usa `ON_ERROR_STOP`). Seis sentencias sobre filas que el seed garantiza (`UPDATE historial_estado_orden SET ... WHERE id = 1`, `DELETE FROM historial_estado_orden WHERE id = 1`, idem `movimiento_stock` id 1 e `historial_precio_repuesto` id 1) y un `INSERT INTO orden_trabajo (vehiculo_id, estado, falla) VALUES (1, 'INEXISTENTE', 'C-14')`, cada una con `-- Esperado: ERROR ...`. Al final, `SELECT count(*)` de las cuatro tablas para mostrar que nada cambió. Comando documentado en el README: `docker compose exec -T postgres psql -U taller -d taller_db < test/solo_agregado.sql` (sin pedir contraseña: socket local del contenedor).
Test: `test/integration/test_solo_agregado_sql.py` parte el archivo por `;`, corre cada sentencia en su propio SAVEPOINT sobre un esquema efímero migrado + seed, y verifica 6 errores del disparador (SQLSTATE `P0001`, mensaje con tabla y operación), 1 de FK (`23503`) y conteos intactos.

### D5 — Base de verificación separada (no destructiva)
La verificación E2E usa una base nueva `taller_entrega` en el mismo contenedor (`docker compose exec postgres createdb -U taller taller_entrega`) y variables de entorno de shell que pisan `.env` sólo para esos comandos (`POSTGRES_DB=taller_entrega`; pydantic-settings prioriza el entorno sobre `.env`). Pasos: `alembic upgrade head` desde vacío → `alembic downgrade base` → `alembic upgrade head` → `python seed.py` (dos veces, idempotencia) → `uvicorn main:app` (con y sin `SQL_ECHO`). Al terminar, `dropdb taller_entrega` **sólo con aprobación** (D12). La base de desarrollo `taller_db` no se toca. Correr el seed o un downgrade sobre `taller_db` es ALTO y queda fuera salvo pedido explícito.
*Alternativa*: `docker compose down -v` y base de cero — prueba también el volumen, pero borra los datos de desarrollo.

### D6 — Verificación "desde cero" de dependencias (a aprobar)
Crear un entorno virtual temporal en el scratchpad, `pip install -r requirements.txt` y arrancar `python -c "import main"` con un entorno mínimo; luego `pip install -r requirements-dev.txt` y `pytest test/unit`. Detecta dependencias usadas pero no declaradas. Requiere red. Además, auditoría estática: imports de `app/`, `main.py`, `seed.py`, `migrations/` contra `requirements.txt`, y de `test/` contra `requirements-dev.txt`.

### D7 — Corrida manual y evidencias (checkpoint con el usuario)
Con el servidor real sobre `taller_entrega`: la agente corre los `.http` con el mismo intérprete de D3 apuntado a `http://localhost:8000` (modo "remoto" del intérprete, contraseñas tomadas de `seed.py` en memoria) y registra la salida de consola. El usuario corre al menos C-07 y C-12 en VS Code REST Client y toma las capturas:
- `docs/evidencias/c14_psql.png` + `c14_psql.txt`: comando `psql` con los 7 errores.
- `docs/evidencias/c15_sql_echo.png` + `c15_sql_echo.txt`: `SQL_ECHO=true`, `GET /ordenes/1` (2 ítems) y `GET /ordenes/3` (4 ítems, creada por `c15_*.http` con los 4 repuestos), con el conteo de sentencias de cada uno.
Los `.txt` los genera la agente desde la salida real (sin contraseña, sin cookie, sin `database_url`); las PNG las toma el usuario (DD-22). *Alternativa*: generar las PNG renderizando el texto con una librería de imágenes — no es una captura real y suma una dependencia.

### D8 — Matriz de trazabilidad en `docs/verificacion.md`
Tabla caso → `.http`/SQL → tests automáticos (archivo::test) → resultado manual → resultado automático, más: resultado de `pytest --exigir-db`, pasos de D5/D6, hallazgos y su corrección. El README la enlaza. *Alternativa*: sección dentro del README — lo alarga y mezcla guía de instalación con informe.

### D9 — `escenario_c11` se mantiene (a aprobar)
El ayudante de C-10 (`test/integration/ordenes/ayudantes.py::escenario_c11`) arma un estado equivalente al seed para la orden 2. Reemplazarlo por `cargar_datos_iniciales` uniría la fuente de verdad, pero cambia ~3 archivos de tests verdes, acopla los tests de órdenes al seed completo (más lentos: 7 hashes bcrypt por test) y C-11/C-12 sobre el seed real ya están en `test/integration/seed/test_seed_http_c11_c12.py` y lo estarán en D3. **Default: mantener.**

### D10 — Timeout del ping de la base: se deja en 3 s (opcional)
`test/integration/conftest.py` usa `asyncio.timeout(3)`. Subirlo (p. ej. 10 s) evitaría skips/fallos espurios con Docker frío, pero el usuario ya eligió dejarlo. **Default: dejar como está**; sólo se cambia si el usuario lo pide.

### D11 — Git: sólo plan de commit (a aprobar)
El change no hace commits. Si se aprueba, la tarea final deja un plan: verificación de que `git status` no lista `.env`, `.venv`, `.atl/`, `.claude/`, `__pycache__`, y un mensaje en conventional commits (`feat: api del taller mecánico con entrega del TP (C-01..C-12)` o commits por fase). Ejecutarlo requiere pedido explícito.

### D12 — Hallazgos de código se corrigen con TDD dentro del change (a aprobar)
- **Logging del aviso** (spec `aviso-cliente`): función idempotente en el arranque que agrega un `StreamHandler` con formato `%(levelname)s %(name)s: %(message)s` al logger `app` (nivel INFO) si no tiene uno propio; `propagate` sigue en `True` para no romper `caplog`. No toca `sqlalchemy.*` ni `uvicorn.*`. Primero se reproduce (2.1); si el aviso ya se ve, se descarta.
- **Ids fuera de rango** (spec `entrega` §"Ninguna entrada inválida termina en 500"): si 3.1 confirma el 500, un tipo de id compartido en `app/core/` (`int` con `ge=-2**63`, `le=2**63-1`, para no cambiar el 404 actual de ids 0 o negativos) en los parámetros de ruta de los cinco routers → 422 como C-01. Igual criterio para ids dentro del cuerpo (`vehiculo_id`, `repuesto_id`, …) si no están acotados. Otros 500 que aparezcan en el barrido (3.2) se reportan y se corrigen igual, cada uno con su test primero.
*Alternativa*: sólo reportar y dejar la corrección para un change aparte — pero C-12 es el último y el PDF exige "ninguna entrada inválida termina en 500".

### D13 — `CLAUDE.md` / `AGENTS.md` / `CHANGES.md`
Hoy `CLAUDE.md` y `AGENTS.md` son idénticos. Sólo se editan si la auditoría encuentra deriva (p. ej. falta mencionar `README.md`/`docs/verificacion.md`), y siempre los dos a la vez. `CHANGES.md` C-12 pasa a `[x]` en el archive.

## Risks / Trade-offs

- [`# @prompt` es incómodo: C-07 pide 2-3 contraseñas] → el README explica de dónde copiarlas; alternativa D2(a)/(b) si el usuario prefiere comodidad.
- [El intérprete de D3 soporta sólo un subconjunto de REST Client] → test unitario del intérprete; el `.http` que use otra sintaxis falla en el test estático; la corrida manual en VS Code (D7) valida la compatibilidad real.
- [C-03 "con `Authorization: Bearer` → 401": REST Client no extrae el token de la cookie] → se envía `Bearer` con un JWT bien formado pero sin cookie; el punto es que el encabezado se ignora. Se documenta en el comentario.
- [C-05 deja `admin` bloqueado 60 s] → cada archivo indica correr `python seed.py` antes (el seed vacía `intento_acceso`); el C-05 usa `recepcion` para no bloquear al admin de otros archivos.
- [El handler de logging duplica líneas si otro arranque configura el raíz (p. ej. `fastapi dev`)] → escenario "arranque repetido sin duplicados"; se prueba con `uvicorn` y se documenta el comando oficial en el README.
- [Capturas tomadas por el usuario pueden mostrar secretos (prompt, `.env`)] → checklist en la tarea de evidencias; revisión de las PNG antes de cerrar.
- [Suite completa `pytest --exigir-db` tarda 15-30 min, más los nuevos tests] → una sola corrida en serie en Verify; durante apply, sólo los archivos tocados.
- [`createdb`/`dropdb` en el contenedor] → base nueva con nombre propio; nunca se borra `taller_db`; `dropdb taller_entrega` requiere aprobación.

## Migration Plan

Sin migraciones. Orden: estáticos (README, estructura) → SQL C-14 → `.http` por grupos → hallazgos de código (TDD) → verificación E2E en `taller_entrega` → evidencias (usuario) → matriz → Verify. Rollback: todos los artefactos son archivos nuevos; las correcciones de código son acotadas y revertibles.

## Decisiones a aprobar (resumen)

1. **D1** — 18 `.http`, uno por caso, en `test/` con `# Esperado: NNN`.
2. **D2** — contraseñas de los logins con `# @prompt` (DD-15 intacto). Alternativas: literales en `.http` (cambia DD-15 y el test) o archivo local ignorado.
3. **D3** — los `.http` se ejecutan en `pytest` con un intérprete mínimo (recomendado) vs. sólo chequeo estático.
4. **D4** — `solo_agregado.sql` sin transacción, probado en la suite.
5. **D5** — verificación E2E en base nueva `taller_entrega`; `taller_db` intacta; `dropdb taller_entrega` al final sólo con OK.
6. **D6** — instalación desde cero en un venv temporal (requiere red) — sí/no.
7. **D7** — PNG las toma el usuario (checkpoint); la agente genera los `.txt` y la corrida automática contra el servidor real.
8. **D8** — matriz en `docs/verificacion.md` enlazada desde el README.
9. **D9** — mantener `escenario_c11` (default) vs. reemplazarlo por el seed real.
10. **D10** — timeout de ping 3 s: dejar (default) vs. subir a 10 s.
11. **D11** — sólo plan de commit, sin ejecutarlo.
12. **D12** — corregir dentro del change, con TDD, el logging del aviso y los ids fuera de rango (si se confirman) vs. sólo reportarlos.
13. **D13** — `CLAUDE.md`/`AGENTS.md` sólo si hay deriva, siempre juntos.
14. La copia de `TP_Cap1a6_Consigna.pdf` en la raíz duplica `docs/`: ¿quitarla de la raíz? (default: no tocar; se menciona en el plan de commit).
