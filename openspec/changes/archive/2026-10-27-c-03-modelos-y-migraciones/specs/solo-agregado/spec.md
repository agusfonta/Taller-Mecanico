# Spec Delta — solo-agregado

## Purpose

Garantiza desde la propia base que el historial de estados de órdenes, los movimientos de stock y el historial de precios de repuestos sólo crecen: ninguna sesión, ni de la aplicación ni manual, puede modificar ni borrar sus filas (RN-15).

## ADDED Requirements

### Requirement: Modificación y borrado rechazados en tablas de sólo agregado
En `historial_estado_orden`, `movimiento_stock` e `historial_precio_repuesto`, la base MUST rechazar toda sentencia UPDATE y toda sentencia DELETE que afecte al menos una fila, con un error cuyo mensaje identifique la tabla y la operación rechazada. La fila MUST quedar intacta y la transacción que lo intentó MUST quedar en error. El rechazo MUST aplicarse a cualquier cliente de la base (aplicación, `psql`), no sólo a la aplicación.

#### Scenario: UPDATE rechazado
- **WHEN** existe una fila en `movimiento_stock` y se ejecuta un UPDATE sobre ella
- **THEN** la base rechaza la sentencia con un error que nombra `movimiento_stock` y UPDATE, y la fila conserva sus valores

#### Scenario: DELETE rechazado
- **WHEN** existe una fila en `historial_precio_repuesto` y se ejecuta un DELETE sobre ella
- **THEN** la base rechaza la sentencia con un error que nombra la tabla y DELETE, y la fila sigue existiendo

#### Scenario: Las tres tablas, las dos operaciones
- **WHEN** se intenta UPDATE y DELETE sobre una fila de cada una de las tres tablas
- **THEN** los seis intentos son rechazados

### Requirement: El agregado sigue permitido
La protección MUST NOT impedir insertar filas nuevas en las tres tablas, ni modificar o borrar filas de las demás tablas del esquema.

#### Scenario: INSERT permitido
- **WHEN** se inserta una fila válida en cada tabla de sólo agregado
- **THEN** la base acepta las tres inserciones

#### Scenario: Otras tablas no afectadas
- **WHEN** se actualiza el `stock` de un repuesto
- **THEN** la base acepta el cambio

### Requirement: Vaciado completo para datos iniciales
La protección MUST NOT impedir vaciar por completo las tablas de sólo agregado con un vaciado de tabla (no fila a fila), necesario para que el script de datos iniciales deje la base en un estado conocido. Revertir las migraciones MUST eliminar la protección.

#### Scenario: Vaciado de tabla
- **WHEN** se vacía `movimiento_stock` junto con las tablas que la referencian mediante un vaciado de tabla
- **THEN** la operación termina sin error y la tabla queda sin filas

#### Scenario: DELETE masivo sigue rechazado
- **WHEN** se ejecuta `DELETE FROM movimiento_stock` sin condiciones con filas presentes
- **THEN** la base lo rechaza
