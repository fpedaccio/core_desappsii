"""El pasamanos, de punta a punta por la API."""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.asyncio


async def test_publica_y_rutea_a_los_suscriptos(client, auth, make_envelope, broker):
    headers = await auth("atencion-ciudadana")
    response = await client.post("/api/v1/events", json=make_envelope(), headers=headers)

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "ROUTED"
    assert body["routedTo"] == ["obras"]
    # Y llego de verdad a la cola, no solo a la base.
    assert len(broker.messages_for("q.obras")) == 1


async def test_el_mismo_event_id_no_genera_efectos_nuevos(client, auth, make_envelope, broker):
    headers = await auth("atencion-ciudadana")
    envelope = make_envelope()

    first = await client.post("/api/v1/events", json=envelope, headers=headers)
    assert first.status_code == 202

    second = await client.post("/api/v1/events", json=envelope, headers=headers)
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    # La clave: no se volvio a publicar en la cola.
    assert len(broker.messages_for("q.obras")) == 1


async def test_un_tipo_sin_suscriptores_se_conserva(client, auth, make_envelope):
    """No es un error: es la señal de que falta una suscripcion o el nombre no
    coincide con el que espera el consumidor."""
    headers = await auth("atencion-ciudadana")
    response = await client.post(
        "/api/v1/events",
        json=make_envelope(eventType="workOrderScheduled", sourceModule="atencion-ciudadana"),
        headers=headers,
    )

    assert response.status_code == 202
    assert response.json()["status"] == "NO_SUBSCRIBERS"
    assert response.json()["accepted"] is True


