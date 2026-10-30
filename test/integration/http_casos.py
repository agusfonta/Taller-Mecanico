"""Interprete minimo de los ``.http`` de ``test/`` (subconjunto de REST Client, C-12, D3).

Es un AYUDANTE DE TESTS, no codigo de la app. Soporta solo lo que usan los archivos ``c*.http``:

- ``@variable = valor`` y ``{{variable}}`` (los valores pueden referenciar otras variables);
- ``###`` como separador de pedidos (el texto que sigue es el titulo);
- ``# @name x`` y ``{{x.response.headers.Set-Cookie}}`` (cualquier cabecera de la respuesta ``x``);
- ``# @prompt variable descripcion``: la variable solo vale en ese pedido y su valor lo da quien llama
  (en los tests, ``seed.CONTRASENAS_SEED`` en memoria; en REST Client la pide el editor);
- ``# @no-cookie-jar``: el pedido no envia ni guarda las cookies del archivo;
- ``# Esperado: NNN``: codigo de estado esperado (el resto de la linea es informativo).

Cualquier otra sintaxis (``{{$guid}}``, ``< archivo``, ``{{x.response.body...}}``, directivas ``@``
desconocidas, metodos raros) levanta ``SintaxisNoSoportada``: un ``.http`` que usa algo que este
intérprete no entiende falla en ``pytest`` en vez de pasar sin ejecutarse.
"""
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field

import httpx

__all__ = ["Documento", "Pedido", "Resultado", "SintaxisNoSoportada", "claves_de_prompts", "ejecutar", "parsear"]

METODOS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
DIRECTIVAS = {"name", "prompt", "no-cookie-jar"}

_RE_ESPERADO = re.compile(r"^(?:#|//)\s*Esperado:\s*(\d{3})\b")
_RE_DIRECTIVA = re.compile(r"^(?:#|//)\s*@([\w-]+)\s*(.*)$")
_RE_VARIABLE = re.compile(r"^@(\w+)\s*=\s*(.*)$")
_RE_PEDIDO = re.compile(r"^([A-Z]+)\s+(\S+)(?:\s+HTTP/\d(?:\.\d)?)?\s*$")
_RE_CABECERA = re.compile(r"^([A-Za-z][\w-]*):\s*(.*)$")
_RE_REFERENCIA = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
_RE_RESPUESTA = re.compile(r"^([\w-]+)\.response\.headers\.([\w-]+)$")


class SintaxisNoSoportada(ValueError):
    """El ``.http`` usa algo que el interprete no soporta (o una variable sin valor)."""


@dataclass
class Pedido:
    titulo: str
    metodo: str
    url: str
    cabeceras: list[tuple[str, str]] = field(default_factory=list)
    cuerpo: str | None = None
    nombre: str | None = None
    prompts: list[tuple[str, str]] = field(default_factory=list)
    sin_jar: bool = False
    esperado: int | None = None


@dataclass
class Documento:
    variables: dict[str, str] = field(default_factory=dict)
    pedidos: list[Pedido] = field(default_factory=list)


@dataclass
class Resultado:
    pedido: Pedido
    codigo: int
    texto: str
    set_cookie: str | None


def _bloques(texto: str) -> list[tuple[str, list[str]]]:
    bloques: list[tuple[str, list[str]]] = [("", [])]
    for linea in texto.splitlines():
        if linea.startswith("###"):
            bloques.append((linea[3:].strip(), []))
        else:
            bloques[-1][1].append(linea)
    return bloques


def _revisar_sintaxis(linea: str, donde: str) -> None:
    if "{{$" in linea:
        raise SintaxisNoSoportada(f"{donde}: variable de sistema no soportada: {linea.strip()!r}")
    if ".response.body" in linea:
        raise SintaxisNoSoportada(f"{donde}: referencia al cuerpo de una respuesta no soportada: {linea.strip()!r}")
    if linea.startswith("<"):
        raise SintaxisNoSoportada(f"{donde}: cuerpo desde archivo no soportado: {linea.strip()!r}")


