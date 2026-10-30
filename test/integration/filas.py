"""Filas validas minimas y ayudantes de violacion para los tests de integracion de C-03."""
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

async def _insertar(conexion, sql, **params):
    return (await conexion.execute(text(sql), params)).scalar_one()


async def usuario(c, email="u@example.com"):
    return await _insertar(
        c, "INSERT INTO usuario (email, nombre, password_hash) VALUES (:e, 'N', 'h') RETURNING id", e=email
    )


async def cliente(c, documento="30111222", usuario_id=None):
    return await _insertar(
        c,
        "INSERT INTO cliente (usuario_id, nombre, documento, telefono) "
        "VALUES (:u, 'Laura', :d, '555') RETURNING id",
        u=usuario_id, d=documento,
    )


async def vehiculo(c, cliente_id, patente="AB123CD", anio=2020, borrado=False):
    return await _insertar(
        c,
        "INSERT INTO vehiculo (cliente_id, patente, marca, modelo, anio, borrado_en) "
        "VALUES (:c, :p, 'M', 'X', :a, CASE WHEN :b THEN now() END) RETURNING id",
        c=cliente_id, p=patente, a=anio, b=borrado,
    )


async def repuesto(c, codigo="FIL-001", precio=Decimal("100.00"), stock=5, borrado=False):
    return await _insertar(
        c,
        "INSERT INTO repuesto (codigo, descripcion, precio, stock, borrado_en) "
        "VALUES (:c, 'D', :p, :s, CASE WHEN :b THEN now() END) RETURNING id",
        c=codigo, p=precio, s=stock, b=borrado,
    )


async def estado(c, codigo="PENDIENTE", posicion=1, es_final=False):
    await c.execute(
        text("INSERT INTO estado_orden (codigo, descripcion, posicion, es_final) VALUES (:c, 'D', :p, :f)"),
        {"c": codigo, "p": posicion, "f": es_final},
    )
    return codigo


async def orden(c, vehiculo_id, estado_="PENDIENTE", mecanico_id=None, total=Decimal("0")):
    return await _insertar(
        c,
        "INSERT INTO orden_trabajo (vehiculo_id, mecanico_id, estado, falla, total) "
        "VALUES (:v, :m, :e, 'ruido', :t) RETURNING id",
        v=vehiculo_id, m=mecanico_id, e=estado_, t=total,
    )


async def item(c, orden_id, repuesto_id, cantidad=1, precio=Decimal("10.00")):
    return await _insertar(
        c,
        "INSERT INTO item_orden (orden_id, repuesto_id, cantidad, precio_unitario) "
        "VALUES (:o, :r, :q, :p) RETURNING id",
        o=orden_id, r=repuesto_id, q=cantidad, p=precio,
    )


async def asignacion(c, usuario_id, rol="MECANICO", revocada=False):
    return await _insertar(
        c,
        "INSERT INTO asignacion_rol (usuario_id, rol, revocada_en) "
        "VALUES (:u, :r, CASE WHEN :x THEN now() END) RETURNING id",
        u=usuario_id, r=rol, x=revocada,
    )


async def movimiento(c, repuesto_id, usuario_id, cantidad=5):
    return await _insertar(
        c,
        "INSERT INTO movimiento_stock (repuesto_id, usuario_id, cantidad, motivo) "
        "VALUES (:r, :u, :q, 'Stock inicial') RETURNING id",
        r=repuesto_id, u=usuario_id, q=cantidad,
    )


async def historial_precio(c, repuesto_id, usuario_id, anterior=Decimal("8000.00"), nuevo=Decimal("8500.00")):
    return await _insertar(
        c,
        "INSERT INTO historial_precio_repuesto (repuesto_id, usuario_id, precio_anterior, precio_nuevo) "
        "VALUES (:r, :u, :a, :n) RETURNING id",
        r=repuesto_id, u=usuario_id, a=anterior, n=nuevo,
    )


async def historial_estado(c, orden_id, usuario_id, desde=None, hasta="PENDIENTE"):
    return await _insertar(
        c,
        "INSERT INTO historial_estado_orden (orden_id, desde_estado, hasta_estado, usuario_id) "
        "VALUES (:o, :d, :h, :u) RETURNING id",
        o=orden_id, d=desde, h=hasta, u=usuario_id,
    )


async def rechaza(conexion, operacion, *, restriccion=None, sqlstate=None):
    """``operacion`` (corrutina) debe fallar con IntegrityError; verifica por nombre o sqlstate."""
    with pytest.raises(IntegrityError) as exc:
        async with conexion.begin_nested():
            await operacion
    causa = exc.value.orig.__cause__
    if restriccion is not None:
        assert causa.constraint_name == restriccion
    if sqlstate is not None:
        assert exc.value.orig.sqlstate == sqlstate


async def acepta(conexion, operacion):
    async with conexion.begin_nested():
        return await operacion