async def test_un_tipo_desconocido_se_auto_registra(client, auth, make_envelope):
    """El pasamanos no traba la integracion por un nombre que nadie declaro."""
    headers = await auth("obras")
    response = await client.post(
        "/api/v1/events",
        json=make_envelope(eventType="algoQueNadieDeclaro", sourceModule="obras"),
        headers=headers,
    )

    assert response.status_code == 202
    assert response.json()["eventTypeDiscovered"] is True

    detail = await client.get("/api/v1/event-types/algoQueNadieDeclaro", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["discovered"] is True
    assert detail.json()["totalReceived"] == 1


async def test_no_se_puede_publicar_en_nombre_de_otro(client, auth, make_envelope):
    headers = await auth("obras")
    response = await client.post(
        "/api/v1/events",
        json=make_envelope(sourceModule="atencion-ciudadana"),
        headers=headers,
    )
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


async def test_rechaza_fecha_sin_zona_horaria(client, auth, make_envelope):
    headers = await auth("atencion-ciudadana")
    response = await client.post(
        "/api/v1/events",
        json=make_envelope(occurredAt="2026-09-08T10:00:00"),
        headers=headers,
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_sin_token_no_se_publica(client, make_envelope):
    response = await client.post("/api/v1/events", json=make_envelope())
    assert response.status_code == 401


async def test_valida_el_data_cuando_el_tipo_declara_schema(client, auth, make_envelope):
    admin = await auth("core")
    await client.put(
        "/api/v1/event-types/ticketCreated/schema",
        json={"jsonSchema": {"type": "object", "required": ["ticketId", "priority"]}},
        headers=admin,
    )

    headers = await auth("atencion-ciudadana")
    response = await client.post(
        "/api/v1/events", json=make_envelope(data={"ticketId": "TK-1"}), headers=headers
    )

    assert response.status_code == 422
    body = response.json()
    assert body["rejectionCode"] == "SCHEMA_VIOLATION"
    assert body["details"][0]["field"] == "priority"


async def test_quitar_el_schema_vuelve_a_dejar_pasar_todo(client, auth, make_envelope):
    admin = await auth("core")
    await client.put(
        "/api/v1/event-types/ticketCreated/schema",
        json={"jsonSchema": {"type": "object", "required": ["priority"]}},
        headers=admin,
    )
    await client.put(
        "/api/v1/event-types/ticketCreated/schema", json={"jsonSchema": None}, headers=admin
    )

    headers = await auth("atencion-ciudadana")
    response = await client.post("/api/v1/events", json=make_envelope(data={}), headers=headers)
    assert response.status_code == 202


async def test_lo_rechazado_queda_en_la_dlq(client, auth, make_envelope):
    """Nada se pierde: se guarda con el motivo y se puede reintentar."""
    admin = await auth("core")
    await client.put(
        "/api/v1/event-types/ticketCreated/schema",
        json={"jsonSchema": {"type": "object", "required": ["priority"]}},
        headers=admin,
    )

    headers = await auth("atencion-ciudadana")
    await client.post("/api/v1/events", json=make_envelope(data={}), headers=headers)

    dlq = await client.get("/api/v1/dlq", headers=admin)
    items = dlq.json()["items"]
    assert len(items) == 1
    assert items[0]["reasonCode"] == "SCHEMA_VIOLATION"
    assert items[0]["retryable"] is True


async def test_reintentar_tras_corregir_el_schema_reprocesa_el_evento(client, auth, make_envelope):
    """El camino que evita pedirle al modulo origen que republique."""
    admin = await auth("core")
    await client.put(
        "/api/v1/event-types/ticketCreated/schema",
        json={"jsonSchema": {"type": "object", "required": ["priority"]}},
        headers=admin,
    )

    headers = await auth("atencion-ciudadana")
    await client.post("/api/v1/events", json=make_envelope(data={}), headers=headers)

    # Se corrige la causa y se reintenta el evento ya guardado.
    await client.put(
        "/api/v1/event-types/ticketCreated/schema", json={"jsonSchema": None}, headers=admin
    )
    dead_letter_id = (await client.get("/api/v1/dlq", headers=admin)).json()["items"][0]["id"]
    retry = await client.post(f"/api/v1/dlq/{dead_letter_id}/retry", headers=admin)

    assert retry.status_code == 200
    assert retry.json()["success"] is True
    assert "obras" in retry.json()["message"]


async def test_el_reintento_queda_auditado(client, auth, make_envelope):
    admin = await auth("core")
    await client.put(
        "/api/v1/event-types/ticketCreated/schema",
        json={"jsonSchema": {"type": "object", "required": ["priority"]}},
        headers=admin,
    )
    headers = await auth("atencion-ciudadana")
    await client.post("/api/v1/events", json=make_envelope(data={}), headers=headers)
    await client.put(
        "/api/v1/event-types/ticketCreated/schema", json={"jsonSchema": None}, headers=admin
    )

    dead_letter_id = (await client.get("/api/v1/dlq", headers=admin)).json()["items"][0]["id"]
    await client.post(f"/api/v1/dlq/{dead_letter_id}/retry", headers=admin)

    audit = await client.get(f"/api/v1/dlq/{dead_letter_id}/audit", headers=admin)
    entries = audit.json()["items"]
    assert len(entries) == 1
    assert entries[0]["mode"] == "MANUAL"
    # La auditoria identifica a la **persona**, no al equipo: es el punto de
    # tener cuentas por integrante.
    assert entries[0]["actor"] == "core@munitest.com"
    assert entries[0]["result"] == "SUCCESS"


async def test_descartar_exige_motivo(client, auth, make_envelope):
    admin = await auth("core")
    await client.put(
        "/api/v1/event-types/ticketCreated/schema",
        json={"jsonSchema": {"type": "object", "required": ["priority"]}},
        headers=admin,
    )
    headers = await auth("atencion-ciudadana")
    await client.post("/api/v1/events", json=make_envelope(data={}), headers=headers)
    dead_letter_id = (await client.get("/api/v1/dlq", headers=admin)).json()["items"][0]["id"]

    sin_motivo = await client.post(
        f"/api/v1/dlq/{dead_letter_id}/discard", json={"reason": ""}, headers=admin
    )
    assert sin_motivo.status_code == 422

    con_motivo = await client.post(
        f"/api/v1/dlq/{dead_letter_id}/discard",
        json={"reason": "Evento de prueba del equipo 2, confirmado por Slack"},
        headers=admin,
    )
    assert con_motivo.status_code == 200
    assert con_motivo.json()["status"] == "DISCARDED"
    assert con_motivo.json()["resolvedBy"] == "core@munitest.com"


async def test_una_dlq_ya_resuelta_no_se_reintenta(client, auth, make_envelope):
    admin = await auth("core")
    await client.put(
        "/api/v1/event-types/ticketCreated/schema",
        json={"jsonSchema": {"type": "object", "required": ["priority"]}},
        headers=admin,
    )
    headers = await auth("atencion-ciudadana")
    await client.post("/api/v1/events", json=make_envelope(data={}), headers=headers)
    dead_letter_id = (await client.get("/api/v1/dlq", headers=admin)).json()["items"][0]["id"]
    await client.post(
        f"/api/v1/dlq/{dead_letter_id}/discard", json={"reason": "descartada"}, headers=admin
    )

    retry = await client.post(f"/api/v1/dlq/{dead_letter_id}/retry", headers=admin)
    assert retry.status_code == 409


async def test_la_journey_junta_los_eventos_por_correlation_id(client, auth, make_envelope):
    correlation = str(uuid.uuid4())
    ac = await auth("atencion-ciudadana")
    obras = await auth("obras")

    await client.post("/api/v1/events", json=make_envelope(correlationId=correlation), headers=ac)
    await client.post(
        "/api/v1/events",
        json=make_envelope(
            eventType="workOrderScheduled", sourceModule="obras", correlationId=correlation
        ),
        headers=obras,
    )

    admin = await auth("core")
    journey = await client.get(f"/api/v1/events/journey/{correlation}", headers=admin)

    assert journey.status_code == 200
    body = journey.json()
    assert body["eventCount"] == 2
    assert set(body["modulesInvolved"]) == {"atencion-ciudadana", "obras"}


async def test_el_detalle_trae_el_estado_de_cada_entrega(client, auth, make_envelope):
    headers = await auth("atencion-ciudadana")
    envelope = make_envelope()
    await client.post("/api/v1/events", json=envelope, headers=headers)

    detail = await client.get(f"/api/v1/events/{envelope['eventId']}", headers=headers)
    assert detail.status_code == 200
    deliveries = detail.json()["deliveries"]
    assert len(deliveries) == 1
    assert deliveries[0]["targetModule"] == "obras"
    assert deliveries[0]["status"] == "DELIVERED"
    assert deliveries[0]["attempts"] == 1


async def test_un_evento_inexistente_da_404(client, auth):
    headers = await auth("core")
    response = await client.get(f"/api/v1/events/{uuid.uuid4()}", headers=headers)
    assert response.status_code == 404
