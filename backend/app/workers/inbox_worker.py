"""Consumidores del Core: `core.inbox` y `q.dlq`.

Se corre como proceso aparte del servidor de la API:

    python -m app.workers.inbox_worker

Son dos consumidores:

* **`core.inbox`** recibe todo lo que publican los 9 modulos, y por cada mensaje
  corre el pipeline del hub (idempotencia, estructura, evidencia, ruteo).
* **`q.dlq`** recibe lo que los consumidores rechazaron, y decide si programa el
  siguiente escalon de backoff o si abre una dead letter.
"""

from __future__ import annotations

import asyncio
import contextlib

import structlog

from app.core.config import settings
from app.core.context import set_trace_id
from app.core.database import SessionFactory, engine
from app.core.logging import configure_logging
from app.messaging.broker import HEADER_TRACE_ID, InboundMessage
from app.messaging.provider import connect_broker, get_broker
from app.messaging.topology import base_topology, full_topology
from app.models.events import IngestionChannel
from app.repositories.event_repository import (
    DeadLetterRepository,
    DeliveryRepository,
    EventLogRepository,
    RetryAuditRepository,
)
from app.repositories.registry_repository import (
    EventTypeRepository,
    ModuleRepository,
    SubscriptionRepository,
)
from app.services.delivery_service import DeliveryService
from app.services.envelope import EventEnvelope
from app.services.event_hub_service import EventHubService

logger = structlog.get_logger(__name__)

RETRY_SCAN_SECONDS = 30


async def _handle_inbox(message: InboundMessage) -> None:
    """Un mensaje de `core.inbox`: lo mete en el pipeline del hub."""
    set_trace_id(message.headers.get(HEADER_TRACE_ID))
    broker = get_broker()

    async with SessionFactory() as session:
        hub = EventHubService(
            event_log_repo=EventLogRepository(session),
            delivery_repo=DeliveryRepository(session),
            dead_letter_repo=DeadLetterRepository(session),
            event_type_repo=EventTypeRepository(session),
            subscription_repo=SubscriptionRepository(session),
            broker=broker,
        )
        try:
            envelope = EventEnvelope.model_validate(message.json())
        except Exception as exc:
            # No se puede rutear lo que no se entiende: se guarda el cuerpo crudo
            # para que quede constancia y se pueda inspeccionar.
            await hub.record_malformed(raw_body=message.text, queue=message.queue)
            await session.commit()
            logger.warning("inbox_malformed", error=str(exc))
            return

        result = await hub.ingest(envelope, channel=IngestionChannel.AMQP)

        module = await ModuleRepository(session).get_by_name(envelope.source_module)
        if module is not None:
            from app.core.database import utcnow

            module.last_publish_at = utcnow()

        await session.commit()
        logger.info(
            "inbox_processed",
            event_type=envelope.event_type,
            status=result.status,
            routed_to=result.routed_to,
        )


async def _handle_dlq(message: InboundMessage) -> None:
    """Un mensaje de `q.dlq`: lo rechazo su consumidor."""
    set_trace_id(message.headers.get(HEADER_TRACE_ID))
    broker = get_broker()

    async with SessionFactory() as session:
        hub = EventHubService(
            event_log_repo=EventLogRepository(session),
            delivery_repo=DeliveryRepository(session),
            dead_letter_repo=DeadLetterRepository(session),
            event_type_repo=EventTypeRepository(session),
            subscription_repo=SubscriptionRepository(session),
            broker=broker,
        )
        delivery_service = DeliveryService(
            delivery_repo=DeliveryRepository(session),
            dead_letter_repo=DeadLetterRepository(session),
            retry_audit_repo=RetryAuditRepository(session),
            event_log_repo=EventLogRepository(session),
            hub=hub,
            broker=broker,
        )
        await delivery_service.handle_dlq_message(message)
        await session.commit()


async def _retry_loop() -> None:
    """Completa las entregas que quedaron pendientes por un broker caido."""
    while True:
        await asyncio.sleep(RETRY_SCAN_SECONDS)
        broker = get_broker()
        try:
            async with SessionFactory() as session:
                hub = EventHubService(
                    event_log_repo=EventLogRepository(session),
                    delivery_repo=DeliveryRepository(session),
                    dead_letter_repo=DeadLetterRepository(session),
                    event_type_repo=EventTypeRepository(session),
                    subscription_repo=SubscriptionRepository(session),
                    broker=broker,
                )
                service = DeliveryService(
                    delivery_repo=DeliveryRepository(session),
                    dead_letter_repo=DeadLetterRepository(session),
                    retry_audit_repo=RetryAuditRepository(session),
                    event_log_repo=EventLogRepository(session),
                    hub=hub,
                    broker=broker,
                )
                await service.process_due_retries()
                await session.commit()
        except Exception as exc:
            # Un fallo del ciclo de reintentos no puede tumbar el worker.
            logger.warning("retry_loop_error", error=str(exc))


async def main() -> None:
    configure_logging()
    logger.info("worker_starting")

    if not await connect_broker():
        logger.error(
            "worker_cannot_start",
            hint="El broker no esta disponible. Con RABBITMQ_URL=memory:// no hay "
            "consumidores externos: usa RabbitMQ real para correr el worker.",
        )
        return

    broker = get_broker()
    async with SessionFactory() as session:
        queues = await SubscriptionRepository(session).active_queue_names()
    await broker.declare(base_topology())
    await broker.declare(full_topology(queues))

    await broker.consume(settings.queue_inbox, _handle_inbox, prefetch=16)
    await broker.consume(settings.queue_dlq, _handle_dlq, prefetch=8)
    logger.info("worker_ready", inbox=settings.queue_inbox, dlq=settings.queue_dlq)

    retry_task = asyncio.create_task(_retry_loop())
    try:
        await asyncio.Event().wait()
    finally:
        retry_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await retry_task
        await broker.close()
        await engine.dispose()


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
