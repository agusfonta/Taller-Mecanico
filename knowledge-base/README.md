# Taller Mecánico — Base de Conocimiento

Base de conocimiento generada a partir de `TP_Cap1a6_Consigna.pdf` (22 páginas, leídas como imagen, incluida la Figura 1 — diagrama de clases). API de órdenes de trabajo, stock y acceso con FastAPI y PostgreSQL (Programación III, UTN).

## Índice de Archivos

| Archivo | Contenido |
|---|---|
| [01_vision_y_objetivos.md](01_vision_y_objetivos.md) | Propósito, objetivos por actor y de aprendizaje, alcance, fuera de alcance, criterios de éxito |
| [02_descripcion_general.md](02_descripcion_general.md) | Stack, arquitectura en capas, módulos, integraciones, resumen de API |
| [03_actores_y_roles.md](03_actores_y_roles.md) | Actores, modelo de roles con vigencia, matriz RBAC, rutas públicas |
| [04_modelo_de_datos.md](04_modelo_de_datos.md) | 13 tablas, restricciones, ERD, migraciones, seed data |
| [05_reglas_de_negocio.md](05_reglas_de_negocio.md) | RN-01 a RN-20, requisitos no funcionales, reglas de contrato |
| [06_funcionalidades.md](06_funcionalidades.md) | Tabla completa de endpoints (roles y códigos) + historias de usuario por épica |
| [07_flujos_principales.md](07_flujos_principales.md) | Registro, login, autorización, orden de trabajo, terminar orden, lifespan |
| [08_arquitectura_propuesta.md](08_arquitectura_propuesta.md) | Patrones, estructura obligatoria de directorios, seguridad, variables de entorno |
| [09_decisiones_y_supuestos.md](09_decisiones_y_supuestos.md) | Decisiones DD-01..12 y supuestos SU-01..09 |
| [10_preguntas_abiertas.md](10_preguntas_abiertas.md) | Inconsistencias y preguntas priorizadas |
| [11_casos_de_prueba_y_evaluacion.md](11_casos_de_prueba_y_evaluacion.md) | Casos C-01..C-19, puntajes, evidencias de entrega |

## Quick Start para Desarrolladores

1. Entender el dominio → [01](01_vision_y_objetivos.md), [03](03_actores_y_roles.md)
2. Entender los datos → [04](04_modelo_de_datos.md)
3. Entender las reglas → [05](05_reglas_de_negocio.md)
4. Entender la arquitectura → [02](02_descripcion_general.md), [08](08_arquitectura_propuesta.md)
5. Implementar → [07](07_flujos_principales.md), [06](06_funcionalidades.md)
6. Verificar → [11](11_casos_de_prueba_y_evaluacion.md)
7. Antes de codificar → [10](10_preguntas_abiertas.md)

## Resumen Ejecutivo

API asincrónica en capas (Router → Service → UoW → Repository → Model) para un taller mecánico con cuatro roles (ADMIN, RECEPCION, MECANICO, CLIENTE) asignados con vigencia y consultados en la base en cada petición. Las órdenes de trabajo descuentan stock al terminarse en una sola transacción; historiales de estado, stock y precio son de sólo agregado (disparador); la autenticación usa bcrypt fuera del bucle y JWT en cookie HttpOnly. Fuera de alcance: concurrencia (cap. 7) y colas Redis (cap. 8).