def _parsear_bloque(titulo: str, lineas: list[str], doc: Documento, numero: int) -> None:
    donde = f"pedido {numero} ({titulo or 'sin titulo'})"
    pedido: Pedido | None = None
    estado = "previo"
    cuerpo: list[str] = []
    nombre = None
    prompts: list[tuple[str, str]] = []
    sin_jar = False
    esperado = None

    for linea in lineas:
        vacia = not linea.strip()
        es_comentario = linea.lstrip().startswith(("#", "//"))
        if estado == "cuerpo":
            _revisar_sintaxis(linea, donde)
            cuerpo.append(linea)
            continue
        if vacia:
            if estado == "cabeceras":
                estado = "cuerpo"
            continue
        if es_comentario:
            directiva = _RE_DIRECTIVA.match(linea.strip())
            if directiva:
                clave, resto = directiva.group(1), directiva.group(2).strip()
                if clave not in DIRECTIVAS:
                    raise SintaxisNoSoportada(f"{donde}: directiva @{clave} no soportada")
                if clave == "name":
                    nombre = resto
                elif clave == "no-cookie-jar":
                    sin_jar = True
                else:
                    variable, _, descripcion = resto.partition(" ")
                    if not variable:
                        raise SintaxisNoSoportada(f"{donde}: @prompt sin nombre de variable (no soportado)")
                    prompts.append((variable, descripcion.strip()))
            else:
                coincide = _RE_ESPERADO.match(linea.strip())
                if coincide:
                    esperado = int(coincide.group(1))
            continue
        _revisar_sintaxis(linea, donde)
        if estado == "previo":
            variable = _RE_VARIABLE.match(linea.strip())
            if variable:
                doc.variables[variable.group(1)] = variable.group(2).strip()
                continue
            coincide = _RE_PEDIDO.match(linea.strip())
            if not coincide:
                raise SintaxisNoSoportada(f"{donde}: linea no soportada: {linea.strip()!r}")
            if coincide.group(1) not in METODOS:
                raise SintaxisNoSoportada(f"{donde}: metodo {coincide.group(1)} no soportado")
            pedido = Pedido(titulo, coincide.group(1), coincide.group(2))
            estado = "cabeceras"
            continue
        cabecera = _RE_CABECERA.match(linea.strip())
        if not cabecera:
            raise SintaxisNoSoportada(f"{donde}: cabecera no soportada: {linea.strip()!r}")
        pedido.cabeceras.append((cabecera.group(1), cabecera.group(2).strip()))

    if pedido is None:
        return
    while cuerpo and not cuerpo[-1].strip():
        cuerpo.pop()
    pedido.cuerpo = "\n".join(cuerpo) if cuerpo else None
    pedido.nombre, pedido.prompts, pedido.sin_jar, pedido.esperado = nombre, prompts, sin_jar, esperado
    doc.pedidos.append(pedido)


def parsear(texto: str) -> Documento:
    """Convierte el texto de un ``.http`` en variables y pedidos; falla ante sintaxis no soportada."""
    doc = Documento()
    for numero, (titulo, lineas) in enumerate(_bloques(texto)):
        _parsear_bloque(titulo, lineas, doc, numero)
    return doc


def _actualizar_jar(jar: dict[str, str], respuesta: httpx.Response) -> None:
    for linea in respuesta.headers.get_list("set-cookie"):
        par, *atributos = [parte.strip() for parte in linea.split(";")]
        nombre, _, valor = par.partition("=")
        borrada = not valor or any(a.lower() == "max-age=0" for a in atributos)
        if borrada:
            jar.pop(nombre, None)
        else:
            jar[nombre] = valor


