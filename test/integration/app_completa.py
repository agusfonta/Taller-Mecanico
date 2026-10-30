"""Fixtures de la app COMPLETA (todos los routers) sobre el seed real, compartidas por los tests de entrega (C-12).

Se reexportan desde ``test/integration/seed/conftest.py`` para no duplicar el montaje; cada archivo de
test que las necesita las importa (``from test.integration.app_completa import ...``).
"""
from test.integration.seed.conftest import (  # noqa: F401
    app_auth,
    contrasenas_seed,
    fabrica_seed,
    seed_cargado,
    sesion_de,
)

__all__ = ["app_auth", "contrasenas_seed", "fabrica_seed", "seed_cargado", "sesion_de"]
