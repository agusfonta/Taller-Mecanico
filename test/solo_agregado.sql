-- Caso C-14: las tablas de solo agregado rechazan UPDATE y DELETE (RN-15) y el estado de una orden
-- debe existir en el catalogo (FK).
--
-- Precondicion: base migrada (`alembic upgrade head`) y sembrada (`python seed.py`), para que existan
-- las filas con id = 1 de las tres tablas y el vehiculo 1.
--
-- Uso (psql en el contenedor, sin pedir contrasena; reemplazar <usuario> y <base> por los de tu .env):
--   docker compose exec -T postgres psql -U <usuario> -d <base> < test/solo_agregado.sql
--
-- Sin BEGIN: psql corre cada sentencia en autocommit y SIGUE despues de un error (no se usa
-- ON_ERROR_STOP). Se esperan 7 errores y ningun cambio en los conteos finales.

-- 1) historial_estado_orden: UPDATE
-- Esperado: ERROR  La tabla historial_estado_orden es de solo agregado: UPDATE no permitido
UPDATE historial_estado_orden SET hasta_estado = 'OTRO' WHERE id = 1;

-- 2) historial_estado_orden: DELETE
-- Esperado: ERROR  La tabla historial_estado_orden es de solo agregado: DELETE no permitido
DELETE FROM historial_estado_orden WHERE id = 1;

-- 3) movimiento_stock: UPDATE
-- Esperado: ERROR  La tabla movimiento_stock es de solo agregado: UPDATE no permitido
UPDATE movimiento_stock SET cantidad = cantidad + 1 WHERE id = 1;

-- 4) movimiento_stock: DELETE
-- Esperado: ERROR  La tabla movimiento_stock es de solo agregado: DELETE no permitido
DELETE FROM movimiento_stock WHERE id = 1;

-- 5) historial_precio_repuesto: UPDATE
-- Esperado: ERROR  La tabla historial_precio_repuesto es de solo agregado: UPDATE no permitido
UPDATE historial_precio_repuesto SET precio_nuevo = precio_nuevo + 1 WHERE id = 1;

-- 6) historial_precio_repuesto: DELETE
-- Esperado: ERROR  La tabla historial_precio_repuesto es de solo agregado: DELETE no permitido
DELETE FROM historial_precio_repuesto WHERE id = 1;

-- 7) orden_trabajo con un estado que no esta en el catalogo
-- Esperado: ERROR  viola la llave foranea "fk_orden_trabajo_estado_estado_orden" (23503)
INSERT INTO orden_trabajo (vehiculo_id, estado, falla) VALUES (1, 'INEXISTENTE', 'C-14');

-- Conteos finales: deben ser iguales a los del seed (3, 4, 1 y 2 filas).
SELECT 'historial_estado_orden' AS tabla, count(*) FROM historial_estado_orden
UNION ALL SELECT 'movimiento_stock', count(*) FROM movimiento_stock
UNION ALL SELECT 'historial_precio_repuesto', count(*) FROM historial_precio_repuesto
UNION ALL SELECT 'orden_trabajo', count(*) FROM orden_trabajo;
