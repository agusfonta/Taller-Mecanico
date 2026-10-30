# estructura-proyecto Specification

## Purpose

Fija la estructura de directorios obligatoria del trabajo práctico, las dependencias declaradas y el comportamiento del punto de entrada de la aplicación ante una configuración incompleta.

## Requirements

### Requirement: Estructura de directorios obligatoria
El repositorio SHALL contener `main.py`, `seed.py`, `requirements.txt`, `alembic.ini`, `env.example`, `README.md`, los directorios `migrations/` y `test/`, el paquete `app/core/` y un paquete por módulo funcional en `app/modules/`: `health`, `usuarios`, `clientes`, `repuestos` y `ordenes`. El directorio `test/` SHALL contener los archivos `*.http` de los casos de prueba y `solo_agregado.sql`. El archivo `.env` MUST NOT versionarse.

#### Scenario: Estructura presente
- **WHEN** se inspecciona la raíz del repositorio
- **THEN** existen todos los archivos y directorios listados, y cada módulo de `app/modules/` es un paquete importable

#### Scenario: Módulos funcionales importables
- **WHEN** se importa cada uno de `app.modules.health`, `app.modules.usuarios`, `app.modules.clientes`, `app.modules.repuestos` y `app.modules.ordenes`
- **THEN** la importación no falla y no requiere configuración ni base de datos

#### Scenario: Artefactos de prueba en test/
- **WHEN** se inspecciona `test/`
- **THEN** contiene al menos un archivo `*.http` y el archivo `solo_agregado.sql`

#### Scenario: .env fuera del control de versiones
- **WHEN** se consulta si `.env` está ignorado por git
- **THEN** `.env` está ignorado y no figura entre los archivos versionados

### Requirement: Dependencias declaradas
`requirements.txt` SHALL declarar, con versión mínima según el stack del proyecto, FastAPI (con extras `standard`), SQLModel, SQLAlchemy (asincrónico), asyncpg, Alembic, pydantic-settings, bcrypt y PyJWT. Las dependencias sólo de tests MUST declararse aparte.

#### Scenario: Paquetes requeridos listados
- **WHEN** se inspecciona `requirements.txt`
- **THEN** cada uno de los paquetes listados aparece con una versión mínima

### Requirement: La aplicación no arranca con configuración incompleta
El punto de entrada `main.py` MUST validar la configuración al cargarse; si falta `JWT_SECRET_KEY` o `POSTGRES_PASSWORD`, el proceso SHALL terminar con error antes de aceptar peticiones, nombrando la variable faltante y sin mostrar valores secretos. Con la configuración completa, SHALL cargarse sin contactar la base de datos.

#### Scenario: Arranque sin clave de firma
- **WHEN** se carga `main.py` en un entorno sin `JWT_SECRET_KEY` y sin archivo `.env`
- **THEN** el proceso termina con código distinto de cero y el error menciona `JWT_SECRET_KEY`

#### Scenario: Arranque sin contraseña de base
- **WHEN** se carga `main.py` en un entorno sin `POSTGRES_PASSWORD` y sin archivo `.env`
- **THEN** el proceso termina con código distinto de cero y el error menciona `POSTGRES_PASSWORD`

#### Scenario: Arranque con configuración completa
- **WHEN** se carga `main.py` con ambos secretos definidos y sin una base de datos disponible
- **THEN** la carga termina con éxito y expone la aplicación
