"""Registry: suscripciones, tipos de evento, modulos y topologia."""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.messaging.topology import retry_queue_for
from tests.conftest import MODULE_SECRET, USER_PASSWORD

pytestmark = pytest.mark.asyncio


# ----------------------------------------------------------------------
# Suscripciones
# ----------------------------------------------------------------------
async def test_un_modulo_se_suscribe_y_empieza_a_recibir(client, auth, make_envelope, broker):
    obras = await auth("obras")
    subscribe = await client.post(
        "/api/v1/subscriptions", json={"eventType": "workOrderScheduled"}, headers=obras
    )
    assert subscribe.status_code == 201
    assert subscribe.json()["queueName"] == "q.obras"

    ac = await auth("atencion-ciudadana")
    response = await client.post(
        "/api/v1/events",
        json=make_envelope(eventType="workOrderScheduled", sourceModule="atencion-ciudadana"),
        headers=ac,
    )
    assert response.json()["routedTo"] == ["obras"]


async def test_se_puede_suscribir_a_un_tipo_que_todavia_no_existe(client, auth):
    """Cuando llegue el primer evento, ya tiene destino."""
    obras = await auth("obras")
    response = await client.post(
        "/api/v1/subscriptions", json={"eventType": "unTipoNuevo"}, headers=obras
    )
    assert response.status_code == 201
    assert response.json()["eventType"] == "unTipoNuevo"


async def test_suscribirse_dos_veces_no_duplica(client, auth):
    obras = await auth("obras")
    first = await client.post(
        "/api/v1/subscriptions", json={"eventType": "workOrderScheduled"}, headers=obras
    )
    second = await client.post(
        "/api/v1/subscriptions", json={"eventType": "workOrderScheduled"}, headers=obras
    )
    assert first.json()["id"] == second.json()["id"]


async def test_un_modulo_no_puede_suscribir_a_otro(client, auth):
    obras = await auth("obras")
    response = await client.post(
        "/api/v1/subscriptions",
        json={"eventType": "workOrderScheduled", "module": "atencion-ciudadana"},
        headers=obras,
    )
    assert response.status_code == 403


async def test_el_admin_puede_suscribir_a_cualquiera(client, auth):
    admin = await auth("core")
    response = await client.post(
        "/api/v1/subscriptions",
        json={"eventType": "workOrderScheduled", "module": "atencion-ciudadana"},
        headers=admin,
    )
    assert response.status_code == 201
    assert response.json()["moduleName"] == "atencion-ciudadana"


async def test_pausar_una_suscripcion_deja_de_entregar(client, auth, make_envelope, broker):
    obras = await auth("obras")
    subscriptions = (await client.get("/api/v1/subscriptions", headers=obras)).json()
    subscription_id = subscriptions[0]["id"]

    await client.post(f"/api/v1/subscriptions/{subscription_id}/toggle?active=false", headers=obras)

    ac = await auth("atencion-ciudadana")
    response = await client.post("/api/v1/events", json=make_envelope(), headers=ac)
    assert response.json()["status"] == "NO_SUBSCRIBERS"
    assert broker.messages_for("q.obras") == []


async def test_reactivar_vuelve_a_entregar(client, auth, make_envelope):
    obras = await auth("obras")
    subscription_id = (await client.get("/api/v1/subscriptions", headers=obras)).json()[0]["id"]
    await client.post(f"/api/v1/subscriptions/{subscription_id}/toggle?active=false", headers=obras)
    await client.post(f"/api/v1/subscriptions/{subscription_id}/toggle?active=true", headers=obras)

    ac = await auth("atencion-ciudadana")
    response = await client.post("/api/v1/events", json=make_envelope(), headers=ac)
    assert response.json()["routedTo"] == ["obras"]


async def test_cancelar_una_suscripcion(client, auth):
    obras = await auth("obras")
    subscription_id = (await client.get("/api/v1/subscriptions", headers=obras)).json()[0]["id"]

    response = await client.delete(f"/api/v1/subscriptions/{subscription_id}", headers=obras)
    assert response.status_code == 204
    assert (await client.get("/api/v1/subscriptions", headers=obras)).json() == []


async def test_un_modulo_solo_ve_sus_suscripciones(client, auth):
    ac = await auth("atencion-ciudadana")
    assert (await client.get("/api/v1/subscriptions", headers=ac)).json() == []

    admin = await auth("core")
    assert len((await client.get("/api/v1/subscriptions", headers=admin)).json()) == 1


