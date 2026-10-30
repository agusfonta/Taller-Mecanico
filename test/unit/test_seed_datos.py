"""Coherencia de los datos constantes de ``seed.py`` (C-11, 2.1 y 2.2; sin base de datos).

Las contraseñas del seed viven SOLO en ``seed.py``: aqui se importan, nunca se copian.
"""
import dataclasses
from decimal import Decimal

import pytest

import seed
from app.modules.clientes.schemas import normalizar_patente
from app.modules.ordenes.models import EstadoOrdenCodigo
from app.modules.usuarios.models import Rol

EMAILS_Y_ROLES = (
    ("admin@example.com", Rol.ADMIN),
    ("admin2@example.com", Rol.ADMIN),
    ("recepcion@example.com", Rol.RECEPCION),
    ("mecanico@example.com", Rol.MECANICO),
    ("mecanico2@example.com", Rol.MECANICO),
    ("cliente@example.com", Rol.CLIENTE),
    ("nuevo@example.com", Rol.MECANICO),
)


# --- 2.1 estados, usuarios y contraseñas ---------------------------------------------------


def test_estados_son_cuatro_con_posiciones_consecutivas_y_finales_correctos():
    assert [(e.codigo, e.posicion, e.es_final) for e in seed.ESTADOS] == [
        (EstadoOrdenCodigo.PENDIENTE, 1, False),
        (EstadoOrdenCodigo.EN_REPARACION, 2, False),
        (EstadoOrdenCodigo.TERMINADA, 3, True),
        (EstadoOrdenCodigo.CANCELADA, 4, True),
    ]


def test_estados_tienen_descripcion_no_vacia_y_distinta():
    descripciones = [e.descripcion for e in seed.ESTADOS]
    assert all(d.strip() for d in descripciones)
    assert len(set(descripciones)) == 4


def test_usuarios_tienen_los_emails_y_roles_de_la_spec_en_orden():
    assert [(u.email, u.rol) for u in seed.USUARIOS] == list(EMAILS_Y_ROLES)


def test_solo_nuevo_debe_cambiar_la_contrasena():
    con_cambio = [u.email for u in seed.USUARIOS if u.debe_cambiar_password]
    assert con_cambio == ["nuevo@example.com"]


def test_usuarios_tienen_nombre_y_emails_unicos():
    assert all(u.nombre.strip() for u in seed.USUARIOS)
    emails = [u.email for u in seed.USUARIOS]
    assert len(set(emails)) == len(emails) == 7


def test_hay_una_contrasena_por_usuario_y_ninguna_de_mas():
    assert set(seed.CONTRASENAS_SEED) == {u.email for u in seed.USUARIOS}


def test_contrasenas_son_distintas_entre_usuarios():
    valores = list(seed.CONTRASENAS_SEED.values())
    assert len(set(valores)) == len(valores) == 7


@pytest.mark.parametrize("email", [email for email, _ in EMAILS_Y_ROLES])
def test_contrasena_cumple_el_contrato_de_bcrypt(email):
    contrasena = seed.CONTRASENAS_SEED[email]
    assert len(contrasena) >= 8
    assert len(contrasena.encode("utf-8")) <= 72
    assert "\x00" not in contrasena


# --- 2.2 clientes, vehiculos, repuestos, precios y ordenes ---------------------------------


def test_laura_tiene_usuario_cliente_y_dos_vehiculos_y_jorge_ninguno_y_uno():
    laura, jorge = seed.CLIENTES
    assert (laura.nombre, laura.usuario_email, len(laura.vehiculos)) == ("Laura", "cliente@example.com", 2)
    assert (jorge.nombre, jorge.usuario_email, len(jorge.vehiculos)) == ("Jorge", None, 1)


def test_documentos_de_clientes_son_unicos_y_no_vacios():
    documentos = [c.documento for c in seed.CLIENTES]
    assert all(d.strip() for d in documentos)
    assert len(set(documentos)) == len(documentos)


def test_el_usuario_de_un_cliente_existe_entre_los_usuarios():
    emails = {u.email for u in seed.USUARIOS}
    assert all(c.usuario_email in emails for c in seed.CLIENTES if c.usuario_email)


def _vehiculos():
    return [v for c in seed.CLIENTES for v in c.vehiculos]


def test_patentes_son_unicas_y_ya_estan_normalizadas():
    patentes = [v.patente for v in _vehiculos()]
    assert len(patentes) == len(set(patentes)) == 3
    assert all(normalizar_patente(p) == p for p in patentes)


def test_normalizar_patente_cambiaria_una_patente_mal_escrita():
    # Dos casos para el mismo comportamiento: la comprobacion anterior no es una tautologia.
    assert normalizar_patente("ab-123 cd") == "AB123CD"
    assert normalizar_patente("AB123CD") == "AB123CD"


def test_anios_de_vehiculos_estan_en_el_rango_de_la_restriccion():
    assert all(1950 <= v.anio <= 2100 for v in _vehiculos())


