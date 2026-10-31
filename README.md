# Taller Mecánico

- Integrantes: Agustina Fontagnol, Martina Suarez y Gianella Peña

API asincrónica para un taller mecánico: clientes, vehículos, órdenes de trabajo, stock de repuestos y acceso por roles.
Trabajo práctico de Programación III (TUP). Enunciado: `docs/TP_Cap1a6_Consigna.pdf`.

Stack: Python 3.12+, FastAPI, SQLModel, SQLAlchemy asincrónico, asyncpg, PostgreSQL 16, Alembic, bcrypt y PyJWT.
Arquitectura: Router → Service → UnitOfWork → Repository → Model, por módulo (`health`, `usuarios`, `clientes`,
`repuestos`, `ordenes`) bajo `app/modules/`, con lo transversal en `app/core/`.

## Requisitos

- Python 3.12 o superior.
- Docker con Docker Compose (para PostgreSQL 16) o un PostgreSQL 16 propio.

## Puesta en marcha

Los comandos son de PowerShell (Windows); en Linux/macOS cambia sólo la activación del entorno virtual.

### 1. Entorno virtual

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1      # Linux/macOS: source .venv/bin/activate
```

### 2. Dependencias

```powershell
pip install -r requirements.txt
pip install -r requirements-dev.txt    # sólo para correr los tests
```

### 3. Configuración (`.env`)

Copiá `env.example` a `.env` y completá los valores. **`.env` no se versiona** (está en `.gitignore`): contiene secretos.

```powershell
Copy-Item env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"   # pegar el resultado en JWT_SECRET_KEY
```

- `JWT_SECRET_KEY` (mínimo 32 caracteres) y `POSTGRES_PASSWORD` son obligatorias y no tienen valor por defecto: si faltan,
  la aplicación no arranca. `POSTGRES_PASSWORD` la elegís a mano.
- `POSTGRES_PORT` es el puerto que Docker publica en tu equipo. Si el 5432 ya está ocupado, usá otro (por ejemplo 5433).
- `SQL_ECHO=true` muestra las consultas SQL en la consola del servidor (útil para el caso C-15).

### 4. PostgreSQL

```powershell
docker compose up -d
docker compose ps          # esperar a que el servicio figure como "healthy"
```

### 5. Migraciones

```powershell
alembic upgrade head
```

### 6. Datos iniciales (seed)

```powershell
python seed.py
```

> **Atención: `python seed.py` borra todos los datos de las 13 tablas de la base destino** y los vuelve a cargar. Es
> idempotente (repetirlo deja el mismo resultado) y por defecto sólo acepta una base local.

Crea 7 usuarios de demostración, 2 clientes con 3 vehículos, 4 repuestos y 2 órdenes. Las **contraseñas de demostración
no están en este archivo**: viven únicamente en `CONTRASENAS_SEED`, dentro de `seed.py`.

| Usuario | Rol | Notas |
|---|---|---|
| `admin@example.com`, `admin2@example.com` | ADMIN | |
| `recepcion@example.com` | RECEPCION | |
| `mecanico@example.com`, `mecanico2@example.com` | MECANICO | `mecanico` tiene asignada la orden 2 |
| `cliente@example.com` | CLIENTE | es Laura, dueña de los vehículos 1 y 2 |
| `nuevo@example.com` | MECANICO | debe cambiar la contraseña en el primer ingreso |

### 7. Servidor

```powershell
uvicorn main:app
```

Comprobación: `GET http://localhost:8000/health/ready` responde 200 cuando la base está disponible, y la documentación
interactiva está en `http://localhost:8000/docs`. Con este comando (no con `fastapi dev`) las líneas de log de la
aplicación, como el aviso al cliente al terminar una orden, se ven en la consola.

## Casos de prueba y evidencias

Cada caso C-01..C-19 de la consigna tiene su artefacto en `test/`:

- **`test/cNN_<tema>.http`** (todos los casos salvo C-14): para la extensión *REST Client* de VS Code. Cada pedido lleva en
  un comentario `# Esperado: <código>` con la respuesta que debe dar.
  1. Corré `python seed.py` **antes de cada archivo** (cada uno parte del estado del seed).
  2. Abrí el archivo, tocá *Send Request* sobre cada pedido, en orden.
  3. Los logins usan `# @prompt`: REST Client te pide la contraseña al enviar (copiala de `CONTRASENAS_SEED` en `seed.py`;
     para `clave_elegida` o `clave_incorrecta` escribí cualquier texto). Nada queda escrito en el archivo.
  4. C-07 y C-12 usan dos sesiones a la vez: cada login lleva `# @name` y los pedidos siguientes envían su cookie con
     `# @no-cookie-jar`.
- **`test/solo_agregado.sql`** (C-14): intenta UPDATE y DELETE sobre las tres tablas de sólo agregado y una orden con un
  estado inexistente. Después de `python seed.py`:

  ```powershell
  docker compose exec -T postgres psql -U <POSTGRES_USER> -d <POSTGRES_DB> < test/solo_agregado.sql
  ```

  Se esperan siete errores (seis del disparador y uno de clave foránea) y conteos finales sin cambios. En PowerShell, si
  `<` no funciona, usá `Get-Content test/solo_agregado.sql | docker compose exec -T postgres psql -U <POSTGRES_USER> -d <POSTGRES_DB>`.
- **C-15**: arrancá el servidor con `SQL_ECHO=true` y corré `test/c15_detalle_consultas.http`; el detalle de la orden de 2 y
  el de 4 ítems muestran la misma cantidad de sentencias.

Resultados y trazabilidad: [`docs/verificacion.md`](docs/verificacion.md) (matriz caso → archivo → tests → resultado) y capturas
en [`docs/evidencias/`](docs/evidencias/) (C-14 y C-15).

## Tests

```powershell
pytest test/unit                 # sin base de datos
pytest --exigir-db               # suite completa: usa el PostgreSQL de .env; tarda varios minutos
```

Los tests de integración crean esquemas efímeros (`c02_prueba_<hex>`, etc.) y nunca tocan `public`. Con `--exigir-db`, si la
base no responde los tests fallan en vez de omitirse. Los `.http` también se ejecutan dentro de la suite
(`test/integration/test_http_casos.py`) con un intérprete mínimo, y `test/solo_agregado.sql` se prueba sentencia por sentencia.

## Estructura

```
main.py            app FastAPI (lifespan, routers)
seed.py            datos iniciales de demostración
alembic.ini        configuración de Alembic (sin credenciales)
migrations/        migraciones (esquema inicial y disparador de sólo agregado)
env.example        plantilla de .env, sin secretos
app/core/          configuración, base, seguridad, repositorio y UoW base, errores, paginación
app/modules/       health, usuarios, clientes, repuestos, ordenes
test/              tests (unit/, integration/), archivos .http y solo_agregado.sql
docs/              consigna, matriz de verificación y evidencias
knowledge-base/    base de conocimiento del dominio
```
