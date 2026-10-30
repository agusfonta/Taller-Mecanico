# Proposal — C-12 `verificacion-y-entrega`

## Why

C-01..C-11 están archivados y la suite automática cubre los casos de la KB 11, pero el repositorio todavía **no es entregable** según el "Formato de entrega" del PDF (pág. 22): no existe `README.md`, no hay ningún `test/*.http` ni `test/solo_agregado.sql`, y faltan las evidencias de C-14 y C-15. El PDF además advierte que un proyecto que no levanta, que no crea su esquema con `alembic upgrade head` sobre una base vacía o que contiene credenciales reales "no se corrige hasta que se subsane". Este es el último change: cierra la entrega y verifica de punta a punta, sobre una base recién migrada y cargada con el seed, que los 19 casos dan el resultado esperado.

## What Changes

- **`README.md`** (raíz, nuevo): pasos desde cero — requisitos (Python 3.12+, Docker), entorno virtual, `pip install -r requirements.txt` (y `requirements-dev.txt` para tests), copiar `env.example` a `.env` y cómo generar `JWT_SECRET_KEY`, levantar PostgreSQL con `docker compose`, `alembic upgrade head`, `python seed.py` (advierte que BORRA los datos), arranque con `uvicorn main:app`, cómo correr los `.http` y `test/solo_agregado.sql`, cómo correr `pytest` (`--exigir-db`) y dónde están las evidencias. Las contraseñas del seed se **referencian** (`CONTRASENAS_SEED` en `seed.py`), nunca se copian.
- **`test/*.http`** (nuevos): un archivo por caso C-01..C-19 (salvo C-14, que es SQL), cada pedido con la respuesta esperada en un comentario; corrible con la extensión REST Client tras `python seed.py`; sesiones múltiples con `# @name` + `# @no-cookie-jar` (C-07). Las contraseñas no se escriben en los `.http` (DD-15 y el test `test_seed_secretos.py`): se piden al enviar (decisión a aprobar).
- **`test/solo_agregado.sql`** (nuevo): los seis intentos (UPDATE y DELETE sobre `historial_estado_orden`, `movimiento_stock`, `historial_precio_repuesto`) rechazados por el disparador, más el INSERT de una orden con estado fuera del catálogo rechazado por la FK; corrible con `psql` dentro del contenedor.
- **Evidencias** `docs/evidencias/`: PNG de C-14 (`psql`) y de C-15 (consultas del detalle de una orden de 2 ítems y de otra de 4 con `SQL_ECHO=true`), con su fragmento de texto como respaldo (DD-22).
- **Verificación de punta a punta** sobre una base nueva (separada de la de desarrollo): `alembic upgrade head` desde vacío, `downgrade base` / `upgrade head`, `python seed.py`, servidor real, los 19 casos ejecutados y registrados en una **matriz de trazabilidad** caso → archivo `.http`/SQL → test automático → resultado.
- **Revisión final** de entrega: estructura obligatoria (KB 08), ningún 500 ni `IntegrityError`/traza expuestos ante entrada inválida, ningún secreto en el repo, `env.example` completo, `requirements.txt` coherente, reglas duras de `CLAUDE.md`, y sincronía de `CLAUDE.md`/`AGENTS.md`/`CHANGES.md`.
- **Hallazgo a corregir (con TDD, a aprobar)**: el aviso al cliente se emite con `logger.info` en `app.modules.ordenes.avisos`, pero la app no configura logging; bajo `uvicorn` el logger raíz queda en WARNING y el aviso **no aparece en consola**, con lo que C-12 ("el aviso sale en el registro después de la respuesta") no se puede demostrar manualmente. Se propone configurar el logger `app` en nivel INFO al arrancar.
- Sin cambios de esquema, endpoints ni contratos.

## Capabilities

### New Capabilities
- `entrega`: artefactos de entrega del trabajo práctico — README con los pasos desde cero, archivos `.http` por caso con la respuesta esperada, `test/solo_agregado.sql`, evidencias de C-14/C-15, matriz de trazabilidad de los casos, y ausencia de credenciales reales en los artefactos.

### Modified Capabilities
- `estructura-proyecto`: la estructura obligatoria pasa a incluir `README.md` en la raíz y, dentro de `test/`, los `*.http` y `solo_agregado.sql` (KB 08 §Estructura).
- `aviso-cliente`: el aviso registrado en segundo plano MUST ser visible en la consola del servidor al correr con `uvicorn` (nivel INFO para los loggers de la app), sin cambiar su formato ni el momento en que se emite.

## Impact

- **Archivos nuevos**: `README.md`, `test/c01_*.http` … `test/c19_*.http` (18 archivos), `test/solo_agregado.sql`, `docs/evidencias/*.png|*.txt`, matriz de trazabilidad (ubicación a aprobar).
- **Código**: una configuración mínima de logging en el arranque (`main.py`/lifespan o `app/core/`) — sólo si se aprueba la corrección del aviso. Tests nuevos: `test/unit/test_entrega.py` (estructura y contenido de README, `.http` y SQL, estáticos) y, para el logging, unit test del arranque.
- **Tests existentes**: `test/unit/test_estructura.py` se amplía (README); `test_seed_secretos.py` ya escanea `.http`/`.sql`/`.md` y debe seguir en verde.
- **Base de datos**: ningún cambio de esquema. La verificación E2E usa una base **separada** (p. ej. `taller_entrega` en el mismo contenedor) para no borrar la de desarrollo; cualquier corrida sobre la base de desarrollo es **ALTO** y requiere aprobación.
- **Dependencias**: ninguna nueva.
- **Git**: el primer commit NO forma parte del change salvo pedido explícito del usuario.
- **Governance**: MEDIO (documentación, artefactos de entrega y verificación); las decisiones del `design.md` §"Decisiones a aprobar" requieren el visto bueno antes de `apply`.
