# Taller Mecánico — Instrucciones para Agentes

> Este archivo (y su copia `CLAUDE.md`) es lo PRIMERO que todo agente lee al entrar al repo.
> Generado a partir de `knowledge-base/` y `CHANGES.md`. No editar a mano sin re-sincronizar ambos archivos.

API asincrónica para un taller mecánico (clientes, vehículos, órdenes de trabajo, stock y acceso por roles). Trabajo práctico de Programación III (TUP), fuente: `docs/TP_Cap1a6_Consigna.pdf`.

---

## Stack Tecnológico

| Capa | Tecnología | Versión mínima |
|------|------------|----------------|
| Lenguaje | Python | 3.12 |
| Framework web | FastAPI (`fastapi[standard]`) | 0.111 |
| Modelos de tabla | SQLModel | 0.0.24 |
| ORM / motor | SQLAlchemy asincrónico | 2.0 |
| Driver | asyncpg (se acepta psycopg 3 asincrónico) | 0.30 |
| Base de datos | PostgreSQL | 16 |
| Migraciones | Alembic (plantilla asincrónica) | 1.13 |
| Configuración | pydantic-settings | 2.0 |
| Hash | bcrypt | 4.0 |
| Token | PyJWT | 2.8 |
| Servidor | uvicorn | el de `fastapi[standard]` |

Arquitectura: Router → Service → UnitOfWork → Repository → Model, por módulo funcional (`health`, `usuarios`, `clientes`, `repuestos`, `ordenes`).

Detalle completo: [knowledge-base/02_descripcion_general.md](knowledge-base/02_descripcion_general.md)

---

## Base de Conocimiento

La fuente de verdad del dominio vive en `knowledge-base/`. **Leé el archivo relevante ANTES de implementar.**

| Archivo | Cuándo leerlo |
|---------|---------------|
| [01_vision_y_objetivos.md](knowledge-base/01_vision_y_objetivos.md) | Entender propósito, alcance y fuera de alcance |
| [02_descripcion_general.md](knowledge-base/02_descripcion_general.md) | Stack, capas, resumen de API |
| [03_actores_y_roles.md](knowledge-base/03_actores_y_roles.md) | Auth, RBAC, permisos por ruta |
| [04_modelo_de_datos.md](knowledge-base/04_modelo_de_datos.md) | Tablas, restricciones, migraciones, seed |
| [05_reglas_de_negocio.md](knowledge-base/05_reglas_de_negocio.md) | Reglas codificadas (RN-01..RN-20) |
| [06_funcionalidades.md](knowledge-base/06_funcionalidades.md) | Endpoints (roles y códigos) e historias de usuario |
| [07_flujos_principales.md](knowledge-base/07_flujos_principales.md) | Flujos E2E (login, orden, terminar, lifespan) |
| [08_arquitectura_propuesta.md](knowledge-base/08_arquitectura_propuesta.md) | Patrones, estructura obligatoria, seguridad, env vars |
| [09_decisiones_y_supuestos.md](knowledge-base/09_decisiones_y_supuestos.md) | Decisiones DD-xx y supuestos SU-xx |
| [10_preguntas_abiertas.md](knowledge-base/10_preguntas_abiertas.md) | ⚠️ Inconsistencias y dudas a resolver ANTES de codear |
| [11_casos_de_prueba_y_evaluacion.md](knowledge-base/11_casos_de_prueba_y_evaluacion.md) | Casos C-01..C-19, puntajes y evidencias de entrega |

> ✅ Las preguntas abiertas de `10_preguntas_abiertas.md` ya están resueltas (decisiones DD-13..DD-22 en `09_decisiones_y_supuestos.md`): nombres de variables de entorno, cuerpos de `POST /usuarios` y `POST /usuarios/{id}/roles`, contraseñas del seed sólo en `seed.py`, etc. Leer esas decisiones antes de proponer un change.

---

## Skills Disponibles

Instaladas a nivel proyecto en `.claude/skills/`. Fuente de verdad: `.atl/skill-registry.md`.

