"""``test/solo_agregado.sql`` (caso C-14) probado sentencia por sentencia sobre un esquema migrado + seed (C-12, D4)."""
import re
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from test.integration.app_completa import app_auth, contrasenas_seed, fabrica_seed, seed_cargado, sesion_de  # noqa: F401

pytestmark = pytest.mark.integration

ARCHIVO = Path(__file__).resolve().parents[1] / "solo_agregado.sql"
TABLAS_DE_SOLO_AGREGADO = ("historial_estado_orden", "movimiento_stock", "historial_precio_repuesto")
ERROR_DISPARADOR = "P0001"
ERROR_FK = "23503"


def sentencias_de(contenido: str) -> list[str]:
    """Sentencias ejecutables del archivo: sin comentarios (``--``) y sin los ``SELECT`` de conteo."""
    sin_comentarios = "\n".join(re.sub(r"--.*$", "", linea) for linea in contenido.splitlines())
    partes = [p.strip() for p in sin_comentarios.split(";")]
    return [p for p in partes if p and not p.upper().startswith("SELECT")]


def test_el_analizador_ignora_comentarios_y_selects():
    contenido = "-- uno; dos\nUPDATE t SET a = 1; -- Esperado: ERROR\nSELECT count(*) FROM t;\n\nDELETE FROM t WHERE id = 1;\n"

    assert sentencias_de(contenido) == ["UPDATE t SET a = 1", "DELETE FROM t WHERE id = 1"]


def test_el_archivo_no_usa_transaccion_ni_corta_en_el_primer_error():
    contenido = ARCHIVO.read_text(encoding="utf-8")

    sin_comentarios = re.sub(r"--.*$", "", contenido, flags=re.M).upper()
    assert not re.search(r"\b(BEGIN|COMMIT|START TRANSACTION)\b", sin_comentarios)
    assert "\\set ON_ERROR_STOP" not in contenido


def test_la_cabecera_documenta_el_comando_y_la_precondicion():
    contenido = ARCHIVO.read_text(encoding="utf-8")

    assert "docker compose exec -T postgres psql" in contenido
    assert "python seed.py" in contenido


def test_cada_sentencia_declara_su_resultado_esperado():
    contenido = ARCHIVO.read_text(encoding="utf-8")

    assert len(re.findall(r"^-- Esperado: ERROR", contenido, flags=re.M)) == len(sentencias_de(contenido)) == 7


async def _contar(conexion) -> dict[str, int]:
    conteos = {}
    for tabla in (*TABLAS_DE_SOLO_AGREGADO, "orden_trabajo"):
        conteos[tabla] = (await conexion.execute(text(f"SELECT count(*) FROM {tabla}"))).scalar_one()  # noqa: S608
    return conteos


async def test_las_siete_sentencias_fallan_como_se_espera_y_los_conteos_no_cambian(seed_cargado, motor_auth):
    sentencias = sentencias_de(ARCHIVO.read_text(encoding="utf-8"))
    errores = []

    async with motor_auth.connect() as conexion:
        antes = await _contar(conexion)
        for sentencia in sentencias:
            try:
                async with conexion.begin_nested():
                    await conexion.execute(text(sentencia))
            except DBAPIError as exc:
                errores.append((sentencia, exc.orig.sqlstate, str(exc.orig)))
            else:
                errores.append((sentencia, None, ""))
        despues = await _contar(conexion)

    assert [e[1] for e in errores] == [ERROR_DISPARADOR] * 6 + [ERROR_FK]
    disparados = [e for e in errores if e[1] == ERROR_DISPARADOR]
    for tabla in TABLAS_DE_SOLO_AGREGADO:
        for operacion in ("UPDATE", "DELETE"):
            assert any(tabla in msg and operacion in msg for _, _, msg in disparados), (tabla, operacion)
    assert "orden_trabajo" in errores[6][0] and "INSERT" in errores[6][0].upper()
    assert antes == despues
