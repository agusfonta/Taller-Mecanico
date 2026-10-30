# modelo-de-datos Specification

## Purpose

Define el esquema relacional del taller (13 tablas con nombres fijos) y las garantías de integridad que la base asume por sí misma —unicidad, unicidad entre vigentes, valores válidos, estado de orden del catálogo, índices de claves foráneas— junto con la navegación entre entidades sin carga implícita.

## Requirements


### Requirement: Tablas y columnas con nombres obligatorios
El esquema SHALL contener exactamente las tablas `usuario`, `asignacion_rol`, `intento_acceso`, `evento_seguridad`, `cliente`, `vehiculo`, `repuesto`, `movimiento_stock`, `historial_precio_repuesto`, `estado_orden`, `orden_trabajo`, `item_orden` e `historial_estado_orden`, cada una con **todas** las columnas que indica la base de conocimiento y con esos mismos nombres. Se MAY agregar columnas, pero MUST NOT quitarse ni renombrarse las indicadas. `usuario` MUST NOT tener columna `rol`. Toda tabla salvo `estado_orden` SHALL tener una clave primaria `id` numérica generada por la base; `estado_orden` SHALL tener como clave primaria `codigo` (texto).

#### Scenario: Esquema completo tras migrar
- **WHEN** se aplican todas las migraciones sobre una base vacía
- **THEN** existen las 13 tablas con todas sus columnas indicadas, y ninguna otra tabla de la aplicación salvo la de control de versiones de migraciones

#### Scenario: Usuario sin columna de rol
- **WHEN** se inspeccionan las columnas de `usuario`
- **THEN** están `id`, `email`, `nombre`, `password_hash`, `activo`, `debe_cambiar_password`, `password_cambiada_en` y no existe `rol`

#### Scenario: Catálogo con clave textual
- **WHEN** se inspecciona `estado_orden`
- **THEN** su clave primaria es `codigo` de tipo texto y tiene `descripcion`, `posicion` y `es_final`

### Requirement: Tipos de fecha, dinero y obligatoriedad
Toda columna de fecha/hora MUST almacenarse con zona horaria. Toda columna de dinero (`repuesto.precio`, `item_orden.precio_unitario`, `historial_precio_repuesto.precio_anterior` y `precio_nuevo` con precisión 10,2; `orden_trabajo.total` con 12,2) MUST ser numérica exacta y MUST leerse en la aplicación como decimal exacto, nunca como coma flotante. Las columnas que la base de conocimiento no marca como "nulo permitido" MUST rechazar valores nulos.

#### Scenario: Dinero exacto ida y vuelta
- **WHEN** se guarda un repuesto con precio `8500.10` y se lo vuelve a leer
- **THEN** el valor leído es exactamente el decimal `8500.10`

#### Scenario: Fechas con zona
- **WHEN** se inspecciona el tipo de cualquier columna de fecha (`cuando`, `desde`, `vence_en`, `revocada_en`, `borrado_en`, `creada_en`, `password_cambiada_en`)
- **THEN** su tipo es fecha/hora con zona horaria

#### Scenario: Obligatoria sin valor
- **WHEN** se inserta un `vehiculo` sin `patente`
- **THEN** la base rechaza la fila

#### Scenario: Nulo permitido donde la KB lo indica
- **WHEN** se inserta una `orden_trabajo` sin `mecanico_id` o un `cliente` sin `usuario_id`
- **THEN** la base acepta la fila

### Requirement: Unicidad garantizada por la base
La base MUST rechazar: dos usuarios con el mismo `email`; dos clientes con el mismo `documento`; dos clientes vinculados al mismo `usuario_id` (relación uno a uno opcional, admitiendo varios clientes sin usuario); dos estados con la misma `posicion`; dos ítems de una misma orden con el mismo repuesto. La unicidad MUST NOT depender de una consulta previa de la aplicación.

#### Scenario: Correo repetido
- **WHEN** se insertan dos usuarios con el mismo `email`
- **THEN** la segunda inserción es rechazada por la base con una violación de unicidad

#### Scenario: Documento repetido
- **WHEN** se insertan dos clientes con el mismo `documento`
- **THEN** la segunda inserción es rechazada

#### Scenario: Un cliente por usuario
- **WHEN** se insertan dos clientes con el mismo `usuario_id` no nulo
- **THEN** la segunda inserción es rechazada; dos clientes con `usuario_id` nulo se aceptan

#### Scenario: Repuesto repetido en una orden
- **WHEN** se insertan dos ítems de la misma orden con el mismo repuesto
- **THEN** el segundo es rechazado; el mismo repuesto en otra orden se acepta

#### Scenario: Posición de catálogo repetida
- **WHEN** se insertan dos estados con la misma `posicion`
- **THEN** el segundo es rechazado

### Requirement: Unicidad entre vigentes
La base MUST rechazar dos vehículos **no dados de baja** (`borrado_en` nulo) con la misma `patente` y dos repuestos no dados de baja con el mismo `codigo`, y MUST aceptar que una fila dada de baja comparta el valor con una vigente. La base MUST rechazar dos asignaciones **abiertas** (`revocada_en` nulo) del mismo rol al mismo usuario, y MUST aceptar una asignación nueva del mismo rol cuando la anterior está revocada.

#### Scenario: Patente vigente repetida
- **WHEN** existe un vehículo vigente con patente `AB123CD` y se inserta otro vigente con la misma patente
- **THEN** la base rechaza la inserción

#### Scenario: Patente reutilizada tras la baja
- **WHEN** el vehículo con patente `AB123CD` tiene `borrado_en` no nulo y se inserta otro vigente con la misma patente
- **THEN** la base acepta la inserción

