"""El pasamanos de eventos.

Lo unico que hace el Core con un evento:

    1. **Idempotencia.** Si el `eventId` ya se vio, se marca duplicado y no se
       produce ningun efecto nuevo.
    2. **Estructura.** Se valida el sobre y, si el tipo declaro un JSON Schema,
       tambien el `data`. Lo que no cumple no se descarta: va a la DLQ con el
       detalle del campo.
    3. **Evidencia.** Se guarda el sobre tal cual llego.
    4. **Ruteo.** Se entrega a las suscripciones activas de ese tipo.

Lo que **no** hace: interpretar el significado del evento. No hay una sola rama
que dependa de que un ticket este resuelto o de que un permiso este aprobado.
Eso es de las areas, no del pasamanos.

Un tipo de evento que nadie declaro **no se rechaza**: se auto-registra y queda
marcado como `discovered` en el dashboard. Los equipos todavia estan alineando
nombres, y trabar la integracion por eso seria peor que dejarlo pasar y mostrarlo.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import structlog

from app.core.config import settings
from app.core.context import get_trace_id
from app.core.database import utcnow
from app.core.errors import ContractViolationError
from app.messaging.broker import (
    HEADER_ATTEMPT,
    HEADER_EVENT_ID,
    HEADER_TARGET,
    HEADER_TRACE_ID,
    Broker,
    OutboundMessage,
)
from app.models.events import (
    DeadLetter,
    Delivery,
    DeliveryStatus,
    EventLog,
    EventStatus,
    IngestionChannel,
)
from app.repositories.event_repository import (
    DeadLetterRepository,
    DeliveryRepository,
    EventLogRepository,
)
from app.repositories.registry_repository import (
    EventTypeRepository,
    SubscriptionRepository,
)
from app.services.envelope import EventEnvelope
from app.services.validation import validate_data

logger = structlog.get_logger(__name__)

REASON_SCHEMA_VIOLATION = "SCHEMA_VIOLATION"
REASON_MALFORMED_MESSAGE = "MALFORMED_MESSAGE"
REASON_DELIVERY_FAILED = "DELIVERY_FAILED"


@dataclass
class IngestResult:
    """Que paso con un evento que entro al hub."""

    event_log: EventLog
    status: EventStatus
    duplicate: bool = False
    routed_to: list[str] = field(default_factory=list)
    deferred_to: list[str] = field(default_factory=list)
    """Suscriptores a los que no se pudo publicar ahora; quedan para reintento."""
    already_delivered: list[str] = field(default_factory=list)
    event_type_discovered: bool = False
    """El tipo se registro solo en esta llamada: nadie lo habia declarado."""
    rejection_code: str | None = None
    rejection_reason: str | None = None
    details: list = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return self.status in {EventStatus.ROUTED, EventStatus.NO_SUBSCRIBERS}


class EventHubService:
    def __init__(
        self,
        *,
        event_log_repo: EventLogRepository,
        delivery_repo: DeliveryRepository,
        dead_letter_repo: DeadLetterRepository,
        event_type_repo: EventTypeRepository,
        subscription_repo: SubscriptionRepository,
        broker: Broker,
    ) -> None:
        self.event_log_repo = event_log_repo
        self.delivery_repo = delivery_repo
        self.dead_letter_repo = dead_letter_repo
        self.event_type_repo = event_type_repo
        self.subscription_repo = subscription_repo
        self.broker = broker

    # ------------------------------------------------------------------
    async def ingest(
        self,
        envelope: EventEnvelope,
        *,
        channel: IngestionChannel = IngestionChannel.AMQP,
    ) -> IngestResult:
        """Procesa un evento de punta a punta.

        No levanta excepciones por eventos invalidos: los registra, los manda a
        la DLQ y devuelve el resultado. Es deliberado: el llamador puede ser el
        consumidor de `core.inbox`, donde una excepcion significaria rechazar el
        mensaje al broker en vez de dejar constancia del problema.
        """
        started = utcnow()

        existing = await self.event_log_repo.get_by_event_id(envelope.event_id)
        if existing is not None:
            logger.info(
                "event_duplicate_ignored",
                event_id=str(envelope.event_id),
                event_type=envelope.event_type,
                first_seen_at=existing.received_at.isoformat(),
            )
            return IngestResult(
                event_log=existing,
                status=EventStatus.DUPLICATE,
                duplicate=True,
                routed_to=[d.target_module for d in existing.deliveries],
            )

        # Auto-registro: el tipo se crea si es la primera vez que aparece.
        event_type, discovered = await self.event_type_repo.get_or_create(
            envelope.event_type, source_module=envelope.source_module, seen_at=started
        )
        if discovered:
            logger.warning(
                "event_type_discovered",
                event_type=envelope.event_type,
                source_module=envelope.source_module,
                hint="Nadie lo habia declarado. Revisalo en el dashboard: puede "
                "ser un nombre desalineado entre equipos.",
            )

        event_log = self._build_log(envelope, channel=channel, received_at=started)

        # Validacion de estructura del payload, solo si el tipo declaro schema.
        try:
            validate_data(event_type.json_schema, envelope.data)
        except ContractViolationError as exc:
            return await self._reject(
                event_log,
                code=REASON_SCHEMA_VIOLATION,
                reason=exc.message,
                details=exc.details,
                started=started,
                discovered=discovered,
            )

        self.event_log_repo.add(event_log)
        await self.event_log_repo.flush()

        result = await self._route(event_log, envelope)
        result.event_type_discovered = discovered
        event_log.processing_ms = _elapsed_ms(started)
        return result

    def _build_log(
        self, envelope: EventEnvelope, *, channel: IngestionChannel, received_at: datetime
    ) -> EventLog:
        return EventLog(
            event_id=envelope.event_id,
            event_type=envelope.event_type,
            event_version=envelope.event_version,
            source_module=envelope.source_module,
            occurred_at=envelope.occurred_at,
            received_at=received_at,
            correlation_id=envelope.correlation_id,
            causation_id=envelope.causation_id,
            trace_id=get_trace_id(),
            envelope=envelope.to_wire(),
            ingestion_channel=channel,
            status=EventStatus.ROUTED,
            processing_ms=None,
        )

    # ------------------------------------------------------------------
    async def _route(self, event_log: EventLog, envelope: EventEnvelope) -> IngestResult:
        subscriptions = await self.subscription_repo.active_for_event_type(envelope.event_type)

        if not subscriptions:
            # Se conserva igual. Es la senal de que alguien publica algo que
            # nadie escucha: falta la suscripcion, o el nombre no coincide.
            event_log.status = EventStatus.NO_SUBSCRIBERS
            logger.info(
                "event_without_subscribers",
                event_id=str(envelope.event_id),
                event_type=envelope.event_type,
                source_module=envelope.source_module,
            )
            return IngestResult(event_log=event_log, status=EventStatus.NO_SUBSCRIBERS)

        # En un reproceso puede haber entregas previas: las confirmadas no se
        # repiten y las fallidas se reutilizan en lugar de duplicar la fila.
        existing = {
            d.target_module: d for d in await self.delivery_repo.list_for_event(event_log.id)
        }

        routed: list[str] = []
        deferred: list[str] = []
        skipped: list[str] = []

        for subscription in subscriptions:
            module_name = subscription.module.name
            delivery = existing.get(module_name)

            if delivery is not None and delivery.status == DeliveryStatus.DELIVERED:
                skipped.append(module_name)
                continue

            if delivery is None:
                delivery = Delivery(
                    event_log_id=event_log.id,
                    subscription_id=subscription.id,
                    target_module=module_name,
                    queue_name=subscription.target_queue,
                    event_type=envelope.event_type,
                    # Explicitos: el ruteo los lee y modifica antes del flush, y
                    # los defaults de columna recien se aplican en el INSERT.
                    status=DeliveryStatus.PENDING,
                    attempts=0,
                    max_attempts=subscription.max_attempts,
                )
                self.delivery_repo.add(delivery)

            published = await self._publish_to_queue(
                envelope, delivery=delivery, queue=subscription.target_queue
            )
            (routed if published else deferred).append(module_name)

        event_log.status = EventStatus.ROUTED
        event_log.rejection_code = None
        event_log.rejection_reason = None
        await self.delivery_repo.flush()

        logger.info(
            "event_routed",
            event_id=str(envelope.event_id),
            event_type=envelope.event_type,
            routed_to=routed,
            deferred_to=deferred,
        )
        return IngestResult(
            event_log=event_log,
            status=EventStatus.ROUTED,
            routed_to=routed,
            deferred_to=deferred,
            already_delivered=skipped,
        )

    async def _publish_to_queue(
        self, envelope: EventEnvelope, *, delivery: Delivery, queue: str
    ) -> bool:
        """Publica una entrega. Si el broker falla, la deja programada.

        Un broker caido no puede hacer fracasar la ingesta: el evento ya quedo
        persistido como evidencia y el reintento diferido lo completa despues.
        """
        delivery.attempts += 1
        try:
            await self.broker.publish(
                OutboundMessage(
                    exchange=settings.exchange_events,
                    # La routing key es el nombre de la cola destino: el ruteo lo
                    # decide el hub leyendo suscripciones, no un patron de topic.
                    routing_key=queue,
                    body=envelope.to_wire(),
                    headers={
                        HEADER_EVENT_ID: str(envelope.event_id),
                        HEADER_TARGET: delivery.target_module,
                        HEADER_TRACE_ID: get_trace_id(),
                        HEADER_ATTEMPT: delivery.attempts,
                    },
                    message_id=str(envelope.event_id),
                )
            )
        except Exception as exc:
            delivery.status = DeliveryStatus.RETRYING
            delivery.last_error = f"{type(exc).__name__}: {exc}"
            delivery.next_retry_at = utcnow() + timedelta(seconds=_delay_for(1))
            logger.warning(
                "delivery_publish_failed",
                event_id=str(envelope.event_id),
                target=delivery.target_module,
                error=str(exc),
            )
            return False

        delivery.status = DeliveryStatus.DELIVERED
        delivery.delivered_at = utcnow()
        return True

    # ------------------------------------------------------------------
    async def _reject(
        self,
        event_log: EventLog,
        *,
        code: str,
        reason: str,
        details: list,
        started: datetime,
        discovered: bool = False,
    ) -> IngestResult:
        """Registra el evento como rechazado y lo deja en la DLQ.

        Se persiste igual: nada se pierde. Desde el dashboard se ve el motivo y
        se puede reintentar una vez corregida la causa.
        """
        event_log.status = EventStatus.REJECTED
        event_log.rejection_code = code
        event_log.rejection_reason = reason
        event_log.processing_ms = _elapsed_ms(started)
        self.event_log_repo.add(event_log)
        await self.event_log_repo.flush()

        self.dead_letter_repo.add(
            DeadLetter(
                event_log_id=event_log.id,
                event_id=event_log.event_id,
                event_type=event_log.event_type,
                source_module=event_log.source_module,
                reason_code=code,
                reason=reason[:4000],
                details=details or None,
                raw_payload=event_log.envelope,
                attempts=1,
            )
        )
        logger.warning(
            "event_rejected",
            event_id=str(event_log.event_id),
            event_type=event_log.event_type,
            code=code,
        )
        return IngestResult(
            event_log=event_log,
            status=EventStatus.REJECTED,
            rejection_code=code,
            rejection_reason=reason,
            details=details,
            event_type_discovered=discovered,
        )

    async def record_malformed(self, *, raw_body: str, queue: str) -> DeadLetter:
        """Mensaje que ni siquiera es JSON valido, o al que le falta el sobre."""
        dead_letter = DeadLetter(
            reason_code=REASON_MALFORMED_MESSAGE,
            reason=f"Mensaje ilegible en la cola '{queue}'.",
            raw_body=raw_body[:20_000],
            attempts=1,
        )
        self.dead_letter_repo.add(dead_letter)
        logger.warning("malformed_message", queue=queue, preview=raw_body[:200])
        return dead_letter

    # ------------------------------------------------------------------
    async def reprocess(self, event_log: EventLog) -> IngestResult:
        """Vuelve a validar y rutear un evento ya persistido.

        Es el camino del reintento cuando la causa era del lado del Core: faltaba
        la suscripcion o el schema estaba mal. Se corrige y el mismo evento se
        reprocesa, sin pedirle al modulo origen que lo publique de nuevo.
        """
        envelope = EventEnvelope.model_validate(event_log.envelope)
        event_type = await self.event_type_repo.get_by_name(envelope.event_type)

        try:
            validate_data(event_type.json_schema if event_type else None, envelope.data)
        except ContractViolationError as exc:
            event_log.status = EventStatus.REJECTED
            event_log.rejection_code = REASON_SCHEMA_VIOLATION
            event_log.rejection_reason = exc.message
            return IngestResult(
                event_log=event_log,
                status=EventStatus.REJECTED,
                rejection_code=REASON_SCHEMA_VIOLATION,
                rejection_reason=exc.message,
                details=exc.details,
            )

        return await self._route(event_log, envelope)

    async def journey(self, correlation_id: uuid.UUID) -> list[EventLog]:
        return await self.event_log_repo.by_correlation(correlation_id)


def _delay_for(attempt: int) -> int:
    delays = settings.retry_delays or [5]
    return delays[min(max(attempt, 1), len(delays)) - 1]


def _elapsed_ms(started: datetime) -> int:
    return max(int((utcnow() - started).total_seconds() * 1000), 0)
