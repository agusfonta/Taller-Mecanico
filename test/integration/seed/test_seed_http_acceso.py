"""Acceso y visibilidad sobre el estado del seed, por HTTP con login real (C-11, 4.1 y 4.2)."""
import pytest

import seed

pytestmark = pytest.mark.integration

ROLES = {u.email: u.rol.value for u in seed.USUARIOS}


async def test_humo_health_y_login_del_admin(seed_cargado, http):
    assert (await http.get("/health/live")).status_code == 200
    respuesta = await http.post(
        "/auth/login", json={"email": "admin@example.com", "password": seed.CONTRASENAS_SEED["admin@example.com"]}
    )
    assert respuesta.status_code == 200


@pytest.mark.parametrize("email", sorted(ROLES))
async def test_login_de_cada_usuario_y_su_rol_en_auth_yo(seed_cargado, sesion_de, email):
    cliente = await sesion_de(email)
    yo = await cliente.get("/auth/yo")
    assert yo.status_code == 200
    cuerpo = yo.json()
    assert cuerpo["email"] == email
    assert cuerpo["roles_vigentes"] == [ROLES[email]]
    assert cuerpo["debe_cambiar_password"] is (email == "nuevo@example.com")


async def test_login_con_otra_contrasena_del_seed_es_401(seed_cargado, http):
    respuesta = await http.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": seed.CONTRASENAS_SEED["admin2@example.com"]},
    )
    assert respuesta.status_code == 401


async def test_usuario_con_cambio_obligatorio_recibe_403_fuera_de_auth_c09(seed_cargado, sesion_de):
    nuevo = await sesion_de("nuevo@example.com")
    assert (await nuevo.get("/ordenes")).status_code == 403
    assert (await nuevo.get("/auth/yo")).status_code == 200


async def test_cliente_ve_su_orden_y_no_la_ajena_c06(seed_cargado, sesion_de):
    cliente = await sesion_de("cliente@example.com")
    propia = await cliente.get("/ordenes/1")
    assert propia.status_code == 200
    assert propia.json()["id"] == 1
    assert (await cliente.get("/ordenes/2")).status_code == 403


async def test_cliente_ve_en_mis_vehiculos_exactamente_los_dos_de_laura(seed_cargado, sesion_de):
    cliente = await sesion_de("cliente@example.com")
    respuesta = await cliente.get("/mis-vehiculos")
    assert respuesta.status_code == 200
    assert [v["id"] for v in respuesta.json()] == [1, 2]
    laura = seed.CLIENTES[0]
    assert sorted(v["patente"] for v in respuesta.json()) == sorted(v.patente for v in laura.vehiculos)


async def test_mis_ordenes_del_cliente_es_solo_la_1(seed_cargado, sesion_de):
    cliente = await sesion_de("cliente@example.com")
    respuesta = await cliente.get("/mis-ordenes")
    assert [o["id"] for o in respuesta.json()["items"]] == [1]


async def test_mecanico2_no_lista_la_orden_2_y_mecanico_si_dd18(seed_cargado, sesion_de):
    mecanico2 = await sesion_de("mecanico2@example.com")
    mecanico = await sesion_de("mecanico@example.com")
    ids_2 = [o["id"] for o in (await mecanico2.get("/ordenes")).json()["items"]]
    ids_1 = [o["id"] for o in (await mecanico.get("/ordenes")).json()["items"]]
    assert 2 not in ids_2
    assert 2 in ids_1