# ----------------------------------------------------------------------
# Tipos de evento
# ----------------------------------------------------------------------
async def test_declarar_un_tipo_le_quita_la_marca_de_descubierto(client, auth, make_envelope):
    obras = await auth("obras")
    await client.post(
        "/api/v1/events",
        json=make_envelope(eventType="tipoNuevo", sourceModule="obras"),
        headers=obras,
    )
    assert (await client.get("/api/v1/event-types/tipoNuevo", headers=obras)).json()[
        "discovered"
    ] is True

    await client.post(
        "/api/v1/event-types",
        json={"name": "tipoNuevo", "description": "Ya lo documentamos."},
        headers=obras,
    )
    detail = (await client.get("/api/v1/event-types/tipoNuevo", headers=obras)).json()
    assert detail["discovered"] is False
    assert detail["description"] == "Ya lo documentamos."


async def test_rechaza_un_json_schema_invalido_al_declarar(client, auth):
    obras = await auth("obras")
    response = await client.post(
        "/api/v1/event-types",
        json={"name": "otroTipo", "jsonSchema": {"type": "no-existe"}},
        headers=obras,
    )
    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_JSON_SCHEMA"


async def test_el_mapa_muestra_quien_publica_y_quien_consume(client, auth):
    obras = await auth("obras")
    mapa = (await client.get("/api/v1/event-types/map", headers=obras)).json()
    fila = next(r for r in mapa if r["eventType"] == "ticketCreated")
    assert fila["publishedBy"] == ["atencion-ciudadana"]
    assert fila["consumedBy"] == ["obras"]


async def test_filtrar_tipos_descubiertos(client, auth, make_envelope):
    obras = await auth("obras")
    await client.post(
        "/api/v1/events",
        json=make_envelope(eventType="apareciSolo", sourceModule="obras"),
        headers=obras,
    )
    response = await client.get("/api/v1/event-types?discovered=true", headers=obras)
    assert [t["name"] for t in response.json()["items"]] == ["apareciSolo"]


async def test_un_tipo_inexistente_da_404(client, auth):
    response = await client.get("/api/v1/event-types/noExiste", headers=await auth("obras"))
    assert response.status_code == 404


# ----------------------------------------------------------------------
# Publicaciones
# ----------------------------------------------------------------------
async def test_declarar_una_publicacion(client, auth):
    obras = await auth("obras")
    response = await client.post(
        "/api/v1/publications", json={"eventType": "workOrderScheduled"}, headers=obras
    )
    assert response.status_code == 201
    assert response.json()["moduleName"] == "obras"


async def test_publicar_sin_haberlo_declarado_funciona_igual(client, auth, make_envelope):
    """La declaracion es documentacion, no un permiso."""
    obras = await auth("obras")
    response = await client.post(
        "/api/v1/events",
        json=make_envelope(eventType="workOrderScheduled", sourceModule="obras"),
        headers=obras,
    )
    assert response.status_code == 202


# ----------------------------------------------------------------------
# Modulos
# ----------------------------------------------------------------------
async def test_dar_de_alta_un_modulo_devuelve_el_secret_una_vez(client, auth):
    admin = await auth("core")
    response = await client.post(
        "/api/v1/modules",
        json={"name": "rentas", "displayName": "Rentas", "team": "Equipo 5"},
        headers=admin,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["module"] == "rentas"
    assert len(body["secret"]) > 30
    assert "no lo puede volver a mostrar" in body["warning"]


async def test_el_secret_nuevo_sirve_para_publicar(client, auth):
    """El secret de un modulo nuevo habilita el token de maquina, no el login."""
    admin = await auth("core")
    secret = (
        await client.post(
            "/api/v1/modules",
            json={"name": "rentas", "displayName": "Rentas"},
            headers=admin,
        )
    ).json()["secret"]

    token = await client.post(
        "/api/v1/auth/module-token", json={"module": "rentas", "secret": secret}
    )
    assert token.status_code == 200
    assert token.json()["kind"] == "module"
    assert token.json()["isAdmin"] is False


async def test_un_modulo_nuevo_no_tiene_cuentas_todavia(client, auth):
    """Dar de alta el modulo no crea personas: hay que crearlas aparte."""
    admin = await auth("core")
    await client.post(
        "/api/v1/modules", json={"name": "rentas", "displayName": "Rentas"}, headers=admin
    )

    cuentas = (await client.get("/api/v1/users", headers=admin)).json()
    assert [u for u in cuentas if u["moduleName"] == "rentas"] == []


async def test_un_modulo_comun_no_puede_dar_de_alta(client, auth):
    obras = await auth("obras")
    response = await client.post(
        "/api/v1/modules", json={"name": "x", "displayName": "X"}, headers=obras
    )
    assert response.status_code == 403


async def test_rotar_el_secret_invalida_el_anterior(client, auth):
    admin = await auth("core")
    nuevo = (await client.post("/api/v1/modules/obras/rotate-secret", headers=admin)).json()[
        "secret"
    ]

    viejo = await client.post(
        "/api/v1/auth/module-token",
        json={"module": "obras", "secret": MODULE_SECRET},
    )
    assert viejo.status_code == 401

    actual = await client.post(
        "/api/v1/auth/module-token", json={"module": "obras", "secret": nuevo}
    )
    assert actual.status_code == 200


async def test_rotar_el_secret_no_le_corta_el_dashboard_a_nadie(client, auth):
    """Es el punto de haber separado las dos credenciales: rotar la de maquina
    no obliga a que las personas vuelvan a pedir acceso."""
    admin = await auth("core")
    await client.post("/api/v1/modules/obras/rotate-secret", headers=admin)

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "obras@munitest.com", "password": USER_PASSWORD},
    )
    assert login.status_code == 200


