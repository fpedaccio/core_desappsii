"""Comportamientos que la prueba de mutacion de QA (T6) mostro sin verificar.

Cada test cubre datos que el Core guarda o devuelve y que ningun test miraba:
si se rompian (un campo que queda en None, una condicion invertida), la suite
seguia pasando.
"""

from __future__ import annotations

import uuid

from app.messaging.broker import HEADER_ATTEMPT, HEADER_EVENT_ID, HEADER_TARGET

SCHEMA_ESTRICTO = {"type": "object", "required": ["priority"]}


async def _rechazar(client, auth, make_envelope):
    """Un ticketCreated que no cumple el schema: queda en la DLQ."""
    admin = await auth("core")
    await client.put(
        "/api/v1/event-types/ticketCreated/schema",
        json={"jsonSchema": SCHEMA_ESTRICTO},
        headers=admin,
    )
    origen = await auth("atencion-ciudadana")
    sobre = make_envelope(data={})
    await client.post("/api/v1/events", json=sobre, headers=origen)
    dead_letter = (await client.get("/api/v1/dlq", headers=admin)).json()["items"][0]
    return admin, origen, sobre, dead_letter


# ----------------------------------------------------------------------
# Evidencia del evento
# ----------------------------------------------------------------------
async def test_el_evento_guarda_version_causa_y_canal(client, auth, make_envelope):
    causa, correlacion = str(uuid.uuid4()), str(uuid.uuid4())
    sobre = make_envelope(eventVersion="2.1", causationId=causa, correlationId=correlacion)
    headers = await auth("atencion-ciudadana")

    assert (await client.post("/api/v1/events", json=sobre, headers=headers)).status_code == 202
    detalle = (await client.get(f"/api/v1/events/{sobre['eventId']}", headers=headers)).json()

    assert detalle["eventVersion"] == "2.1"
    assert detalle["causationId"] == causa
    assert detalle["correlationId"] == correlacion
    assert detalle["ingestionChannel"] == "HTTP"
    assert detalle["status"] == "ROUTED"
    assert detalle["traceId"]


async def test_el_mensaje_entregado_lleva_el_sobre_y_sus_cabeceras(
    client, auth, make_envelope, broker
):
    sobre = make_envelope()
    await client.post("/api/v1/events", json=sobre, headers=await auth("atencion-ciudadana"))

    mensajes = [m for m in broker.published if m.message_id == sobre["eventId"]]
    assert len(mensajes) == 1
    mensaje = mensajes[0]
    assert mensaje.routing_key == "q.obras"
    assert mensaje.body["eventId"] == sobre["eventId"]
    assert mensaje.body["data"] == sobre["data"]
    assert mensaje.headers[HEADER_EVENT_ID] == sobre["eventId"]
    assert mensaje.headers[HEADER_TARGET] == "obras"
    assert mensaje.headers[HEADER_ATTEMPT] == 1


async def test_el_duplicado_informa_a_quien_se_ruteo(client, auth, make_envelope):
    sobre = make_envelope()
    headers = await auth("atencion-ciudadana")
    await client.post("/api/v1/events", json=sobre, headers=headers)

    duplicado = await client.post("/api/v1/events", json=sobre, headers=headers)

    assert duplicado.status_code == 200
    assert duplicado.json()["duplicate"] is True
    assert duplicado.json()["routedTo"] == ["obras"]


# ----------------------------------------------------------------------
# Dead letters
# ----------------------------------------------------------------------
async def test_la_dead_letter_de_schema_guarda_origen_y_payload(client, auth, make_envelope):
    admin, origen, sobre, dead_letter = await _rechazar(client, auth, make_envelope)

    detalle = (await client.get(f"/api/v1/dlq/{dead_letter['id']}", headers=admin)).json()
    assert detalle["sourceModule"] == "atencion-ciudadana"
    assert detalle["eventId"] == sobre["eventId"]
    assert detalle["eventType"] == "ticketCreated"
    assert detalle["reasonCode"] == "SCHEMA_VIOLATION"
    assert detalle["attempts"] == 1
    assert detalle["rawPayload"]["eventId"] == sobre["eventId"]
    assert detalle["details"]

    # El alcance por modulo depende de sourceModule: el origen la tiene que ver.
    propias = (await client.get("/api/v1/dlq", headers=origen)).json()["items"]
    assert dead_letter["id"] in [d["id"] for d in propias]