#### Scenario: Código de repuesto entre vigentes
- **WHEN** se inserta un repuesto vigente con un `codigo` que ya tiene otro repuesto vigente, y luego otro con el código de un repuesto dado de baja
- **THEN** el primero es rechazado y el segundo aceptado

#### Scenario: Asignación abierta duplicada
- **WHEN** un usuario tiene abierta la asignación `MECANICO` y se inserta otra abierta del mismo rol
- **THEN** la base rechaza la inserción; si la anterior tiene `revocada_en` no nulo, la nueva se acepta

### Requirement: Valores válidos garantizados por la base
La base MUST rechazar, con una violación de restricción de verificación identificable por tabla y regla: `asignacion_rol.rol` fuera de {ADMIN, RECEPCION, MECANICO, CLIENTE}; `vehiculo.anio` fuera de 1950–2100; `repuesto.precio <= 0`; `repuesto.stock < 0`; `orden_trabajo.total < 0`; `item_orden.cantidad <= 0`; `item_orden.precio_unitario <= 0`; `movimiento_stock.cantidad = 0`; `historial_precio_repuesto.precio_nuevo <= 0`; `historial_precio_repuesto.precio_nuevo = precio_anterior`. Los valores en el borde válido MUST aceptarse.

#### Scenario: Rol desconocido
- **WHEN** se inserta una asignación con rol `SUPERUSUARIO`
- **THEN** la base la rechaza; con rol `CLIENTE` la acepta

#### Scenario: Año en los bordes
- **WHEN** se insertan vehículos con `anio` 1949, 1950, 2100 y 2101
- **THEN** se aceptan 1950 y 2100 y se rechazan 1949 y 2101

#### Scenario: Stock negativo
- **WHEN** se actualiza un repuesto a `stock = -1`
- **THEN** la base rechaza el cambio; `stock = 0` se acepta

#### Scenario: Movimiento de cantidad cero
- **WHEN** se inserta un movimiento de stock con `cantidad = 0`
- **THEN** la base lo rechaza; con cantidades positivas o negativas lo acepta

#### Scenario: Historial de precio sin cambio
- **WHEN** se inserta una línea de historial con `precio_anterior = precio_nuevo`
- **THEN** la base la rechaza

#### Scenario: Precios y totales no válidos
- **WHEN** se inserta un repuesto con `precio = 0`, un ítem con `cantidad = 0` o `precio_unitario = 0`, o una orden con `total = -0.01`
- **THEN** cada inserción es rechazada; `total = 0` se acepta

### Requirement: Estado de orden del catálogo
`orden_trabajo.estado`, `historial_estado_orden.desde_estado` y `historial_estado_orden.hasta_estado` MUST ser claves foráneas a `estado_orden.codigo` (no una lista fija en una verificación). La base MUST rechazar una orden o una línea de historial que nombre un estado inexistente en el catálogo. `desde_estado` MAY ser nulo (primera línea del historial).

#### Scenario: Estado fuera del catálogo
- **WHEN** se inserta una orden con `estado = 'INEXISTENTE'`
- **THEN** la base la rechaza por clave foránea

#### Scenario: Estado del catálogo
- **WHEN** el catálogo tiene el estado `PENDIENTE` y se inserta una orden con ese estado
- **THEN** la base la acepta

#### Scenario: Catálogo vacío impide órdenes
- **WHEN** el catálogo está vacío y se inserta cualquier orden
- **THEN** la base la rechaza por clave foránea

### Requirement: Claves foráneas indexadas
Toda clave foránea MUST estar cubierta por un índice cuyo primer campo sea esa columna. `intento_acceso` MUST tener un índice por (`email`, `ip`, `cuando`) en ese orden. Las claves foráneas MUST NOT borrar en cascada: borrar una fila referenciada MUST rechazarse.

#### Scenario: Ninguna FK sin índice
- **WHEN** se consulta el catálogo de la base por las claves foráneas del esquema y los índices existentes
- **THEN** cada columna de clave foránea es el primer campo de al menos un índice

#### Scenario: Índice de intentos de acceso
- **WHEN** se inspeccionan los índices de `intento_acceso`
- **THEN** existe uno sobre (`email`, `ip`, `cuando`) en ese orden

#### Scenario: Borrar un padre con historial
- **WHEN** se intenta borrar un repuesto que tiene movimientos de stock
- **THEN** la base rechaza el borrado y los movimientos quedan intactos

### Requirement: Navegación en ambos extremos sin carga implícita
Cada relación del modelo (cliente–vehículos, vehículo–órdenes, orden–ítems, ítem–repuesto, orden–historial de estados, orden–estado del catálogo, orden–mecánico, usuario–asignaciones de rol, usuario–cliente, repuesto–movimientos, repuesto–historial de precios) SHALL poder recorrerse desde ambos extremos. Desde un usuario, su cliente MUST obtenerse como un único objeto (o ninguno), no como una lista. Leer una relación que no fue precargada explícitamente MUST fallar con un error en lugar de consultar la base de forma implícita; precargada, MUST devolver los datos sin consultas adicionales.

#### Scenario: Cliente del usuario es un objeto
- **WHEN** se lee un usuario precargando su cliente
- **THEN** se obtiene un único cliente (o vacío si no tiene), no una colección

#### Scenario: Relación precargada
- **WHEN** se lee un cliente precargando sus vehículos
- **THEN** se obtienen sus vehículos y, desde cada vehículo, el mismo cliente

#### Scenario: Relación no precargada
- **WHEN** se lee un cliente sin precargar sus vehículos y se accede a ellos
- **THEN** se produce un error de carga no permitida y no se emite ninguna consulta

#### Scenario: Alta de una orden con sus ítems
- **WHEN** se agrega una orden nueva con dos ítems asociados por la relación y se confirma
- **THEN** quedan persistidas la orden y sus dos ítems con su `orden_id`
