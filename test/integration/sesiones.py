"""Ayudantes de sesion reutilizables por los tests de C-06/C-07/C-08 (sin fixtures).

Contrasenas siempre aleatorias (``secrets``): nunca literales en los tests.
"""
import secrets


def clave() -> str:
    """Contrasena de prueba aleatoria que cumple la politica (>= 8 caracteres, < 72 bytes)."""
    return "pw-" + secrets.token_urlsafe(12)


async def entrar(http, email: str, password: str):
    """Login real por ``POST /auth/login``; falla si no responde 200. Deja la cookie en ``http``."""
    r = await http.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r


async def usuario_con_sesion(db_auth, fabrica_http, email: str, roles=("ADMIN",), **kwargs):
    """Siembra un usuario con ``roles`` y devuelve ``(id, cliente_http_con_sesion, password)``."""
    password = clave()
    uid = await db_auth.crear_usuario(email, password, roles=roles, **kwargs)
    http = fabrica_http()
    await entrar(http, email, password)
    return uid, http, password


async def admin_con_sesion(db_auth, fabrica_http, email: str):
    """Siembra un ADMIN y devuelve ``(id, cliente_http_con_sesion)``."""
    uid, http, _ = await usuario_con_sesion(db_auth, fabrica_http, email, roles=("ADMIN",))
    return uid, http
