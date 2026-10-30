# Visión y Objetivos

> Fuente: `TP_Cap1a6_Consigna.pdf` (Programación III, UTN — Tecnicatura Universitaria en Programación). Unidades 1 a 6, "Del objeto a la transacción". Las 22 páginas fueron leídas como imagen, incluido el diagrama de clases (Figura 1).

## Propósito del sistema

API REST asincrónica para el trabajo diario de un taller mecánico: órdenes de trabajo, stock de repuestos y control de acceso por roles, construida con FastAPI y PostgreSQL.

Es a la vez un **trabajo práctico evaluable**: integra lo visto en los capítulos 1 a 6 (fundamentos de FastAPI, contratos y CRUD, asincronía sin bloqueos, persistencia con migraciones, autenticación/autorización, repositorios + Unit of Work + transacciones). El dominio está elegido para que cada capítulo tenga un lugar concreto donde aparecer.

## Objetivos por actor

| Actor | Objetivo principal | Objetivos secundarios |
|---|---|---|
| Recepción | Dar de alta clientes y vehículos y abrir una orden de trabajo por cada ingreso (falla descrita por el cliente + repuestos a usar) | Cancelar órdenes; consultar repuestos |
| Mecánico | Tomar una orden, repararla y darla por terminada | Al terminar se descuenta el stock de cada repuesto usado |
| Administrador | Mantener el catálogo de repuestos, reponer stock, administrar personal y roles | Ver el historial de seguridad; terminar/cancelar órdenes |
| Cliente | Registrarse solo en la web y consultar el estado de sus vehículos y órdenes | Cancelar su propia orden pendiente |

## Objetivos de aprendizaje (lo que el proyecto debe demostrar)

1. API asincrónica en capas **Router → Service → UoW → Repository → Model**, donde cada capa sabe lo suyo y nada más.
2. Modelo con asociación, composición, uno a uno y tabla de catálogo traducido a esquema relacional versionado con Alembic, incluida una **migración escrita a mano**.
3. Autenticación con **bcrypt** y token en **cookie HttpOnly**, sin frenar el servidor y sin revelar qué cuentas existen.
4. Autorización consultando **los roles en la base en cada petición**, con vigencia, distinguiendo siempre 401 de 403.
5. Agrupar en **una sola transacción** las escrituras de una operación de negocio (sin datos a medias).
6. Delegar en la base lo que la base garantiza: unicidad, claves foráneas, checks y sólo-agregado.

## Alcance v1.0

- Gestión de usuarios/personal y roles con vigencia (alta, asignación, revocación).
- Registro de clientes (auto-registro y alta por recepción) y vehículos con borrado lógico.
- Catálogo de repuestos con borrado lógico, stock vía movimientos y historial de precios.
- Órdenes de trabajo con ítems (composición), estados por catálogo y historial de estados.
- Autenticación (registro, login, logout, `/auth/yo`, cambio obligatorio de contraseña).
- Historial de seguridad (`evento_seguridad`) y límite de intentos de login (`intento_acceso`).
- Aviso simulado al cliente al terminar una orden (`BackgroundTasks`).
- Salud: `/health/live` y `/health/ready`.

## Fuera de alcance (explícito en el PDF)

- **Concurrencia (cap. 7)**: no se evalúa. Dos órdenes que terminan a la vez pueden leer el mismo stock y producir una *actualización perdida* (el CHECK `stock >= 0` no la detecta). El bloqueo que lo evita es tema de la próxima clase.
- **Colas de tareas con Redis (cap. 8)**: el aviso al cliente usa `BackgroundTasks` en el mismo proceso. Si el proceso se reinicia el aviso se pierde y no hay reintento; se acepta porque el aviso es simulado.
- Segundo mecanismo de sólo-agregado por permisos del rol de base (sec. 6.9): no se pide; el TP usa un solo rol de base.

## Métricas de éxito (criterios de evaluación, 100 %)

| Criterio | Peso |
|---|---|
| Proyecto, configuración y ciclo de vida | 8 % |
| Modelos, relaciones y migraciones | 14 % |
| Contratos y CRUD | 10 % |
| Autenticación | 16 % |
| Autorización | 14 % |
| Repositorios y Unit of Work | 20 % |
| Integridad (sólo agregado, intento de acceso) | 10 % |
| Lecturas sin N+1 y asincronía | 8 % |

Condición de corrección: un proyecto que **no levanta**, que **no crea su esquema con `alembic upgrade head` sobre base vacía** o que **contiene credenciales reales en el repositorio** no se corrige hasta que se subsane.
