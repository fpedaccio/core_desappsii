"""Scope de datos por modulo, dashboard y alertas de integracion.

El scope lo aplican los repositorios, no la capa HTTP: la idea es que no haya
forma de pedir datos de otro modulo cambiando un query param. Estos tests son
los que verifican esa garantia.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


# ----------------------------------------------------------------------
# Login
# ----------------------------------------------------------------------
async def test_login_devuelve_is_admin_solo_para_core(client, auth):
    for module, expected in [("atencion-ciudadana", False), ("obras", False), ("core", True)]:
        response = await client.post(
            "/api/v1/auth/login",
            json={"module": module, "secret": "test-secret-para-los-modulos"},
        )
        assert response.json()["isAdmin"] is expected


async def test_secret_incorrecto_da_401(client):
    response = await client.post(
        "/api/v1/auth/login", json={"module": "obras", "secret": "mal"}
    )
    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_CREDENTIALS"


async def test_modulo_inexistente_da_el_mismo_error_que_secret_malo(client):
    """No se filtra si el modulo existe o no."""
    inexistente = await client.post(
        "/api/v1/auth/login", json={"module": "no-existe", "secret": "x"}
    )
    mal_secret = await client.post(
        "/api/v1/auth/login", json={"module": "obras", "secret": "x"}
    )
    assert inexistente.status_code == mal_secret.status_code == 401
    assert inexistente.json()["code"] == mal_secret.json()["code"]


async def test_me_devuelve_la_identidad(client, auth):
    response = await client.get("/api/v1/auth/me", headers=await auth("obras"))
    assert response.json() == {
        "module": "obras",
        "displayName": "Obras Publicas",
        "isAdmin": False,
    }


# ----------------------------------------------------------------------
# Scope de datos
# ----------------------------------------------------------------------
async def test_un_modulo_ve_lo_que_publico(client, auth, make_envelope):
    ac = await auth("atencion-ciudadana")
    await client.post("/api/v1/events", json=make_envelope(), headers=ac)

    events = await client.get("/api/v1/events", headers=ac)
    assert events.json()["total"] == 1


async def test_un_modulo_ve_lo_que_le_entregaron(client, auth, make_envelope):
    ac = await auth("atencion-ciudadana")
    await client.post("/api/v1/events", json=make_envelope(), headers=ac)

    # obras no lo publico, pero es suscriptor: tiene que verlo.
    obras = await auth("obras")
    events = await client.get("/api/v1/events", headers=obras)
    assert events.json()["total"] == 1


async def test_un_modulo_no_ve_el_trafico_ajeno(client, auth, make_envelope):
    """workOrderScheduled lo publica obras y nadie lo consume, asi que
    atencion-ciudadana no deberia verlo."""
    obras = await auth("obras")
    await client.post(
        "/api/v1/events",
        json=make_envelope(eventType="workOrderScheduled", sourceModule="obras"),
        headers=obras,
    )

    ac = await auth("atencion-ciudadana")
    events = await client.get("/api/v1/events", headers=ac)
    assert events.json()["total"] == 0


async def test_el_query_param_no_permite_espiar_a_otro(client, auth, make_envelope):
    """La garantia central: el scope lo aplica el repositorio, asi que pedir
    explicitamente el trafico de otro modulo no devuelve nada."""
    obras = await auth("obras")
    await client.post(
        "/api/v1/events",
        json=make_envelope(eventType="workOrderScheduled", sourceModule="obras"),
        headers=obras,
    )

    ac = await auth("atencion-ciudadana")
    events = await client.get("/api/v1/events?sourceModule=obras", headers=ac)
    assert events.json()["total"] == 0


async def test_el_admin_ve_todo(client, auth, make_envelope):
    ac = await auth("atencion-ciudadana")
    obras = await auth("obras")
    await client.post("/api/v1/events", json=make_envelope(), headers=ac)
    await client.post(
        "/api/v1/events",
        json=make_envelope(eventType="workOrderScheduled", sourceModule="obras"),
        headers=obras,
    )

    admin = await auth("core")
    events = await client.get("/api/v1/events", headers=admin)
    assert events.json()["total"] == 2


async def test_un_modulo_no_puede_leer_un_evento_ajeno_por_id(client, auth, make_envelope):
    obras = await auth("obras")
    envelope = make_envelope(eventType="workOrderScheduled", sourceModule="obras")
    await client.post("/api/v1/events", json=envelope, headers=obras)

    ac = await auth("atencion-ciudadana")
    response = await client.get(f"/api/v1/events/{envelope['eventId']}", headers=ac)
    assert response.status_code == 404


# ----------------------------------------------------------------------
# Dashboard
# ----------------------------------------------------------------------
async def test_el_dashboard_de_un_modulo_cuenta_lo_suyo(client, auth, make_envelope):
    ac = await auth("atencion-ciudadana")
    await client.post("/api/v1/events", json=make_envelope(), headers=ac)
    await client.post("/api/v1/events", json=make_envelope(), headers=ac)

    dashboard = (await client.get("/api/v1/dashboard", headers=ac)).json()
    assert dashboard["module"] == "atencion-ciudadana"
    assert dashboard["published"]["total"] == 2
    assert dashboard["publications"]["declared"] == ["ticketCreated"]


async def test_el_dashboard_cuenta_las_entregas_recibidas(client, auth, make_envelope):
    ac = await auth("atencion-ciudadana")
    await client.post("/api/v1/events", json=make_envelope(), headers=ac)

    obras = await auth("obras")
    dashboard = (await client.get("/api/v1/dashboard", headers=obras)).json()
    assert dashboard["received"]["delivered"] == 1
    assert dashboard["subscriptions"]["eventTypes"] == ["ticketCreated"]


async def test_un_modulo_no_puede_pedir_el_dashboard_de_otro(client, auth):
    obras = await auth("obras")
    response = await client.get(
        "/api/v1/dashboard/modules/atencion-ciudadana", headers=obras
    )
    assert response.status_code == 403


async def test_el_admin_puede_pedir_el_dashboard_de_cualquiera(client, auth):
    admin = await auth("core")
    response = await client.get(
        "/api/v1/dashboard/modules/atencion-ciudadana", headers=admin
    )
    assert response.status_code == 200
    assert response.json()["module"] == "atencion-ciudadana"


async def test_el_dashboard_global_es_solo_del_admin(client, auth):
    comun = await client.get("/api/v1/dashboard/global", headers=await auth("obras"))
    admin = await client.get("/api/v1/dashboard/global", headers=await auth("core"))
    assert comun.status_code == 403
    assert admin.status_code == 200


async def test_el_dashboard_global_cuenta_por_estado(client, auth, make_envelope):
    ac = await auth("atencion-ciudadana")
    await client.post("/api/v1/events", json=make_envelope(), headers=ac)
    await client.post(
        "/api/v1/events",
        json=make_envelope(eventType="workOrderScheduled", sourceModule="atencion-ciudadana"),
        headers=ac,
    )

    admin = await auth("core")
    dashboard = (await client.get("/api/v1/dashboard/global", headers=admin)).json()
    assert dashboard["events"]["byStatus"]["ROUTED"] == 1
    assert dashboard["events"]["byStatus"]["NO_SUBSCRIBERS"] == 1
    assert dashboard["broker"]["connected"] is True
    assert len(dashboard["modules"]) == 3


# ----------------------------------------------------------------------
# Alertas de integracion
# ----------------------------------------------------------------------
async def test_alerta_cuando_llegan_eventos_que_nadie_consume(client, auth, make_envelope):
    ac = await auth("atencion-ciudadana")
    await client.post(
        "/api/v1/events",
        json=make_envelope(eventType="workOrderScheduled", sourceModule="atencion-ciudadana"),
        headers=ac,
    )

    admin = await auth("core")
    alerts = (await client.get("/api/v1/dashboard/integration-alerts", headers=admin)).json()
    sin_suscriptores = [a for a in alerts if a["kind"] == "NO_SUBSCRIBERS"]
    assert any(a["eventType"] == "workOrderScheduled" for a in sin_suscriptores)


async def test_alerta_cuando_aparece_un_tipo_sin_declarar(client, auth, make_envelope):
    obras = await auth("obras")
    await client.post(
        "/api/v1/events",
        json=make_envelope(eventType="ticketCreatd", sourceModule="obras"),  # typo a proposito
        headers=obras,
    )

    admin = await auth("core")
    alerts = (await client.get("/api/v1/dashboard/integration-alerts", headers=admin)).json()
    assert any(
        a["kind"] == "UNDECLARED_TYPE" and a["eventType"] == "ticketCreatd" for a in alerts
    )


async def test_alerta_de_nombres_parecidos_detecta_el_typo(client, auth, make_envelope):
    """El caso que mas duele en la integracion: un typo que hace que el evento
    no le llegue a nadie y nadie sepa por que."""
    obras = await auth("obras")
    await client.post(
        "/api/v1/events",
        json=make_envelope(eventType="ticketCreatd", sourceModule="obras"),
        headers=obras,
    )

    admin = await auth("core")
    alerts = (await client.get("/api/v1/dashboard/integration-alerts", headers=admin)).json()
    parecidos = [a for a in alerts if a["kind"] == "SIMILAR_NAMES"]
    assert any("ticketCreatd" in a["detail"] and "ticketCreated" in a["detail"] for a in parecidos)


async def test_las_alertas_vienen_ordenadas_por_severidad(client, auth):
    admin = await auth("core")
    alerts = (await client.get("/api/v1/dashboard/integration-alerts", headers=admin)).json()
    severidades = [a["severity"] for a in alerts]
    assert severidades == sorted(severidades, key=lambda s: {"warning": 0, "info": 1}.get(s, 2))