async def test_dar_de_baja_un_modulo_impide_entrar(client, auth):
    admin = await auth("core")
    await client.patch("/api/v1/modules/obras", json={"active": False}, headers=admin)

    # Ni las personas ni el backend del equipo.
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "obras@munitest.com", "password": USER_PASSWORD},
    )
    assert login.status_code == 403
    assert login.json()["code"] == "MODULE_INACTIVE"

    token = await client.post(
        "/api/v1/auth/module-token",
        json={"module": "obras", "secret": MODULE_SECRET},
    )
    assert token.status_code == 403


async def test_un_modulo_de_baja_no_recibe_eventos(client, auth, make_envelope):
    """Sus suscripciones quedan declaradas para cuando vuelva."""
    admin = await auth("core")
    await client.patch("/api/v1/modules/obras", json={"active": False}, headers=admin)

    ac = await auth("atencion-ciudadana")
    response = await client.post("/api/v1/events", json=make_envelope(), headers=ac)
    assert response.json()["status"] == "NO_SUBSCRIBERS"

    subscriptions = (await client.get("/api/v1/subscriptions", headers=admin)).json()
    assert len(subscriptions) == 1  # sigue ahi


async def test_no_se_puede_dar_de_alta_un_nombre_repetido(client, auth):
    admin = await auth("core")
    response = await client.post(
        "/api/v1/modules", json={"name": "obras", "displayName": "Otra"}, headers=admin
    )
    assert response.status_code == 409


# ----------------------------------------------------------------------
# Topologia
# ----------------------------------------------------------------------
async def test_la_topologia_se_deriva_de_las_suscripciones(client, auth):
    obras = await auth("obras")
    topology = (await client.get("/api/v1/topology", headers=obras)).json()

    exchanges = {e["name"] for e in topology["exchanges"]}
    assert "muni.inbox" in exchanges and "muni.events" in exchanges and "muni.dlx" in exchanges

    colas = {q["name"] for q in topology["queues"]}
    assert "core.inbox" in colas and "q.dlq" in colas and "q.obras" in colas

    # Cada escalon de backoff con su TTL y su vuelta a muni.events.
    retry = next(
        q for q in topology["queues"] if q["name"] == retry_queue_for(settings.retry_delays[0])
    )
    assert retry["arguments"]["x-message-ttl"] == 5000
    assert retry["arguments"]["x-dead-letter-exchange"] == "muni.events"


async def test_la_cola_de_un_modulo_se_bindea_con_su_nombre(client, auth):
    obras = await auth("obras")
    topology = (await client.get("/api/v1/topology", headers=obras)).json()
    binding = next(b for b in topology["bindings"] if b["queue"] == "q.obras")
    assert binding["exchange"] == "muni.events"
    assert binding["routingKey"] == "q.obras"


async def test_aplicar_la_topologia_es_solo_del_admin(client, auth):
    comun = await client.post("/api/v1/topology/apply", headers=await auth("obras"))
    admin = await client.post("/api/v1/topology/apply", headers=await auth("core"))
    assert comun.status_code == 403
    assert admin.status_code == 200