def test_repuestos_en_orden_con_stock_inicial():
    assert [(r.codigo, r.stock_inicial) for r in seed.REPUESTOS] == [
        ("FIL-001", 10),
        ("FRE-010", 4),
        ("BUJ-001", 2),
        ("ACE-530", 20),
    ]


def test_precios_son_decimal_positivos_y_el_filtro_vale_8500():
    assert all(isinstance(r.precio, Decimal) and r.precio > 0 for r in seed.REPUESTOS)
    assert seed.REPUESTOS[0].precio == Decimal("8500.00")


def test_solo_las_pastillas_de_freno_contienen_freno():
    con_freno = [r.codigo for r in seed.REPUESTOS if "freno" in r.descripcion.lower()]
    assert con_freno == ["FRE-010"]


def test_historial_de_precio_es_una_sola_linea_del_filtro_de_8000_a_8500():
    assert [(p.codigo, p.precio_anterior, p.precio_nuevo) for p in seed.HISTORIAL_PRECIOS] == [
        ("FIL-001", Decimal("8000.00"), Decimal("8500.00"))
    ]
    assert seed.HISTORIAL_PRECIOS[0].precio_nuevo == seed.REPUESTOS[0].precio


def test_ordenes_segun_el_diseno():
    uno, dos = seed.ORDENES
    assert (uno.vehiculo_id, uno.estado, uno.mecanico_email) == (1, "PENDIENTE", None)
    assert [(i.codigo, i.cantidad) for i in uno.items] == [("FIL-001", 1), ("ACE-530", 4)]
    assert [(t.desde, t.hasta, t.email) for t in uno.historial] == [
        (None, "PENDIENTE", "recepcion@example.com")
    ]
    assert (dos.vehiculo_id, dos.estado, dos.mecanico_email) == (3, "EN_REPARACION", "mecanico@example.com")
    assert [(i.codigo, i.cantidad) for i in dos.items] == [("FIL-001", 1), ("BUJ-001", 4)]
    assert [(t.desde, t.hasta, t.email) for t in dos.historial] == [
        (None, "PENDIENTE", "recepcion@example.com"),
        ("PENDIENTE", "EN_REPARACION", "mecanico@example.com"),
    ]


def test_totales_son_la_suma_exacta_de_cantidad_por_precio():
    precios = {r.codigo: r.precio for r in seed.REPUESTOS}
    for orden in seed.ORDENES:
        esperado = sum((precios[i.codigo] * i.cantidad for i in orden.items), Decimal("0"))
        assert seed.calcular_total(orden) == esperado
    assert [seed.calcular_total(o) for o in seed.ORDENES] == [Decimal("32500.00"), Decimal("20500.00")]


def test_la_orden_2_pide_mas_bujias_de_las_que_hay():
    stock = {r.codigo: r.stock_inicial for r in seed.REPUESTOS}
    pedidas = {i.codigo: i.cantidad for i in seed.ORDENES[1].items}
    assert pedidas["BUJ-001"] == 4 > stock["BUJ-001"] == 2
    assert pedidas["FIL-001"] <= stock["FIL-001"]


def test_el_filtro_precede_a_la_bujia_por_id_para_que_terminar_descuente_primero_el_filtro():
    codigos = [r.codigo for r in seed.REPUESTOS]
    assert codigos.index("FIL-001") < codigos.index("BUJ-001")


def test_los_codigos_de_repuesto_son_unicos():
    codigos = [r.codigo for r in seed.REPUESTOS]
    assert len(set(codigos)) == len(codigos)


def test_el_evento_de_seguridad_es_el_del_sistema():
    assert (seed.ACTOR_EVENTO, seed.ACCION_EVENTO) == ("SISTEMA", "Carga de los datos iniciales")


def _recorrer(valor):
    if dataclasses.is_dataclass(valor) and not isinstance(valor, type):
        for campo in dataclasses.fields(valor):
            yield from _recorrer(getattr(valor, campo.name))
    elif isinstance(valor, dict):
        for k, v in valor.items():
            yield from _recorrer(k)
            yield from _recorrer(v)
    elif isinstance(valor, (tuple, list)):
        for elemento in valor:
            yield from _recorrer(elemento)
    else:
        yield valor


def test_ningun_dato_del_seed_es_float():
    conjuntos = (seed.ESTADOS, seed.USUARIOS, seed.CLIENTES, seed.REPUESTOS, seed.HISTORIAL_PRECIOS, seed.ORDENES)
    hojas = [h for conjunto in conjuntos for h in _recorrer(conjunto)]
    assert hojas  # el recorrido encuentra datos
    assert not [h for h in hojas if isinstance(h, float)]


def test_el_recorrido_detectaria_un_float():
    @dataclasses.dataclass(frozen=True)
    class Malo:
        precio: float

    assert [h for h in _recorrer((Malo(1.5),)) if isinstance(h, float)] == [1.5]
