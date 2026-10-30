"""Repositorios del módulo usuarios contra PostgreSQL real (C-05, tareas 5.1 y 5.3)."""
from datetime import UTC, datetime, timedelta

import pytest

from app.core.database import crear_fabrica_sesiones
from app.modules.usuarios.models import Rol

pytestmark = pytest.mark.integration

AHORA = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
async def uow(motor_auth):
    from app.modules.usuarios.unit_of_work import UsuariosUoW

    fabrica = crear_fabrica_sesiones(motor_auth)
    async with fabrica() as sesion:
        yield UsuariosUoW(sesion)


# --- 5.1 get_by_email -------------------------------------------------------------


async def test_get_by_email_encuentra_por_correo_exacto(uow, db_auth):
    uid = await db_auth.crear_usuario("ana@example.com", "clave-de-prueba-1")
    async with uow:
        usuario = await uow.usuarios.get_by_email("ana@example.com")
    assert usuario is not None and usuario.id == uid and usuario.email == "ana@example.com"


async def test_get_by_email_devuelve_none_si_no_existe(uow, db_auth):
    await db_auth.crear_usuario("ana@example.com", "clave-de-prueba-1")
    async with uow:
        assert await uow.usuarios.get_by_email("otra@example.com") is None


async def test_get_by_email_es_exacto_no_busca_por_prefijo_ni_comodines(uow, db_auth):
    await db_auth.crear_usuario("ana@example.com", "clave-de-prueba-1")
    async with uow:
        assert await uow.usuarios.get_by_email("ana@example.co") is None
        assert await uow.usuarios.get_by_email("%") is None
        assert await uow.usuarios.get_by_email("' OR '1'='1") is None


# --- 5.1 roles_vigentes -----------------------------------------------------------


async def test_roles_vigentes_solo_abiertos_no_revocados_ni_vencidos(uow, db_auth):
    uid = await db_auth.crear_usuario("r@example.com", "clave-de-prueba-1", roles=[])
    await db_auth.asignar_rol(uid, "ADMIN")  # abierta sin vencimiento
    await db_auth.asignar_rol(uid, "RECEPCION", vence_en=AHORA - timedelta(seconds=1))  # vencida
    await db_auth.asignar_rol(uid, "MECANICO", revocada_en=AHORA - timedelta(days=1))  # revocada
    await db_auth.asignar_rol(uid, "CLIENTE", vence_en=AHORA + timedelta(days=1))  # vence a futuro
    async with uow:
        roles = await uow.asignaciones.roles_vigentes(uid, AHORA)
    assert roles == [Rol.ADMIN, Rol.CLIENTE]


async def test_roles_vigentes_de_otro_usuario_no_se_mezclan(uow, db_auth):
    a = await db_auth.crear_usuario("a@example.com", "clave-de-prueba-1", roles=["ADMIN"])
    b = await db_auth.crear_usuario("b@example.com", "clave-de-prueba-1", roles=["MECANICO"])
    async with uow:
        assert await uow.asignaciones.roles_vigentes(a, AHORA) == [Rol.ADMIN]
        assert await uow.asignaciones.roles_vigentes(b, AHORA) == [Rol.MECANICO]


async def test_roles_vigentes_vence_en_igual_a_ahora_ya_no_es_vigente(uow, db_auth):
    uid = await db_auth.crear_usuario("r@example.com", "clave-de-prueba-1", roles=[])
    await db_auth.asignar_rol(uid, "ADMIN", vence_en=AHORA)
    async with uow:
        assert await uow.asignaciones.roles_vigentes(uid, AHORA) == []


async def test_roles_vigentes_sin_asignaciones_es_lista_vacia(uow, db_auth):
    uid = await db_auth.crear_usuario("r@example.com", "clave-de-prueba-1", roles=[])
    async with uow:
        assert await uow.asignaciones.roles_vigentes(uid, AHORA) == []


async def test_uow_comparte_una_sesion_entre_los_cinco_repositorios(uow):
    sesiones = {r.session for r in (uow.usuarios, uow.asignaciones, uow.clientes, uow.eventos, uow.intentos)}
    assert sesiones == {uow.session}


# --- 5.3 fallos_bloqueantes (D7) --------------------------------------------------

EMAIL = "ana@example.com"
IP = "10.0.0.1"


async def _fallos(uow, ahora, email=EMAIL, ip=IP):
    async with uow:
        return await uow.intentos.fallos_bloqueantes(email, ip, desde=ahora - timedelta(seconds=60))


async def test_cinco_fallos_recientes_devuelve_cinco_ordenados_del_mas_nuevo(uow, db_auth):
    ahora = datetime.now(UTC)
    for segundos in (50, 40, 30, 20, 10):
        await db_auth.insertar_intento(EMAIL, IP, False, ahora - timedelta(seconds=segundos))
    fallos = await _fallos(uow, ahora)
    assert fallos == sorted(fallos, reverse=True)
    assert len(fallos) == 5
    assert fallos[0] == ahora - timedelta(seconds=10)


