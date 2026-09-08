"""Reintentos con backoff y DLQ, desde el lado del broker.

Estos tests van directo al servicio, no por HTTP: lo que se ejercita es el
camino que arranca cuando un modulo consumidor **rechaza** un mensaje, que por
HTTP no se puede provocar.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from app.core.context import set_actor
from app.messaging.broker import (
    HEADER_ATTEMPT,
    HEADER_ERROR,
    HEADER_EVENT_ID,
    HEADER_TARGET,
    InboundMessage,
    OutboundMessage,
)
from app.models.events import DeadLetterStatus, DeliveryStatus
from app.repositories.event_repository import (
    DeadLetterRepository,
    DeliveryRepository,
    EventLogRepository,
    RetryAuditRepository,
)
from app.repositories.registry_repository import EventTypeRepository, SubscriptionRepository
from app.services.delivery_service import DeliveryService
from app.services.envelope import EventEnvelope
from app.services.event_hub_service import EventHubService

pytestmark = pytest.mark.asyncio


def _envelope(**overrides) -> EventEnvelope:
    base = {
        "eventId": str(uuid.uuid4()),
        "eventType": "ticketCreated",
        "occurredAt": "2026-09-08T10:00:00-03:00",
        "sourceModule": "atencion-ciudadana",
        "data": {"ticketId": "TK-1"},
    }
    base.update(overrides)
    return EventEnvelope.model_validate(base)


@pytest_asyncio.fixture
async def services(session_factory, broker, seeded):
    """Hub y servicio de entregas sobre una sesion propia."""
    session = session_factory()
    hub = EventHubService(
        event_log_repo=EventLogRepository(session),
        delivery_repo=DeliveryRepository(session),
        dead_letter_repo=DeadLetterRepository(session),
        event_type_repo=EventTypeRepository(session),
        subscription_repo=SubscriptionRepository(session),
        broker=broker,
    )
    delivery = DeliveryService(
        delivery_repo=DeliveryRepository(session),
        dead_letter_repo=DeadLetterRepository(session),
        retry_audit_repo=RetryAuditRepository(session),
        event_log_repo=EventLogRepository(session),
        hub=hub,
        broker=broker,
    )
    set_actor("core")
    yield {"session": session, "hub": hub, "delivery": delivery, "broker": broker}
    await session.close()


def _rejection(envelope: EventEnvelope, *, attempt: int, error: str = "la DB del consumidor cayo"):
    """El mensaje tal como llega a `q.dlq` cuando un consumidor hace nack."""
    return InboundMessage(
        queue="q.dlq",
        routing_key="q.obras",
        raw=OutboundMessage(
            exchange="muni.events", routing_key="q.obras", body=envelope.to_wire()
        ).encoded(),
        headers={
            HEADER_EVENT_ID: str(envelope.event_id),
            HEADER_TARGET: "obras",
            HEADER_ATTEMPT: attempt,
            HEADER_ERROR: error,
        },
    )


# ----------------------------------------------------------------------
async def test_un_rechazo_programa_el_primer_escalon_de_backoff(services):
    envelope = _envelope()
    await services["hub"].ingest(envelope)
    await services["session"].flush()
    services["broker"].reset()

    result = await services["delivery"].handle_dlq_message(_rejection(envelope, attempt=1))

    # Todavia le quedan intentos: no abre dead letter.
    assert result is None
    # Y se publico en el exchange del escalon de 5s.
    assert services["broker"].routing_keys("muni.retry.5s") == ["q.obras"]


async def test_cada_rechazo_sube_de_escalon(services):
    envelope = _envelope()
    await services["hub"].ingest(envelope)
    await services["session"].flush()

    esperados = ["muni.retry.5s", "muni.retry.30s", "muni.retry.2m"]
    for exchange in esperados:
        services["broker"].reset()
        await services["delivery"].handle_dlq_message(_rejection(envelope, attempt=1))
        assert services["broker"].routing_keys(exchange) == ["q.obras"], exchange


async def test_agotados_los_intentos_abre_una_dead_letter(services):
    envelope = _envelope()
    await services["hub"].ingest(envelope)
    await services["session"].flush()

    # maxAttempts=4 y la entrega ya consumio 1 al publicarse.
    result = None
    for _ in range(4):
        result = await services["delivery"].handle_dlq_message(_rejection(envelope, attempt=1))

    assert result is not None
    assert result.reason_code == "DELIVERY_FAILED"
    assert result.status == DeadLetterStatus.OPEN
    assert result.target_module == "obras"
    assert "la DB del consumidor cayo" in result.reason

    delivery = await DeliveryRepository(services["session"]).find_for_event_and_module(
        result.event_log_id, "obras"
    )
    assert delivery.status == DeliveryStatus.DEAD
    assert delivery.next_retry_at is None


async def test_los_reintentos_automaticos_quedan_auditados(services):
    envelope = _envelope()
    await services["hub"].ingest(envelope)
    await services["session"].flush()

    for _ in range(2):
        await services["delivery"].handle_dlq_message(_rejection(envelope, attempt=1))
    await services["session"].flush()

    audit = await RetryAuditRepository(services["session"]).search(event_id=envelope.event_id)
    assert audit.total == 2
    assert all(entry.mode == "AUTOMATIC" for entry in audit.items)
    assert all(entry.actor == "system" for entry in audit.items)


async def test_un_mensaje_ilegible_se_guarda_con_el_cuerpo_crudo(services):
    """No se puede reintentar lo que no se entiende, pero tampoco se pierde."""
    message = InboundMessage(
        queue="q.dlq", routing_key="q.obras", raw=b"esto no es json {{{", headers={}
    )

    result = await services["delivery"].handle_dlq_message(message)

    assert result.reason_code == "MALFORMED_MESSAGE"
    assert result.raw_body == "esto no es json {{{"
    assert result.event_id is None


async def test_un_mensaje_ilegible_no_se_puede_reintentar(services):
    from app.core.errors import ConflictError

    message = InboundMessage(queue="q.dlq", routing_key="q.obras", raw=b"{{{", headers={})
    dead_letter = await services["delivery"].handle_dlq_message(message)
    await services["session"].flush()

    with pytest.raises(ConflictError) as exc:
        await services["delivery"].retry_dead_letter(dead_letter.id)
    assert "malformado" in str(exc.value)


async def test_un_rechazo_sin_entrega_correlacionada_se_guarda_igual(services):
    """Llega un mensaje a la DLQ que no matchea ninguna entrega registrada."""
    envelope = _envelope()
    result = await services["delivery"].handle_dlq_message(_rejection(envelope, attempt=1))

    assert result is not None
    assert result.status == DeadLetterStatus.OPEN
    assert "no se pudo correlacionar" in result.reason.lower()


# ----------------------------------------------------------------------
# Broker caido
# ----------------------------------------------------------------------
async def test_si_el_broker_falla_el_evento_igual_se_persiste(services):
    """La ingesta no puede fracasar por el broker: el evento ya es evidencia."""
    services["broker"]._fail_on_publish = True
    envelope = _envelope()

    result = await services["hub"].ingest(envelope)
    await services["session"].flush()

    assert result.status == "ROUTED"
    assert result.routed_to == []
    assert result.deferred_to == ["obras"]

    stored = await EventLogRepository(services["session"]).get_by_event_id(envelope.event_id)
    assert stored is not None
    assert stored.deliveries[0].status == DeliveryStatus.RETRYING
    assert stored.deliveries[0].next_retry_at is not None


async def test_al_volver_el_broker_se_completan_las_entregas_diferidas(services):
    services["broker"]._fail_on_publish = True
    envelope = _envelope()
    await services["hub"].ingest(envelope)
    await services["session"].flush()

    # El broker vuelve, y el backoff de la entrega ya vencio.
    services["broker"]._fail_on_publish = False
    delivery = (
        await EventLogRepository(services["session"]).get_by_event_id(envelope.event_id)
    ).deliveries[0]
    from app.core.database import utcnow

    delivery.next_retry_at = utcnow()
    await services["session"].flush()

    procesadas = await services["delivery"].process_due_retries()

    assert procesadas == 1
    assert delivery.status == DeliveryStatus.DELIVERED
    assert delivery.next_retry_at is None
    assert services["broker"].messages_for("q.obras")


async def test_sin_broker_los_reintentos_diferidos_esperan(services):
    from app.core.errors import ExternalUnavailableError

    await services["broker"].close()
    with pytest.raises(ExternalUnavailableError):
        await services["delivery"].process_due_retries()


# ----------------------------------------------------------------------
# Reintento manual
# ----------------------------------------------------------------------
async def test_el_reintento_manual_republica_en_la_cola_del_destino(services):
    envelope = _envelope()
    await services["hub"].ingest(envelope)
    await services["session"].flush()
    for _ in range(4):
        dead_letter = await services["delivery"].handle_dlq_message(
            _rejection(envelope, attempt=1)
        )
    await services["session"].flush()
    services["broker"].reset()

    outcome = await services["delivery"].retry_dead_letter(dead_letter.id)

    assert outcome.success
    assert "q.obras" in outcome.message
    assert services["broker"].routing_keys("muni.events") == ["q.obras"]


async def test_el_reintento_manual_reinicia_el_contador(services):
    envelope = _envelope()
    await services["hub"].ingest(envelope)
    await services["session"].flush()
    for _ in range(4):
        dead_letter = await services["delivery"].handle_dlq_message(
            _rejection(envelope, attempt=1)
        )
    await services["session"].flush()

    await services["delivery"].retry_dead_letter(dead_letter.id)

    delivery = await DeliveryRepository(services["session"]).get(dead_letter.delivery_id)
    assert delivery.status == DeliveryStatus.DELIVERED
    assert delivery.attempts == 1


async def test_el_reintento_masivo_audita_cada_uno_por_separado(services):
    ids = []
    for _ in range(3):
        envelope = _envelope()
        await services["hub"].ingest(envelope)
        await services["session"].flush()
        for _ in range(4):
            dead_letter = await services["delivery"].handle_dlq_message(
                _rejection(envelope, attempt=1)
            )
        # El id lo asigna SQLAlchemy en el INSERT, asi que hay que empujar los
        # cambios antes de leerlo.
        await services["session"].flush()
        ids.append(dead_letter.id)

    outcome = await services["delivery"].retry_many([*ids, uuid.uuid4()])

    assert outcome.total == 4
    assert outcome.succeeded == 3
    assert outcome.failed == 1  # el uuid inventado


async def test_descartar_marca_la_entrega_como_descartada(services):
    envelope = _envelope()
    await services["hub"].ingest(envelope)
    await services["session"].flush()
    for _ in range(4):
        dead_letter = await services["delivery"].handle_dlq_message(
            _rejection(envelope, attempt=1)
        )
    await services["session"].flush()

    await services["delivery"].discard_dead_letter(dead_letter.id, reason="Prueba del equipo 2")

    assert dead_letter.status == DeadLetterStatus.DISCARDED
    assert dead_letter.resolved_by == "core"
    delivery = await DeliveryRepository(services["session"]).get(dead_letter.delivery_id)
    assert delivery.status == DeliveryStatus.DISCARDED