| Agente | Rol | Skills que carga |
|--------|-----|------------------|
| **Backend Core** | FastAPI / SQLModel / UoW / lifespan / config | `fastapi`, `fastapi-templates`, `async-python-patterns`, `python-configuration`, `python-project-structure` |
| **Persistencia** | Modelos, migraciones, PostgreSQL, rendimiento | `postgresql-table-design`, `postgres-patterns`, `sqlalchemy-alembic-expert-best-practices-code-review`, `database-migration`, `sql-optimization-patterns` |
| **Seguridad** | Auth JWT/cookie, RBAC, bcrypt | `auth-implementation-patterns`, `python-configuration` |
| **QA / TDD** | Tests, casos C-01..C-19 | `python-testing-patterns` |
| **Orquestación** | OPSX / SDD / docs | `openspec-*`, `kb-creator`, `roadmap-generator`, `skill-registry` |

Cargá la skill correspondiente al contexto ANTES de escribir código. `database-migration` trae ejemplos de Sequelize/TypeORM/Prisma: traducirlos a Alembic.

> Los compact rules de cada skill los resuelve el orquestador desde `.atl/skill-registry.md` (generado por `skill-registry`; no versionado — no está en el repo). Esta tabla solo mapea skill→rol.

---

## Roadmap de Changes

El plan de implementación completo está en [CHANGES.md](CHANGES.md). Resumen:

- **Total**: 12 changes (C-01 a C-12) en 5 fases.
- **Camino crítico** (8): `C-01 → C-02 → C-03 → C-05 → C-07/C-08 → C-09 → C-10 → C-12`.
- **Paralelismo**: C-03 ∥ C-04 tras C-02; tras C-05 se abren C-06, C-07, C-08 y C-11.
- **Primer change**: `C-01` (`foundation-setup`).

**Antes de cualquier `/opsx:propose`**: leé [CHANGES.md](CHANGES.md), identificá las dependencias del change y los archivos de "Leer antes".

---

## Reglas Duras

> Reglas **globales** ya definidas en `~/.claude/CLAUDE.md` (orquestador, governance, TDD, engram): el proyecto las **hereda**. Acá viven solo las reglas **específicas de este proyecto** + las universales que el global no cubra (commits/build). Son contrato; romperlas es un defecto.

**Arquitectura y código**

- NUNCA `commit()` en un repositorio, ni un servicio que construya su Unit of Work, ni un UoW que cierre la sesión → los repositorios hacen `flush()`; el router construye el UoW (dependencia) y el servicio lo abre con `async with`.
- NUNCA una llamada bloqueante en un handler → todo `async def`; bcrypt siempre con `to_thread` bajo un semáforo, y el hash se calcula antes de abrir la transacción.
- NUNCA secretos ni valores por defecto en código, `alembic.ini` o repo, ni carga perezosa (lazy loading) → clave de firma JWT y contraseña de la base solo desde el entorno (sin default: si faltan, la app no arranca); toda relación que se lee se precarga en el repositorio.
- NUNCA SQL armado por concatenación, `float` para dinero ni schema de entrada sin `extra="forbid"` → parámetros ligados, `NUMERIC`/`Decimal`, contratos separados de los modelos de tabla.

**Proceso**

- NUNCA correr build, commit ni push sin que el usuario lo pida explícitamente.
- Commits en formato **conventional commits** (`feat:`, `fix:`, `chore:`, ...).
- NUNCA quitar ni renombrar tablas o columnas indicadas en la KB (los casos de prueba y la corrección las usan) → leer `knowledge-base/04_modelo_de_datos.md` antes de tocar modelos o migraciones.
- NUNCA mockear la base en tests de integración → usar PostgreSQL real (contenedor); complementa el TDD global.

---

## Flujo de Trabajo

```
1. Leer la KB relevante (knowledge-base/)        → entender el dominio
2. Identificar el change en CHANGES.md           → respetar dependencias
3. /opsx:propose C-NN-nombre                     → proposal + design + specs + tasks
4. Implementar las tasks (cargando skills)       → respetando las reglas duras
5. /opsx:archive C-NN-nombre + marcar [x]        → cerrar el change
```

Aplicar TODAS las reglas duras en cada paso. Ante conflicto entre la KB y este archivo, las reglas duras prevalecen.