async def test_fallos_de_hace_mas_de_60_segundos_no_cuentan(uow, db_auth):
    ahora = datetime.now(UTC)
    for segundos in (61, 62, 63, 64, 65):
        await db_auth.insertar_intento(EMAIL, IP, False, ahora - timedelta(seconds=segundos))
    assert await _fallos(uow, ahora) == []


async def test_cuatro_fallos_exito_cuatro_fallos_cuenta_solo_los_posteriores_al_exito(uow, db_auth):
    ahora = datetime.now(UTC)
    for segundos in (50, 49, 48, 47):
        await db_auth.insertar_intento(EMAIL, IP, False, ahora - timedelta(seconds=segundos))
    await db_auth.insertar_intento(EMAIL, IP, True, ahora - timedelta(seconds=40))
    for segundos in (30, 29, 28, 27):
        await db_auth.insertar_intento(EMAIL, IP, False, ahora - timedelta(seconds=segundos))
    assert len(await _fallos(uow, ahora)) == 4


async def test_devuelve_como_maximo_cinco_aunque_haya_mas(uow, db_auth):
    ahora = datetime.now(UTC)
    for segundos in range(1, 9):
        await db_auth.insertar_intento(EMAIL, IP, False, ahora - timedelta(seconds=segundos))
    assert len(await _fallos(uow, ahora)) == 5


async def test_fallos_de_otra_ip_u_otro_correo_no_cuentan(uow, db_auth):
    ahora = datetime.now(UTC)
    for _ in range(3):
        await db_auth.insertar_intento(EMAIL, "10.0.0.2", False, ahora - timedelta(seconds=5))
        await db_auth.insertar_intento("otro@example.com", IP, False, ahora - timedelta(seconds=5))
    await db_auth.insertar_intento(EMAIL, IP, False, ahora - timedelta(seconds=5))
    assert len(await _fallos(uow, ahora)) == 1


async def test_exito_de_otra_ip_no_reinicia_la_cuenta(uow, db_auth):
    ahora = datetime.now(UTC)
    for segundos in (30, 20, 10):
        await db_auth.insertar_intento(EMAIL, IP, False, ahora - timedelta(seconds=segundos))
    await db_auth.insertar_intento(EMAIL, "10.0.0.2", True, ahora - timedelta(seconds=5))
    assert len(await _fallos(uow, ahora)) == 3


async def test_exito_posterior_a_todos_los_fallos_deja_cero(uow, db_auth):
    ahora = datetime.now(UTC)
    for segundos in (30, 20, 10):
        await db_auth.insertar_intento(EMAIL, IP, False, ahora - timedelta(seconds=segundos))
    await db_auth.insertar_intento(EMAIL, IP, True, ahora - timedelta(seconds=5))
    assert await _fallos(uow, ahora) == []


# --- C-06 3.1/3.2: abierta, historial, listar_recientes ---------------------------------


def _hace(**kw):
    return datetime.now(UTC) - timedelta(**kw)


async def test_abierta_devuelve_la_fila_no_revocada_vigente_o_vencida_y_none_si_solo_revocadas(uow, db_auth):
    uid = await db_auth.crear_usuario("ana@example.com", "clave-de-prueba-1", roles=())
    await db_auth.asignar_rol(uid, "MECANICO", revocada_en=_hace(days=2))
    await db_auth.asignar_rol(uid, "RECEPCION", vence_en=_hace(days=1))  # abierta pero vencida
    await db_auth.asignar_rol(uid, "ADMIN")  # abierta y vigente
    async with uow:
        assert await uow.asignaciones.abierta(uid, "MECANICO") is None
        vencida = await uow.asignaciones.abierta(uid, "RECEPCION")
        vigente = await uow.asignaciones.abierta(uid, "ADMIN")
        assert await uow.asignaciones.abierta(uid, "CLIENTE") is None
    assert vencida is not None and vencida.rol == "RECEPCION" and vencida.revocada_en is None
    assert vigente is not None and vigente.rol == "ADMIN"


async def test_abierta_acepta_el_enum_rol_y_no_mezcla_usuarios(uow, db_auth):
    a = await db_auth.crear_usuario("a@example.com", "clave-de-prueba-1", roles=("MECANICO",))
    b = await db_auth.crear_usuario("b@example.com", "clave-de-prueba-1", roles=())
    async with uow:
        assert (await uow.asignaciones.abierta(a, Rol.MECANICO)) is not None
        assert await uow.asignaciones.abierta(b, Rol.MECANICO) is None


