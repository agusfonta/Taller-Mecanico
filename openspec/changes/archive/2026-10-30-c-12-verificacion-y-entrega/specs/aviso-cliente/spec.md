# Spec Delta

## ADDED Requirements

### Requirement: Aviso visible en la consola del servidor
Al ejecutar la aplicación con `uvicorn main:app`, las líneas de log de nivel INFO de los módulos de la aplicación, incluida la del aviso al cliente, MUST mostrarse en la consola del servidor sin configuración adicional del usuario. La configuración MUST NOT duplicar líneas, MUST NOT bajar el nivel de los loggers de terceros (el registro de SQL sigue gobernado sólo por `SQL_ECHO`) y MUST NOT alterar el formato del texto del aviso ni el momento en que se emite.

#### Scenario: Aviso en consola tras terminar
- **WHEN** con el servidor corriendo se termina con éxito la orden 2 (caso C-12)
- **THEN** la consola del servidor muestra una única línea con `Aviso a cliente 2: orden 2 terminada` (Jorge, dueño del vehículo de la orden 2 en el seed), posterior a la línea de acceso de la respuesta 200

#### Scenario: Sin ruido de terceros
- **WHEN** el servidor corre con `SQL_ECHO=false`
- **THEN** la consola no muestra sentencias SQL

#### Scenario: Arranque repetido sin duplicados
- **WHEN** la configuración de logging se aplica más de una vez en el mismo proceso (por ejemplo, al crear la app en varios tests)
- **THEN** cada línea del aviso aparece una sola vez
