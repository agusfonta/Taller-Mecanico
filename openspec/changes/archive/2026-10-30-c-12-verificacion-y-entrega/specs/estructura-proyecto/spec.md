# Spec Delta

## MODIFIED Requirements

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
