# aviso-cliente Specification

## Purpose

Simula el aviso al cliente cuando su orden queda terminada: se agenda en segundo plano, corre después de enviar la respuesta y sólo si la terminación se confirmó, dejando una línea de log con formato estable (DD-10, DD-21, caso C-12).

## Requirements


### Requirement: Aviso sólo tras una terminación confirmada
Cuando `POST /ordenes/{id}/terminar` confirma la transacción, el sistema MUST agendar exactamente un aviso al cliente dueño del vehículo de la orden. El aviso MUST NOT agendarse si la terminación respondió 403, 404 o 409 (incluido stock insuficiente) ni si la confirmación falló. Las transiciones `iniciar` y `cancelar` MUST NOT agendar avisos.

#### Scenario: Terminación exitosa
- **WHEN** el mecánico asignado termina una orden con stock suficiente
- **THEN** la respuesta es 200 y queda registrado exactamente un aviso para el cliente del vehículo y esa orden

#### Scenario: Terminación con stock insuficiente
- **WHEN** la terminación responde 409 por stock insuficiente (caso C-11)
- **THEN** no se registra ningún aviso

#### Scenario: Cancelar no avisa
- **WHEN** el dueño cancela su orden PENDIENTE
- **THEN** la respuesta es 200 y no se registra ningún aviso

### Requirement: Aviso en segundo plano después de la respuesta
El aviso MUST ejecutarse en segundo plano dentro del mismo proceso, después de enviar la respuesta de `terminar`: la respuesta MUST NOT esperar al aviso. El aviso MUST simular la demora de un envío con una espera asincrónica de 0,5 segundos (sin bloquear el bucle de eventos) y luego escribir una línea de log de nivel INFO con el texto `Aviso a cliente {cliente_id}: orden {orden_id} terminada`. Un aviso que falla MUST NOT alterar la orden ya confirmada. Se acepta que el aviso se pierda si el proceso se reinicia (sin reintentos).

#### Scenario: Formato del aviso
- **WHEN** se termina la orden 2 cuyo vehículo es del cliente 5
- **THEN** el log contiene exactamente una línea INFO `Aviso a cliente 5: orden 2 terminada`

#### Scenario: La respuesta no espera al aviso
- **WHEN** se termina una orden con éxito
- **THEN** la respuesta 200 se arma sin haber ejecutado la espera de 0,5 segundos ni la línea de log, que se ejecutan como tarea en segundo plano asociada a la respuesta

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