async def test_reintentar_sin_corregir_el_schema_lo_deja_rechazado(client, auth, make_envelope):
    admin, _, sobre, dead_letter = await _rechazar(client, auth, make_envelope)

    retry = await client.post(f"/api/v1/dlq/{dead_letter['id']}/retry", headers=admin)

    assert retry.status_code == 200
    assert retry.json()["success"] is False
    evento = (await client.get(f"/api/v1/events/{sobre['eventId']}", headers=admin)).json()
    assert evento["status"] == "REJECTED"
    assert evento["rejectionCode"] == "SCHEMA_VIOLATION"
    assert evento["rejectionReason"]
    assert evento["deliveries"] == []
    estado = (await client.get(f"/api/v1/dlq/{dead_letter['id']}", headers=admin)).json()
    assert estado["status"] == "OPEN"


# ----------------------------------------------------------------------
# Registry
# ----------------------------------------------------------------------
async def test_resuscribirse_reactiva_una_suscripcion_pausada(client, auth):
    obras = await auth("obras")
    subscription_id = (await client.get("/api/v1/subscriptions", headers=obras)).json()[0]["id"]
    await client.post(f"/api/v1/subscriptions/{subscription_id}/toggle?active=false", headers=obras)

    response = await client.post(
        "/api/v1/subscriptions", json={"eventType": "ticketCreated"}, headers=obras
    )

    assert response.status_code == 201
    assert response.json()["id"] == subscription_id
    assert response.json()["active"] is True


async def test_dar_de_alta_un_modulo_guarda_sus_datos(client, auth):
    admin = await auth("core")
    alta = await client.post(
        "/api/v1/modules",
        json={
            "name": "qa-mutacion",
            "displayName": "QA Mutacion",
            "team": "Equipo QA",
            "description": "Modulo de prueba",
            "contactEmail": "qa@example.com",
        },
        headers=admin,
    )
    assert alta.status_code == 201

    modulo = next(
        m
        for m in (await client.get("/api/v1/modules", headers=admin)).json()
        if m["name"] == "qa-mutacion"
    )
    assert modulo["team"] == "Equipo QA"
    assert modulo["description"] == "Modulo de prueba"
    assert modulo["contactEmail"] == "qa@example.com"
    assert modulo["queueName"] == "q.qa-mutacion"
    assert modulo["active"] is True
    assert modulo["isAdmin"] is False


async def test_editar_un_modulo_actualiza_solo_lo_enviado(client, auth):
    admin = await auth("core")
    editado = await client.patch(
        "/api/v1/modules/obras",
        json={
            "displayName": "Obras editado",
            "team": "Equipo Obras",
            "description": "Nueva descripcion",
            "contactEmail": "obras@example.com",
        },
        headers=admin,
    )
    assert editado.status_code == 200
    assert editado.json()["displayName"] == "Obras editado"
    assert editado.json()["team"] == "Equipo Obras"
    assert editado.json()["description"] == "Nueva descripcion"
    assert editado.json()["contactEmail"] == "obras@example.com"

    parcial = await client.patch(
        "/api/v1/modules/obras", json={"displayName": "Obras"}, headers=admin
    )
    assert parcial.json()["displayName"] == "Obras"
    assert parcial.json()["contactEmail"] == "obras@example.com"
    assert parcial.json()["team"] == "Equipo Obras"


async def test_redeclarar_un_tipo_con_schema_nuevo_lo_reemplaza(client, auth):
    obras = await auth("obras")
    primero = {"type": "object", "required": ["a"]}
    segundo = {"type": "object", "required": ["b"]}
    await client.post(
        "/api/v1/event-types", json={"name": "tipoQa", "jsonSchema": primero}, headers=obras
    )

    await client.post(
        "/api/v1/event-types", json={"name": "tipoQa", "jsonSchema": segundo}, headers=obras
    )
    assert (await client.get("/api/v1/event-types/tipoQa", headers=obras)).json()[
        "jsonSchema"
    ] == segundo

    # Redeclarar sin schema no borra el que tenia.
    await client.post("/api/v1/event-types", json={"name": "tipoQa"}, headers=obras)
    assert (await client.get("/api/v1/event-types/tipoQa", headers=obras)).json()[
        "jsonSchema"
    ] == segundo


async def test_crear_una_cuenta_normaliza_el_nombre_del_modulo(client, auth):
    response = await client.post(
        "/api/v1/users",
        json={
            "email": "nueva@munitest.com",
            "fullName": "Cuenta Nueva",
            "password": "Clave12345",
            "module": "OBRAS",
        },
        headers=await auth("core"),
    )

    assert response.status_code == 201
    assert response.json()["moduleName"] == "obras"
