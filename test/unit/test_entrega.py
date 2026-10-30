"""Artefactos de entrega (C-12): archivos ``.http`` por caso, README y matriz de trazabilidad. Estatico, sin base."""
import re
from pathlib import Path

import pytest

import seed
from test.integration.http_casos import parsear

pytestmark = pytest.mark.unit

RAIZ = Path(__file__).resolve().parents[2]
DIRECTORIO_TEST = RAIZ / "test"
CASOS_HTTP = [f"C-{n:02d}" for n in range(1, 20) if n != 14]
RE_ARCHIVO_CASO = re.compile(r"^c(\d{2})_[a-z0-9_]+\.http$")
RE_CLAVE_EN_CUERPO = re.compile(r'"(password\w*)"\s*:\s*("[^"]*"|[^,}\s]+)')
RE_CLAVE_PROMPT = re.compile(r"^\{\{clave_\w+\}\}$")
RE_JWT = re.compile(r"[\w-]+\.[\w-]+\.[\w-]+")


def _archivos_http() -> list[Path]:
    return sorted(DIRECTORIO_TEST.glob("*.http"))


def _por_caso() -> dict[str, list[Path]]:
    encontrados: dict[str, list[Path]] = {}
    for ruta in _archivos_http():
        coincide = RE_ARCHIVO_CASO.match(ruta.name)
        assert coincide, f"nombre fuera del formato cNN_tema.http: {ruta.name}"
        encontrados.setdefault(f"C-{coincide.group(1)}", []).append(ruta)
    return encontrados


def test_hay_exactamente_un_http_por_caso_salvo_c14():
    por_caso = _por_caso()

    assert sorted(por_caso) == CASOS_HTTP
    assert all(len(rutas) == 1 for rutas in por_caso.values())


@pytest.mark.parametrize("archivo", _archivos_http(), ids=lambda p: p.stem)
def test_cada_pedido_declara_el_codigo_esperado_y_el_archivo_se_parsea(archivo):
    doc = parsear(archivo.read_text(encoding="utf-8"))

    assert doc.pedidos, "el archivo no tiene pedidos"
    sin_esperado = [p.titulo for p in doc.pedidos if p.esperado is None]
    assert sin_esperado == []


@pytest.mark.parametrize("archivo", _archivos_http(), ids=lambda p: p.stem)
def test_el_archivo_documenta_el_caso_y_la_precondicion_del_seed(archivo):
    cabecera = archivo.read_text(encoding="utf-8").split("###", 1)[0]
    numero = RE_ARCHIVO_CASO.match(archivo.name).group(1)

    assert f"C-{numero}" in cabecera
    assert "python seed.py" in cabecera
    assert "@base = http://localhost:8000" in cabecera


@pytest.mark.parametrize("archivo", _archivos_http(), ids=lambda p: p.stem)
def test_ninguna_contrasena_ni_cookie_ni_token_esta_escrito_en_el_http(archivo):
    texto = archivo.read_text(encoding="utf-8")
    doc = parsear(texto)

    for pedido in doc.pedidos:
        for campo, valor in RE_CLAVE_EN_CUERPO.findall(pedido.cuerpo or ""):
            assert RE_CLAVE_PROMPT.match(valor.strip('"')), (archivo.name, campo, valor)
        declaradas = {nombre for nombre, _ in pedido.prompts}
        for referencia in re.findall(r"\{\{(clave_\w+)\}\}", (pedido.cuerpo or "") + pedido.url):
            assert referencia in declaradas, (archivo.name, pedido.titulo, referencia)
        for nombre, valor in pedido.cabeceras:
            assert not re.search(r"access_token\s*=\s*[^{\s;]", valor), (archivo.name, nombre)
            if nombre.lower() == "authorization":
                assert not RE_JWT.search(valor), (archivo.name, "Authorization con un JWT literal")
    assert not any(clave in texto for clave in seed.CONTRASENAS_SEED.values())


@pytest.mark.parametrize("archivo", _archivos_http(), ids=lambda p: p.stem)
def test_cada_clave_de_prompt_sigue_la_convencion_de_nombres(archivo):
    doc = parsear(archivo.read_text(encoding="utf-8"))
    usuarios = {correo.split("@")[0] for correo in seed.CONTRASENAS_SEED}
    conocidas = {f"clave_{u}" for u in usuarios} | {"clave_elegida", "clave_incorrecta"}

    for pedido in doc.pedidos:
        for variable, descripcion in pedido.prompts:
            assert variable in conocidas, (archivo.name, variable)
            assert descripcion, (archivo.name, variable, "el prompt necesita una descripcion")


