"""El HUB de eventos: ingesta, validacion, evidencia y ruteo.

Es el corazon del modulo Core. Todo evento de la plataforma pasa por aca:

    1. **Idempotencia.** Si el `eventId` ya se vio, se registra como duplicado y
       no se produce ningun efecto nuevo (regla 1).
    2. **Contrato.** Se resuelve el tipo de evento en el catalogo y se valida el
       `data` contra el JSON Schema de su version. Lo que no cumple *no se
       descarta*: queda en la DLQ con el motivo (regla 2).
    3. **Evidencia.** Se persiste el sobre tal cual llego, con su traza (regla 3).
    4. **Ruteo.** Se entrega a las suscripciones activas, y solo a esas.

Lo que este servicio **no** hace: interpretar el contenido de `data`. No hay una
sola rama que dependa de que un reclamo sea urgente o de que una habilitacion
este aprobada. Esa es la linea que fija la seccion 9 del enunciado ("el Core no
implementara reglas de negocio de las demas areas") y es lo que mantiene al hub
generico para los 8 modulos restantes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import structlog

from app.core.config import settings
from app.core.context import get_trace_id
from app.core.database import utcnow
from app.core.errors import ContractViolationError, NotFoundError
from app.messaging.broker import (
    HEADER_ATTEMPT,
    HEADER_EVENT_ID,
    HEADER_TARGET,
    HEADER_TRACE_ID,
    Broker,
    OutboundMessage,
)
from app.models.contracts import EventType
from app.models.events import (
    DeadLetter,
    DeadLetterStatus,
    Delivery,
    DeliveryStatus,
    EventLog,
    EventStatus,
    IngestionChannel,
)
from app.repositories.contract_repository import (
    ContractVersionRepository,
    EventTypeRepository,
    SubscriptionRepository,
)
from app.repositories.event_repository import (
    DeadLetterRepository,
    DeliveryRepository,
    EventLogRepository,
)
from app.services.envelope import EventEnvelope
from app.services.schema_compat import validate_payload

logger = structlog.get_logger(__name__)

REASON_UNKNOWN_EVENT_TYPE = "UNKNOWN_EVENT_TYPE"
REASON_UNKNOWN_CONTRACT_VERSION = "UNKNOWN_CONTRACT_VERSION"
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
    """Suscriptores que ya tenian el evento (solo ocurre en un reproceso)."""
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
        version_repo: ContractVersionRepository,
        subscription_repo: SubscriptionRepository,
        broker: Broker,
    ) -> None:
        self.event_log_repo = event_log_repo
        self.delivery_repo = delivery_repo
        self.dead_letter_repo = dead_letter_repo
        self.event_type_repo = event_type_repo
        self.version_repo = version_repo
        self.subscription_repo = subscription_repo
        self.broker = broker

    # ------------------------------------------------------------------
    # Ingesta
    # ------------------------------------------------------------------
    async def ingest(
        self,
        envelope: EventEnvelope,
        *,
        channel: IngestionChannel = IngestionChannel.AMQP,
    ) -> IngestResult:
        """Procesa un evento de punta a punta.

        No levanta excepciones por eventos invalidos: los registra, los manda a
        la DLQ y devuelve el resultado. Es deliberado - el llamador puede ser el
        consumidor de `core.inbox`, y ahi una excepcion significaria rechazar el
        mensaje al broker en lugar de dejar constancia del problema.
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

        event_log = self._build_log(envelope, channel=channel, received_at=started)

        try:
            event_type = await self._resolve_contract(envelope)
        except (NotFoundError, ContractViolationError) as exc:
            return await self._reject(
                event_log,
                code=getattr(exc, "code", REASON_SCHEMA_VIOLATION),
                reason=exc.message,
                details=getattr(exc, "details", []),
                started=started,
            )

        self.event_log_repo.add(event_log)
        await self.event_log_repo.flush()

        result = await self._route(event_log, envelope, event_type)
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
            # El sobre se guarda tal cual llego: es la evidencia y no se reescribe.
            envelope=envelope.to_wire(),
            ingestion_channel=channel,
            status=EventStatus.RECEIVED,
        )

    async def _resolve_contract(self, envelope: EventEnvelope) -> EventType:
        """Busca el tipo en el catalogo y valida el payload contra su schema.

        Un tipo no registrado se rechaza: sin catalogo el hub tampoco sabria a
        quien entregarlo. El operador lo registra y reintenta desde el panel.
        """
        event_type = await self.event_type_repo.get_by_name(envelope.event_type)
        if event_type is None:
            raise NotFoundError(
                f"El tipo de evento '{envelope.event_type}' no esta registrado en el "
                "catalogo. Registralo y reintenta el mensaje desde la DLQ.",
                code=REASON_UNKNOWN_EVENT_TYPE,
            )

        version = await self.version_repo.get_version(event_type.id, envelope.event_version)
        if version is None:
            available = ", ".join(v.version for v in event_type.versions) or "ninguna"
            raise NotFoundError(
                f"El tipo '{envelope.event_type}' no tiene una version "
                f"'{envelope.event_version}'. Versiones declaradas: {available}.",
                code=REASON_UNKNOWN_CONTRACT_VERSION,
            )

        validate_payload(version.json_schema, envelope.data)
        return event_type

    # ------------------------------------------------------------------
    # Ruteo
    # ------------------------------------------------------------------
    async def _route(
        self, event_log: EventLog, envelope: EventEnvelope, event_type: EventType
    ) -> IngestResult:
        subscriptions = await self.subscription_repo.active_for_event_type(event_type.name)

        if not subscriptions:
            # Se conserva igual: manana alguien se suscribe y el evento ya es
            # evidencia de que el hecho ocurrio.
            event_log.status = EventStatus.NO_SUBSCRIBERS
            logger.info(
                "event_without_subscribers",
                event_id=str(envelope.event_id),
                event_type=envelope.event_type,
            )
            return IngestResult(event_log=event_log, status=EventStatus.NO_SUBSCRIBERS)

        # En un reproceso puede haber entregas previas: las ya confirmadas no se
        # repiten (seria entregar el mismo evento dos veces al mismo modulo) y
        # las fallidas se reutilizan en lugar de duplicar la fila.
        existing = {
            delivery.target_module: delivery
            for delivery in await self.delivery_repo.list_for_event(event_log.id)
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
                    max_attempts=subscription.max_attempts or 4,
                    # attempts y status se pasan explicitos porque el ruteo los
                    # lee y modifica antes del flush, y los defaults de columna
                    # de SQLAlchemy recien se aplican al INSERT.
                    attempts=0,
                    status=DeliveryStatus.PENDING,
                )
                self.delivery_repo.add(delivery)

            published = await self._publish_to_queue(
                envelope, delivery=delivery, queue=subscription.target_queue
            )
            if published:
                routed.append(module_name)
            else:
                deferred.append(module_name)

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
            already_delivered=skipped,
        )
        return IngestResult(
            event_log=event_log,
            status=EventStatus.ROUTED,
            routed_to=routed,
            deferred_to=deferred,
            already_delivered=skipped,
        )

    # ------------------------------------------------------------------
    # Reproceso
    # ------------------------------------------------------------------
    async def reprocess(self, event_log: EventLog) -> IngestResult:
        """Vuelve a validar y rutear un evento ya persistido.

        Es el camino del reintento manual cuando la causa del rechazo era del
        lado del Core: faltaba registrar el tipo de evento o el schema estaba
        mal. Se corrige la configuracion y el mismo evento se reprocesa, sin
        pedirle al modulo origen que lo publique de nuevo.
        """
        envelope = EventEnvelope.model_validate(event_log.envelope)

        try:
            event_type = await self._resolve_contract(envelope)
        except (NotFoundError, ContractViolationError) as exc:
            code = getattr(exc, "code", REASON_SCHEMA_VIOLATION)
            event_log.status = EventStatus.REJECTED
            event_log.rejection_code = code
            event_log.rejection_reason = exc.message
            logger.info(
                "reprocess_still_invalid",
                event_id=str(envelope.event_id),
                code=code,
            )
            return IngestResult(
                event_log=event_log,
                status=EventStatus.REJECTED,
                rejection_code=code,
                rejection_reason=exc.message,
                details=getattr(exc, "details", []),
            )

        return await self._route(event_log, envelope, event_type)

    async def _publish_to_queue(
        self, envelope: EventEnvelope, *, delivery: Delivery, queue: str
    ) -> bool:
        """Publica una entrega. Si el broker falla, la deja programada para reintento.

        Un broker caido no puede hacer fracasar la ingesta: el evento ya quedo
        persistido como evidencia y el planificador de reintentos se encarga
        despues. Esa es la tolerancia a indisponibilidad que pide la regla 6.
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
            delivery.next_retry_at = utcnow() + timedelta(seconds=self._delay_for(1))
            logger.warning(
                "delivery_publish_failed",
                event_id=str(envelope.event_id),
                target=delivery.target_module,
                error=str(exc),
                next_retry_at=delivery.next_retry_at.isoformat(),
            )
            return False

        delivery.status = DeliveryStatus.DELIVERED
        delivery.delivered_at = utcnow()
        return True

    def _delay_for(self, attempt: int) -> int:
        delays = settings.retry_delays or [5]
        return delays[min(attempt, len(delays)) - 1]

    # ------------------------------------------------------------------
    # Rechazos
    # ------------------------------------------------------------------
    async def _reject(
        self,
        event_log: EventLog,
        *,
        code: str,
        reason: str,
        details: list,
        started: datetime,
    ) -> IngestResult:
        """Registra el evento como rechazado y lo deja en la DLQ.

        Se persiste igual: "los mensajes fallidos no deberan perderse". Desde el
        panel se corrige la causa y se reintenta.
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
                reason=_with_details(reason, details),
                raw_payload=event_log.envelope,
                attempts=1,
                status=DeadLetterStatus.OPEN,
            )
        )
        logger.warning(
            "event_rejected",
            event_id=str(event_log.event_id),
            event_type=event_log.event_type,
            code=code,
            reason=reason,
        )
        return IngestResult(
            event_log=event_log,
            status=EventStatus.REJECTED,
            rejection_code=code,
            rejection_reason=reason,
            details=details,
        )

    async def record_malformed(self, *, raw_body: str, queue: str) -> DeadLetter:
        """Mensaje que ni siquiera es JSON valido, o al que le falta el sobre.

        No hay `event_id` con el que correlacionarlo, pero se guarda el cuerpo
        crudo: tampoco este caso puede perderse.
        """
        dead_letter = DeadLetter(
            reason_code=REASON_MALFORMED_MESSAGE,
            reason=f"Mensaje ilegible en la cola '{queue}'.",
            raw_body=raw_body[:20_000],
            attempts=1,
            status=DeadLetterStatus.OPEN,
        )
        self.dead_letter_repo.add(dead_letter)
        logger.warning("malformed_message", queue=queue, preview=raw_body[:200])
        return dead_letter

    # ------------------------------------------------------------------
    # Consulta
    # ------------------------------------------------------------------
    async def journey(self, correlation_id: uuid.UUID) -> list[EventLog]:
        """Todos los eventos de una misma journey, en orden cronologico."""
        return await self.event_log_repo.by_correlation(correlation_id)


def _elapsed_ms(started: datetime) -> int:
    return max(int((utcnow() - started).total_seconds() * 1000), 0)


def _with_details(reason: str, details: list) -> str:
    if not details:
        return reason
    rendered = "; ".join(
        f"{item.get('field', '?')}: {item.get('message', '')}"
        if isinstance(item, dict)
        else str(item)
        for item in details[:10]
    )
    return f"{reason} | {rendered}"
