"""Cuentas del dashboard: cada equipo administra las de sus integrantes."""

from __future__ import annotations

import pytest

from tests.conftest import USER_PASSWORD

pytestmark = pytest.mark.asyncio

NUEVA = {"email": "ana@munitest.com", "fullName": "Ana Perez", "password": "Secreta123"}


async def test_crear_una_cuenta_en_mi_equipo(client, auth):
    obras = await auth("obras")
    response = await client.post("/api/v1/users", json=NUEVA, headers=obras)

    assert response.status_code == 201
    assert response.json()["email"] == "ana@munitest.com"
    assert response.json()["moduleName"] == "obras"


async def test_la_cuenta_nueva_puede_entrar(client, auth):
    obras = await auth("obras")
    await client.post("/api/v1/users", json=NUEVA, headers=obras)

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "ana@munitest.com", "password": "Secreta123"},
    )
    assert login.status_code == 200
    assert login.json()["module"] == "obras"
    assert login.json()["actor"] == "ana@munitest.com"


async def test_la_cuenta_nueva_hereda_el_scope_del_equipo(client, auth, make_envelope):
    """Una persona ve lo de su modulo, no lo de los demas."""
    ac = await auth("atencion-ciudadana")
    await client.post("/api/v1/events", json=make_envelope(), headers=ac)

    obras = await auth("obras")
    await client.post("/api/v1/users", json=NUEVA, headers=obras)
    ana = (
        await client.post(
            "/api/v1/auth/login",
            json={"email": "ana@munitest.com", "password": "Secreta123"},
        )
    ).json()
    headers = {"Authorization": f"Bearer {ana['accessToken']}"}

    # obras es suscriptor de ticketCreated, asi que Ana lo ve.
    events = await client.get("/api/v1/events", headers=headers)
    assert events.json()["total"] == 1
    assert ana["isAdmin"] is False


async def test_no_se_puede_crear_una_cuenta_en_otro_equipo(client, auth):
    obras = await auth("obras")
    response = await client.post(
        "/api/v1/users", json={**NUEVA, "module": "atencion-ciudadana"}, headers=obras
    )
    assert response.status_code == 403


async def test_el_admin_puede_crear_en_cualquier_equipo(client, auth):
    admin = await auth("core")
    response = await client.post(
        "/api/v1/users", json={**NUEVA, "module": "atencion-ciudadana"}, headers=admin
    )
    assert response.status_code == 201
    assert response.json()["moduleName"] == "atencion-ciudadana"


async def test_no_se_repite_el_email(client, auth):
    obras = await auth("obras")
    await client.post("/api/v1/users", json=NUEVA, headers=obras)
    repetido = await client.post("/api/v1/users", json=NUEVA, headers=obras)
    assert repetido.status_code == 409


@pytest.mark.parametrize("password", ["corta1", "solamenteletras", "12345678"])
async def test_rechaza_contrasenas_debiles(client, auth, password):
    obras = await auth("obras")
    response = await client.post(
        "/api/v1/users", json={**NUEVA, "password": password}, headers=obras
    )
    assert response.status_code == 422


async def test_un_equipo_solo_ve_sus_cuentas(client, auth):
    obras = await auth("obras")
    cuentas = (await client.get("/api/v1/users", headers=obras)).json()
    assert [c["email"] for c in cuentas] == ["obras@munitest.com"]


async def test_el_admin_ve_las_cuentas_de_todos(client, auth):
    admin = await auth("core")
    cuentas = (await client.get("/api/v1/users", headers=admin)).json()
    assert len(cuentas) == 3


async def test_desactivar_una_cuenta_le_impide_entrar(client, auth):
    obras = await auth("obras")
    creada = (await client.post("/api/v1/users", json=NUEVA, headers=obras)).json()

    await client.patch(f"/api/v1/users/{creada['id']}", json={"active": False}, headers=obras)

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "ana@munitest.com", "password": "Secreta123"},
    )
    assert login.status_code == 403
    assert login.json()["code"] == "ACCOUNT_INACTIVE"


async def test_no_se_puede_desactivar_la_unica_cuenta_del_equipo(client, auth):
    """Si no, el equipo se queda sin forma de volver a entrar."""
    obras = await auth("obras")
    propia = (await client.get("/api/v1/users", headers=obras)).json()[0]

    response = await client.patch(
        f"/api/v1/users/{propia['id']}", json={"active": False}, headers=obras
    )
    assert response.status_code == 409
    assert "unica cuenta activa" in response.json()["message"]


async def test_no_se_puede_eliminar_la_unica_cuenta_del_equipo(client, auth):
    obras = await auth("obras")
    propia = (await client.get("/api/v1/users", headers=obras)).json()[0]

    response = await client.delete(f"/api/v1/users/{propia['id']}", headers=obras)
    assert response.status_code == 409


async def test_con_dos_cuentas_si_se_puede_eliminar_una(client, auth):
    obras = await auth("obras")
    creada = (await client.post("/api/v1/users", json=NUEVA, headers=obras)).json()

    response = await client.delete(f"/api/v1/users/{creada['id']}", headers=obras)
    assert response.status_code == 204
    assert len((await client.get("/api/v1/users", headers=obras)).json()) == 1


async def test_cambiar_la_contrasena(client, auth):
    obras = await auth("obras")
    creada = (await client.post("/api/v1/users", json=NUEVA, headers=obras)).json()

    await client.put(
        f"/api/v1/users/{creada['id']}/password",
        json={"password": "OtraNueva99"},
        headers=obras,
    )

    vieja = await client.post(
        "/api/v1/auth/login",
        json={"email": "ana@munitest.com", "password": "Secreta123"},
    )
    nueva = await client.post(
        "/api/v1/auth/login",
        json={"email": "ana@munitest.com", "password": "OtraNueva99"},
    )
    assert vieja.status_code == 401
    assert nueva.status_code == 200


async def test_cambiar_la_contrasena_desbloquea_la_cuenta(client, auth):
    """Es la salida cuando alguien se bloquea por intentos fallidos."""
    obras = await auth("obras")
    creada = (await client.post("/api/v1/users", json=NUEVA, headers=obras)).json()
    for _ in range(5):
        await client.post(
            "/api/v1/auth/login",
            json={"email": "ana@munitest.com", "password": "mal"},
        )

    await client.patch(f"/api/v1/users/{creada['id']}", json={"active": True}, headers=obras)
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "ana@munitest.com", "password": "Secreta123"},
    )
    assert login.status_code == 200


async def test_no_se_puede_tocar_una_cuenta_de_otro_equipo(client, auth):
    admin = await auth("core")
    ajena = (
        await client.post(
            "/api/v1/users", json={**NUEVA, "module": "atencion-ciudadana"}, headers=admin
        )
    ).json()

    obras = await auth("obras")
    assert (
        await client.patch(f"/api/v1/users/{ajena['id']}", json={"fullName": "Otro"}, headers=obras)
    ).status_code == 403
    assert (await client.delete(f"/api/v1/users/{ajena['id']}", headers=obras)).status_code == 403


async def test_la_cuenta_inicial_del_seed_usa_la_contrasena_conocida(client):
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "core@munitest.com", "password": USER_PASSWORD},
    )
    assert login.status_code == 200
    assert login.json()["isAdmin"] is True
