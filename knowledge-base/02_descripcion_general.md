# Descripción General

## Stack tecnológico

| Capa | Tecnología | Versión mínima | Uso |
|---|---|---|---|
| Lenguaje | Python | 3.12 | — |
| Framework web | FastAPI | 0.111 | Todos los handlers `async def` |
| Modelos de tabla | SQLModel | 0.0.24 | — |
| ORM / motor | SQLAlchemy asincrónico | 2.0 | Motor, sesión, carga anticipada |
| Driver | asyncpg | 0.30 | (se acepta psycopg 3 asincrónico) |
| Base de datos | PostgreSQL | 16 | — |
| Migraciones | Alembic | 1.13 | Plantilla **asincrónica** |
| Configuración | pydantic-settings | 2.0 | Clase `Settings` desde entorno / `.env` |
| Hash | bcrypt | 4.0 | Contraseñas |
| Token | PyJWT | 2.8 | JWT firmado |
| Servidor | uvicorn | el que instala `fastapi[standard]` | ASGI |

## Arquitectura general

API monolítica organizada **por módulo funcional**, con las mismas seis capas en cada módulo:

```
HTTP ─► Router ─► Service ─► UnitOfWork ─► Repository ─► Model ─► PostgreSQL
        (construye UoW,   (reglas de     (confirma/     (flush,    (tablas,
         traduce errores)  negocio; abre  revierte;      nunca      restricciones)
                           el UoW)        no cierra      commit)
                                          la sesión)
```

- El **router** construye el UoW con una dependencia y se lo pasa al servicio **sin abrirlo**.
- El **servicio** abre el UoW con `async with` y **nunca lo construye**.
- El **UoW** confirma al salir del bloque, revierte si sale con excepción y no cierra la sesión (no la creó).
- Los **repositorios** hacen `flush()`, **nunca `commit()`**.
- Motor y fábrica de sesiones se crean en el **lifespan** y se guardan en `app.state` (no al importar un módulo, EA-08 / sec. 1.9).

Dos grupos de rutas en `main.py`: **abierto** y **protegido**. El protegido lleva montado una sola vez el control de cambio obligatorio de contraseña (FastAPI suma dependencias y no las resta, sec. 5.10).

## Módulos mínimos

| Módulo | Entidades que viven en él |
|---|---|
| `health` | sólo `router.py` |
| `usuarios` | Usuario, AsignacionRol, IntentoAcceso, EventoSeguridad |
| `clientes` | Cliente, Vehiculo |
| `repuestos` | Repuesto, MovimientoStock, HistorialPrecio (`historial_precio_repuesto`) |
| `ordenes` | OrdenTrabajo, EstadoOrden, ItemOrden, HistorialEstadoOrden |

## Integraciones externas

| Servicio | Propósito | Tipo |
|---|---|---|
| PostgreSQL 16 | Persistencia y garantías (unicidad, FK, CHECK, disparador) | Driver asincrónico |
| Aviso al cliente (simulado) | Notificar al terminar una orden | `BackgroundTasks` + `await asyncio.sleep(0.5)` + log; sin integración real |

No hay Redis, colas ni servicios de terceros.

## Configuración (`Settings`)

Variables sueltas `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_HOST`, `POSTGRES_PORT`; la URL se arma con un `@computed_field` (`postgresql+asyncpg` o `postgresql+psycopg`). La clave de firma de tokens sale del entorno. **Ni la clave ni la contraseña de la base tienen valor por defecto**: si faltan, la app no arranca. El repo incluye `env.example` con todas las variables y ningún secreto; `.env` no se versiona. Ver detalle en [08](08_arquitectura_propuesta.md).

## API REST

Resumen por recurso (detalle completo con roles y códigos en [06](06_funcionalidades.md)):

| Recurso | Rutas |
|---|---|
| health | `GET /health/live`, `GET /health/ready` |
| auth | `POST /auth/registro`, `/auth/login`, `/auth/logout`, `/auth/cambiar-password`; `GET /auth/yo` |
| usuarios | `POST /usuarios`; `GET/POST /usuarios/{id}/roles`; `DELETE /usuarios/{id}/roles/{rol}`; `GET /eventos` |
| clientes / vehículos | `POST /clientes`; `GET /clientes/{id}`; `POST /clientes/{id}/vehiculos`; `DELETE /vehiculos/{id}`; `GET /mis-vehiculos` |
| repuestos | `GET/POST /repuestos`; `GET/PATCH/DELETE /repuestos/{id}`; `POST /repuestos/{id}/reponer`; `GET /repuestos/{id}/movimientos`; `GET /repuestos/{id}/precios` |
| órdenes | `GET/POST /ordenes`; `GET /ordenes/{id}`; `POST /ordenes/{id}/iniciar|terminar|cancelar`; `GET /estados-orden`; `GET /mis-ordenes` |
