"""UnitOfWork: commit/rollback sin cerrar la sesion (D5), con sesion espia."""
import asyncio
from pathlib import Path

import pytest

from app.core.unit_of_work import UnitOfWork

pytestmark = pytest.mark.unit

RAIZ = Path(__file__).resolve().parents[2]


class SesionEspia:
    def __init__(self, commit_falla: BaseException | None = None):
        self.llamadas: list[str] = []
        self._commit_falla = commit_falla

    async def commit(self):
        self.llamadas.append("commit")
        if self._commit_falla is not None:
            raise self._commit_falla

    async def rollback(self):
        self.llamadas.append("rollback")

    async def close(self):
        self.llamadas.append("close")


async def test_bloque_sin_error_hace_commit():
    sesion = SesionEspia()
    async with UnitOfWork(sesion):
        pass
    assert sesion.llamadas == ["commit"]


async def test_excepcion_en_bloque_hace_rollback_y_propaga_la_misma_instancia():
    sesion = SesionEspia()
    error = RuntimeError("boom")
    with pytest.raises(RuntimeError) as info:
        async with UnitOfWork(sesion):
            raise error
    assert info.value is error
    assert sesion.llamadas == ["rollback"]


async def test_commit_que_falla_hace_rollback_y_propaga_el_error_del_commit():
    falla = ValueError("commit roto")
    sesion = SesionEspia(commit_falla=falla)
    with pytest.raises(ValueError) as info:
        async with UnitOfWork(sesion):
            pass
    assert info.value is falla
    assert sesion.llamadas == ["commit", "rollback"]


async def test_cancelacion_hace_rollback_y_propaga():
    sesion = SesionEspia()
    with pytest.raises(asyncio.CancelledError):
        async with UnitOfWork(sesion):
            raise asyncio.CancelledError
    assert sesion.llamadas == ["rollback"]


async def test_aenter_devuelve_la_propia_uow_y_expone_la_sesion():
    sesion = SesionEspia()
    uow = UnitOfWork(sesion)
    async with uow as dentro:
        assert dentro is uow
        assert uow.session is sesion


@pytest.mark.parametrize("escenario", ["ok", "error", "commit_falla", "cancelado"])
async def test_nunca_cierra_la_sesion(escenario):
    sesion = SesionEspia(commit_falla=ValueError() if escenario == "commit_falla" else None)
    try:
        async with UnitOfWork(sesion):
            if escenario == "error":
                raise RuntimeError
            if escenario == "cancelado":
                raise asyncio.CancelledError
    except BaseException:
        pass
    assert "close" not in sesion.llamadas


class RepoFalso:
    def __init__(self, session):
        self.session = session


class UoWDeModulo(UnitOfWork):
    def __init__(self, session):
        super().__init__(session)
        self.a = RepoFalso(session)
        self.b = RepoFalso(session)


def test_uow_de_modulo_comparte_la_sesion_entre_repositorios():
    sesion = SesionEspia()
    uow = UoWDeModulo(sesion)
    assert uow.a.session is uow.session
    assert uow.b.session is uow.session
    assert uow.a.session is sesion


def test_fuente_de_unit_of_work_no_contiene_close():
    fuente = (RAIZ / "app" / "core" / "unit_of_work.py").read_text(encoding="utf-8")
    assert ".close(" not in fuente