def _resolver(
    texto: str,
    doc: Documento,
    claves: Mapping[str, str],
    prompts: set[str],
    respuestas: Mapping[str, httpx.Response],
    profundidad: int = 0,
) -> str:
    if profundidad > 10:
        raise SintaxisNoSoportada(f"referencia circular entre variables en {texto!r}")

    def sustituir(coincidencia: re.Match) -> str:
        expresion = coincidencia.group(1)
        if expresion.startswith("$"):
            raise SintaxisNoSoportada(f"variable de sistema no soportada: {{{{{expresion}}}}}")
        de_respuesta = _RE_RESPUESTA.match(expresion)
        if de_respuesta:
            nombre, cabecera = de_respuesta.groups()
            if nombre not in respuestas:
                raise SintaxisNoSoportada(f"el pedido '{nombre}' todavia no se ejecuto (o no tiene # @name)")
            valores = respuestas[nombre].headers.get_list(cabecera)
            if not valores:
                raise SintaxisNoSoportada(f"la respuesta de '{nombre}' no trae la cabecera {cabecera}")
            return valores[0]
        if expresion in doc.variables:
            return _resolver(doc.variables[expresion], doc, claves, prompts, respuestas, profundidad + 1)
        if expresion in prompts:
            if expresion not in claves:
                raise SintaxisNoSoportada(f"sin valor para el # @prompt '{expresion}'")
            return claves[expresion]
        raise SintaxisNoSoportada(f"variable '{expresion}' no definida")

    return _RE_REFERENCIA.sub(sustituir, texto)


async def ejecutar(doc: Documento, cliente: httpx.AsyncClient, claves: Mapping[str, str]) -> list[Resultado]:
    """Envia los pedidos en orden con ``cliente`` y devuelve el codigo recibido de cada uno.

    ``claves`` da el valor de cada ``# @prompt`` (nombre de variable -> valor), solo en memoria.
    No compara con ``# Esperado``: lo hace quien llama.
    """
    resultados: list[Resultado] = []
    respuestas: dict[str, httpx.Response] = {}
    jar: dict[str, str] = {}
    for pedido in doc.pedidos:
        prompts = {nombre for nombre, _ in pedido.prompts}

        def resolver(texto: str) -> str:
            return _resolver(texto, doc, claves, prompts, respuestas)

        url = resolver(pedido.url)
        cabeceras = {nombre: resolver(valor) for nombre, valor in pedido.cabeceras}
        if not pedido.sin_jar and jar and not any(n.lower() == "cookie" for n in cabeceras):
            cabeceras["Cookie"] = "; ".join(f"{n}={v}" for n, v in jar.items())
        contenido = resolver(pedido.cuerpo).encode() if pedido.cuerpo is not None else None

        respuesta = await cliente.request(pedido.metodo, url, headers=cabeceras, content=contenido)
        cliente.cookies.clear()  # la jarra es la nuestra: se respeta # @no-cookie-jar
        if not pedido.sin_jar:
            _actualizar_jar(jar, respuesta)
        if pedido.nombre:
            respuestas[pedido.nombre] = respuesta
        cookies = respuesta.headers.get_list("set-cookie")
        resultados.append(Resultado(pedido, respuesta.status_code, respuesta.text, cookies[0] if cookies else None))
    return resultados


def claves_de_prompts(doc: Documento) -> dict[str, str]:
    """Valor en memoria de cada ``# @prompt clave_*`` del documento.

    ``clave_<usuario>`` toma la contraseña de ``<usuario>@example.com`` en ``seed.CONTRASENAS_SEED``;
    cualquier otra (``clave_elegida``, ``clave_incorrecta``) recibe un valor aleatorio descartable.
    Nada de esto se escribe en disco ni se imprime.
    """
    import seed

    claves: dict[str, str] = {}
    for pedido in doc.pedidos:
        for variable, _ in pedido.prompts:
            correo = f"{variable.removeprefix('clave_')}@example.com"
            claves[variable] = seed.CONTRASENAS_SEED.get(correo) or secrets.token_urlsafe(12)
    return claves
