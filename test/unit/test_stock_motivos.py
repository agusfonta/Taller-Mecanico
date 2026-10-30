"""Motivos de movimiento de stock (C-10, D6-a, tarea 2.4, spec stock-repuestos)."""
import pytest

from app.modules.repuestos import stock

pytestmark = pytest.mark.unit


def test_motivo_de_terminacion_tiene_el_texto_exacto():
    assert stock.MOTIVO_ORDEN_TERMINADA == "Terminación de orden"


def test_motivo_de_terminacion_esta_exportado():
    assert "MOTIVO_ORDEN_TERMINADA" in stock.__all__


def test_los_tres_motivos_son_distintos_y_validos_para_mover_stock():
    motivos = [stock.MOTIVO_STOCK_INICIAL, stock.MOTIVO_REPOSICION, stock.MOTIVO_ORDEN_TERMINADA]
    assert len(set(motivos)) == 3
    assert all(m.strip() for m in motivos)


def test_el_motivo_de_terminacion_no_repite_el_id_de_la_orden():
    assert not any(c.isdigit() for c in stock.MOTIVO_ORDEN_TERMINADA)