# --- README (spec entrega: "README con los pasos desde cero") -------------------------------------------------

README = RAIZ / "README.md"
PASOS_DEL_README = [
    "venv",
    "pip install -r requirements.txt",
    ".env",
    "secrets.token_urlsafe",
    "docker compose up -d",
    "alembic upgrade head",
    "python seed.py",
    "uvicorn main:app",
]


def _texto_readme() -> str:
    return README.read_text(encoding="utf-8")


def test_el_readme_lista_los_pasos_en_orden():
    texto = _texto_readme()
    posiciones = []
    cursor = 0
    for paso in PASOS_DEL_README:
        posicion = texto.find(paso, cursor)
        assert posicion >= 0, f"falta el paso o esta desordenado: {paso}"
        posiciones.append(posicion)
        cursor = posicion
    assert posiciones == sorted(posiciones)


@pytest.mark.parametrize(
    "frase",
    [
        "requirements-dev.txt",
        "env.example",
        "POSTGRES_PASSWORD",
        "POSTGRES_PORT",
        "docs/verificacion.md",
        "docs/evidencias/",
        "REST Client",
        "@prompt",
        "test/solo_agregado.sql",
        "pytest --exigir-db",
        "CONTRASENAS_SEED",
        "/health/ready",
    ],
)
def test_el_readme_menciona(frase):
    assert frase in _texto_readme()


def test_el_readme_advierte_que_el_seed_borra_y_que_env_no_se_versiona():
    texto = _texto_readme().lower()

    assert "borra" in texto
    assert "no se versiona" in texto


def test_el_readme_no_contiene_contrasenas_del_seed_y_nombra_donde_estan():
    texto = _texto_readme()

    assert not any(clave in texto for clave in seed.CONTRASENAS_SEED.values())
    assert "CONTRASENAS_SEED" in texto and "seed.py" in texto


# --- Matriz de trazabilidad (docs/verificacion.md) -------------------------------------------------------------

MATRIZ = RAIZ / "docs" / "verificacion.md"
CASOS_MATRIZ = [f"C-{n:02d}" for n in range(1, 20)]
RE_FILA_CASO = re.compile(r"^\|\s*(C-\d{2})\s*\|(.*)\|\s*$", re.MULTILINE)
RE_REFERENCIA_TEST = re.compile(r"`(test/[\w/]+\.py)::(\w+)`")
RE_ARCHIVO_MANUAL = re.compile(r"`(test/[\w]+\.(?:http|sql))`")


def _filas_de_matriz() -> dict[str, list[str]]:
    texto = MATRIZ.read_text(encoding="utf-8")
    return {caso: [c.strip() for c in resto.split("|")] for caso, resto in RE_FILA_CASO.findall(texto)}


def test_la_matriz_tiene_una_fila_por_cada_caso_y_ninguna_celda_vacia():
    filas = _filas_de_matriz()

    assert sorted(filas) == CASOS_MATRIZ
    for caso, celdas in filas.items():
        assert len(celdas) == 4, (caso, "columnas: artefacto, tests, resultado observado, estado")
        assert all(celdas), (caso, "hay una celda vacia")


@pytest.mark.parametrize("caso", CASOS_MATRIZ)
def test_cada_fila_apunta_a_un_artefacto_manual_y_a_tests_que_existen(caso):
    artefacto, tests, _, _ = _filas_de_matriz()[caso]

    manuales = RE_ARCHIVO_MANUAL.findall(artefacto)
    assert manuales, (caso, "sin artefacto manual")
    for ruta in manuales:
        assert (RAIZ / ruta).is_file(), (caso, ruta)
    referencias = RE_REFERENCIA_TEST.findall(tests)
    assert referencias, (caso, "al menos un test automatico")
    for archivo, funcion in referencias:
        assert (RAIZ / archivo).is_file(), (caso, archivo)
        assert f"def {funcion}" in (RAIZ / archivo).read_text(encoding="utf-8"), (caso, funcion)


def test_ningun_caso_figura_aprobado_con_un_resultado_que_dice_fallo():
    for caso, (_, _, observado, estado) in _filas_de_matriz().items():
        if "fall" in observado.lower() or "difiere" in observado.lower():
            assert "aprobado" not in estado.lower(), caso
