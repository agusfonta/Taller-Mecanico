# Arquitectura Propuesta

## Patrones aplicados

| Patrón | Dónde | Por qué |
|---|---|---|
| Arquitectura en capas por módulo | Router → Service → UoW → Repository → Model | Cada capa sabe lo suyo y nada más |
| Repository genérico | `BaseRepository[T]` (recibe sesión **y clase del modelo**: los genéricos se borran en runtime) | Evita duplicar CRUD |
| Repository con borrado lógico | `SoftDeleteRepository[T]` hereda de Base; filtra dados de baja; agrega `get_by_id_including_deleted` y `soft_delete` | Vehículo y Repuesto |
| Repositorio de sólo lectura (sin herencia) | Catálogo `estado_orden` (PK `codigo`, no `id`) | Heredar daría `add/update/delete` que no debe ofrecer |
| Unit of Work | `UnitOfWork` base (gestor de contexto asincrónico) + uno por módulo | Una transacción por operación de negocio |
| Dependency Injection | `get_session`, `get_usuario_actual`, `requiere_rol`, constructor de UoW | Aislar creación de recursos |
| Lifespan / recursos en `app.state` | Motor y fábrica de sesiones | Evitar crear recursos al importar (EA-08) |
| Eager loading en el repositorio | `selectinload/joinedload` declarado en el método que lo necesita | Sin N+1 ni carga perezosa |
| Catálogo + enum | `estado_orden` en base + enum en código | FK en base; contrato de API y transiciones en código |
| Sesión/transacción propia | `intento_acceso` | El fallo que se cuenta es el que revierte la petición |
| Disparador de sólo-agregado | Migración 2 | Inmutabilidad garantizada por la base |

## Reglas de las capas (requisitos del PDF)

- **Repositorio**: `add` y `update` hacen `flush()`, **nunca `commit()`**. Cada entidad tiene su repositorio; métodos nombrados por lo que traen.
- **UoW base**: confirma al salir del bloque, revierte si hay excepción, **no cierra la sesión** (no la creó). Cada módulo compone sus repositorios con **la misma sesión**.
- **Router**: construye el UoW con una dependencia y lo pasa al servicio **sin abrirlo**; traduce errores.
- **Servicio**: recibe el UoW y lo abre con `async with`; **nunca lo construye**. Contiene las reglas de negocio.
- RN-02, RN-13 y RN-20 se escriben cada una en **un solo bloque** `async with uow`.
- El stock se escribe en **un único punto** (RN-14), usado por reposición y terminación.

## Estructura de directorios (obligatoria)

```
proyecto/
├── main.py                       # app, lifespan, dos grupos de rutas
├── seed.py                       # deja la base en estado inicial conocido
├── alembic.ini
├── requirements.txt
├── env.example                   # todas las variables, ningún secreto
├── README.md                     # pasos desde cero
├── migrations/                   # plantilla asincrónica + versiones
├── test/                         # *.http + solo_agregado.sql
└── app/
    ├── core/
    │   ├── config.py             # Settings (pydantic-settings)
    │   ├── database.py           # crea motor/fábrica (los llama el lifespan) + get_session
    │   ├── security.py           # bcrypt fuera del bucle; emisión/verificación de token
    │   ├── dependencies.py       # usuario actual, roles vigentes, control de cambio, requiere_rol
    │   ├── repository.py         # BaseRepository[T], SoftDeleteRepository[T]
    │   ├── paginacion.py         # envoltorio {items,total,page,size,pages}
    │   └── unit_of_work.py       # UnitOfWork base
    └── modules/
        ├── health/    (router.py)
        ├── usuarios/  (models, schemas, repository, unit_of_work, service, router)
        ├── clientes/  (idem)   # Cliente, Vehiculo
        ├── repuestos/ (idem)   # Repuesto, MovimientoStock, HistorialPrecio
        └── ordenes/   (idem)   # EstadoOrden, OrdenTrabajo, ItemOrden, HistorialEstadoOrden
```

## Seguridad

- **Autenticación**: JWT (`sub`, `iat` fraccional, `exp`, roles al emitir) firmado con PyJWT, **sólo** en cookie `access_token` (HttpOnly, SameSite=Lax, Max-Age = duración, Secure configurable). Nunca en el cuerpo ni leído de `Authorization`.
- **Contraseñas**: bcrypt con costo en la configuración; siempre `to_thread` y bajo **semáforo**; hash calculado **antes** de abrir la transacción; máx. 72 bytes.
- **Anti-enumeración**: mismo mensaje y tiempo con hash ficticio (calculado una vez en el lifespan).
- **Fuerza bruta**: 5 fallos / 60 s por (email, ip) → 429 + `Retry-After`.
- **Autorización**: roles vigentes consultados en la base en cada petición; 401 ≠ 403.
- **Validación de entrada**: `extra="forbid"`, `exclude_unset`; ninguna entrada inválida termina en 500; SQL con parámetros ligados.
- **Errores**: mensajes propios; nunca texto del `IntegrityError` ni trazas.
- **Secrets**: ninguno en código ni en `alembic.ini`; la app no arranca si faltan.

## Variables de entorno

| Variable | Descripción | Ejemplo | Sensible |
|---|---|---|---|
| `POSTGRES_USER` | Usuario de la base | `taller` | N |
| `POSTGRES_PASSWORD` | Contraseña (sin default) | `<definir>` | **Y** |
| `POSTGRES_DB` | Nombre de la base | `taller_db` | N |
| `POSTGRES_HOST` | Host | `localhost` | N |
| `POSTGRES_PORT` | Puerto | `5432` | N |
| `JWT_SECRET_KEY` *(nombre sugerido)* | Clave de firma (sin default) | generar aleatoria | **Y** |
| `JWT_EXPIRE_MINUTES` *(DD-13)* | Duración del token (30 min = 1800 s, como el ejemplo del PDF) | `30` | N |
| `BCRYPT_ROUNDS` *(DD-13)* | Costo de bcrypt | `12` | N |
| `BCRYPT_MAX_CONCURRENCY` *(sugerido)* | Tope del semáforo | `4` | N |
| `COOKIE_SECURE` *(sugerido)* | `Secure` en la cookie | `false` en dev | N |
| `DB_POOL_SIZE` *(sugerido)* | Tamaño del pool (sec. 4.5) | `5` | N |
| `DB_MAX_OVERFLOW` *(DD-17)* | Conexiones extra sobre el pool | `10` | N |
| `SQL_ECHO` | Ver consultas en consola | `true` | N |

> El PDF fija las `POSTGRES_*` y `SQL_ECHO`; los demás nombres son **sugeridos** (ver [10](10_preguntas_abiertas.md)).

## Diagnóstico y entrega

- `SQL_ECHO=true` para evidenciar el caso C-15 (consultas fijas del detalle de orden).
- Entrega: repo con código, `requirements.txt`, `env.example`, `alembic.ini`, `migrations/`, `test/`; `.env` no se sube; README con venv → dependencias → `.env` (cómo generar la clave) → `alembic upgrade head` → `python seed.py` → servidor; evidencias de C-14 y C-15.