async def test_historial_devuelve_todas_las_filas_del_usuario_ordenadas_por_desde_e_id(uow, db_auth):
    uid = await db_auth.crear_usuario("ana@example.com", "clave-de-prueba-1", roles=())
    otro = await db_auth.crear_usuario("otro@example.com", "clave-de-prueba-1", roles=("ADMIN",))
    t = datetime(2026, 1, 1, tzinfo=UTC)
    # insertadas fuera de orden: el orden sale de ``desde``, luego de ``id``
    for rol, desde in (("ADMIN", t + timedelta(days=2)), ("RECEPCION", t), ("MECANICO", t)):
        await db_auth.ejecutar(
            "INSERT INTO asignacion_rol (usuario_id, rol, desde) VALUES (:u, :r, :d)", u=uid, r=rol, d=desde
        )
    await db_auth.asignar_rol(uid, "CLIENTE", revocada_en=_hace(days=1))
    async with uow:
        filas = await uow.asignaciones.historial(uid)
    assert [f.rol for f in filas[:3]] == ["RECEPCION", "MECANICO", "ADMIN"]
    assert len(filas) == 4 and all(f.usuario_id == uid for f in filas)
    assert otro not in {f.usuario_id for f in filas}
    async with uow:
        assert await uow.asignaciones.historial(999999) == []


async def test_listar_recientes_ordena_por_cuando_desc_e_id_desc_con_offset_y_limite(uow, db_auth):
    t = datetime(2026, 1, 1, tzinfo=UTC)
    for actor, cuando in (("a", t), ("b", t + timedelta(hours=1)), ("c", t + timedelta(hours=1)), ("d", t)):
        await db_auth.ejecutar(
            "INSERT INTO evento_seguridad (cuando, actor, accion) VALUES (:w, :a, 'x')", w=cuando, a=actor
        )
    async with uow:
        todos = await uow.eventos.listar_recientes(offset=0, limit=10)
        pag = await uow.eventos.listar_recientes(offset=1, limit=2)
    # mismo ``cuando``: mayor id primero
    assert [e.actor for e in todos] == ["c", "b", "d", "a"]
    assert [e.actor for e in pag] == ["b", "d"]


# --- C-06 3.3: bloquear_admins_vigentes -------------------------------------------------


async def test_bloquear_admins_vigentes_solo_admin_abierto_no_vencido_de_usuario_activo(uow, db_auth):
    vigente = await db_auth.crear_usuario("v@example.com", "clave-de-prueba-1", roles=("ADMIN",))
    vence_futuro = await db_auth.crear_usuario("f@example.com", "clave-de-prueba-1", roles=())
    await db_auth.asignar_rol(vence_futuro, "ADMIN", vence_en=datetime.now(UTC) + timedelta(days=1))
    vencido = await db_auth.crear_usuario("x@example.com", "clave-de-prueba-1", roles=())
    await db_auth.asignar_rol(vencido, "ADMIN", vence_en=_hace(days=1))
    revocado = await db_auth.crear_usuario("r@example.com", "clave-de-prueba-1", roles=())
    await db_auth.asignar_rol(revocado, "ADMIN", revocada_en=_hace(days=1))
    await db_auth.crear_usuario("i@example.com", "clave-de-prueba-1", roles=("ADMIN",), activo=False)
    await db_auth.crear_usuario("m@example.com", "clave-de-prueba-1", roles=("MECANICO",))
    async with uow:
        ids = await uow.asignaciones.bloquear_admins_vigentes(datetime.now(UTC))
    assert sorted(ids) == sorted([vigente, vence_futuro])
    assert ids == sorted(ids)  # ORDER BY id de asignacion (sembradas en orden creciente)


async def test_bloquear_admins_vigentes_sin_admins_devuelve_lista_vacia(uow, db_auth):
    await db_auth.crear_usuario("m@example.com", "clave-de-prueba-1", roles=("MECANICO",))
    async with uow:
        assert await uow.asignaciones.bloquear_admins_vigentes(datetime.now(UTC)) == []


async def test_bloquear_admins_vigentes_la_segunda_transaccion_espera_y_luego_no_ve_la_fila_revocada(
    motor_auth, db_auth
):
    import asyncio

    from app.modules.usuarios.unit_of_work import UsuariosUoW

    a = await db_auth.crear_usuario("a@example.com", "clave-de-prueba-1", roles=("ADMIN",))
    b = await db_auth.crear_usuario("b@example.com", "clave-de-prueba-1", roles=("ADMIN",))
    fabrica = crear_fabrica_sesiones(motor_auth)
    async with fabrica() as s1, fabrica() as s2:
        uow1, uow2 = UsuariosUoW(s1), UsuariosUoW(s2)
        visto1 = await uow1.asignaciones.bloquear_admins_vigentes(datetime.now(UTC))
        assert sorted(visto1) == sorted([a, b])

        segunda = asyncio.ensure_future(uow2.asignaciones.bloquear_admins_vigentes(datetime.now(UTC)))
        # La segunda queda esperando el bloqueo de filas: no termina mientras la primera no confirma.
        hecho, _ = await asyncio.wait({segunda}, timeout=1.0)
        assert not hecho, "la segunda transaccion debia esperar el FOR UPDATE"

        # La primera revoca la fila de ``b`` y confirma.
        abierta_b = await uow1.asignaciones.abierta(b, Rol.ADMIN)
        await uow1.asignaciones.update(abierta_b, {"revocada_en": datetime.now(UTC)})
        await s1.commit()

        visto2 = await asyncio.wait_for(segunda, timeout=5)
        await s2.rollback()
    assert visto2 == [a]
