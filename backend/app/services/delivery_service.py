"""Reintentos y Dead Letter Queue.

Tres reglas del enunciado gobiernan este archivo:

* los mensajes que no puedan procesarse tras los reintentos van a una DLQ;
* los mensajes fallidos no deben perderse;
* los reintentos quedan auditados.

El backoff se implementa con una cola por escalon (5s / 30s / 2m / 10m): el
mensaje se publica en el exchange del escalon, espera el TTL de esa cola y al
vencer vuelve solo a `muni.events` conservando su routing key, o sea la cola del
modulo destino. Agotados los escalones, la entrega queda `DEAD` y aparece en la
DLQ para intervencion manual.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

import structlog

from app.core.config import settings
from app.core.context import get_actor, get_trace_id
from app.core.database import utcnow
from app.core.errors import ConflictError, ExternalUnavailableError, NotFoundError
from app.messaging.broker import (
    HEADER_ATTEMPT,
    HEADER_ERROR,
    HEADER_EVENT_ID,
    HEADER_TARGET,
    HEADER_TRACE_ID,
    Broker,
    InboundMessage,
    OutboundMessage,
)
from app.messaging.topology import retry_exchange_for
from app.models.events import (
    DeadLetter,
    DeadLetterStatus,
    Delivery,
    DeliveryStatus,
    EventLog,
    RetryAudit,
    RetryMode,
    RetryResult,
)
from app.repositories.event_repository import (
    DeadLetterRepository,
    DeliveryRepository,
    EventLogRepository,
    RetryAuditRepository,
)
from app.services.event_hub_service import (
    REASON_DELIVERY_FAILED,
    REASON_MALFORMED_MESSAGE,
    REASON_SCHEMA_VIOLATION,
    EventHubService,
)

logger = structlog.get_logger(__name__)

CONFIG_REASONS = {REASON_SCHEMA_VIOLATION}
"""Motivos que se arreglan cambiando la configuracion del Core (el schema del
tipo, o la suscripcion que faltaba). Se resuelven reprocesando el evento ya
guardado, sin pedirle nada al modulo origen."""


@dataclass
class RetryOutcome:
    dead_letter_id: uuid.UUID
    success: bool
    message: str
    attempt_number: int


@dataclass
class BulkRetryOutcome:
    total: int
    succeeded: int
    failed: int
    results: list[RetryOutcome]


class DeliveryService:
    def __init__(
        self,
        *,
        delivery_repo: DeliveryRepository,
        dead_letter_repo: DeadLetterRepository,
        retry_audit_repo: RetryAuditRepository,
        event_log_repo: EventLogRepository,
        hub: EventHubService,
        broker: Broker,
    ) -> None:
        self.delivery_repo = delivery_repo
        self.dead_letter_repo = dead_letter_repo
        self.retry_audit_repo = retry_audit_repo
        self.event_log_repo = event_log_repo
        self.hub = hub
        self.broker = broker

    # ------------------------------------------------------------------
    async def handle_dlq_message(self, message: InboundMessage) -> DeadLetter | None:
        """Procesa un mensaje que cayo en `q.dlq`.

        Llega aca cuando el modulo destino lo rechazo (nack sin requeue). Si le
        quedan intentos se programa el siguiente escalon de backoff; si no, queda
        como dead letter abierta esperando a un operador.
        """
        event_id = _parse_uuid(message.headers.get(HEADER_EVENT_ID))
        target_module = message.headers.get(HEADER_TARGET)
        last_error = message.headers.get(HEADER_ERROR) or "El consumidor rechazo el mensaje."

        try:
            body = message.json()
        except ValueError:
            return await self.hub.record_malformed(raw_body=message.text, queue=message.queue)

        if event_id is None and isinstance(body, dict):
            event_id = _parse_uuid(body.get("eventId"))

        event_log = await self.event_log_repo.get_by_event_id(event_id) if event_id else None
        delivery = (
            await self.delivery_repo.find_for_event_and_module(event_log.id, target_module)
            if event_log is not None and target_module
            else None
        )

        if delivery is None:
            # Sin entrega correlacionada no hay a quien reintentarle: se guarda
            # para que quede constancia y se pueda inspeccionar.
            return self._open_dead_letter(
                event_log=event_log,
                delivery=None,
                event_id=event_id,
                event_type=body.get("eventType") if isinstance(body, dict) else None,
                source_module=body.get("sourceModule") if isinstance(body, dict) else None,
                target_module=target_module,
                reason_code=REASON_DELIVERY_FAILED
                if event_log is not None
                else REASON_MALFORMED_MESSAGE,
                reason=(
                    "No se pudo correlacionar el mensaje con una entrega registrada. "
                    f"Detalle: {last_error}"
                ),
                raw_payload=body if isinstance(body, dict) else None,
                attempts=message.attempt or 1,
            )

        delivery.last_error = str(last_error)[:2000]

        if delivery.attempts_exhausted:
            return await self._exhaust(delivery, event_log, body, str(last_error))

        await self._schedule_retry(delivery, event_log, body, str(last_error))
        return None

    async def _schedule_retry(
        self, delivery: Delivery, event_log: EventLog | None, body: dict, last_error: str
    ) -> None:
        """Publica el mensaje en el escalon de backoff que corresponda."""
        # `attempts` es el numero del intento que acaba de fallar: define el
        # escalon de espera. Se incrementa aca, al programar el siguiente; sin
        # eso el contador quedaria clavado, el backoff no escalaria nunca y el
        # mensaje giraria para siempre sin llegar a la DLQ.
        attempt = delivery.attempts
        delay = _delay_for(attempt)
        delivery.attempts += 1
        delivery.status = DeliveryStatus.RETRYING
        delivery.next_retry_at = utcnow() + timedelta(seconds=delay)

        published = await self._publish_retry(delivery, body, delay=delay, attempt=attempt)

        self.retry_audit_repo.add(
            RetryAudit(
                delivery_id=delivery.id,
                event_id=event_log.event_id if event_log else None,
                mode=RetryMode.AUTOMATIC,
                actor="system",
                attempt_number=attempt,
                result=RetryResult.SUCCESS if published else RetryResult.FAILURE,
                error=None if published else last_error,
                target_module=delivery.target_module,
            )
        )
        logger.info(
            "delivery_retry_scheduled",
            target=delivery.target_module,
            attempt=attempt,
            max_attempts=delivery.max_attempts,
            delay_seconds=delay,
        )

    async def _exhaust(
        self, delivery: Delivery, event_log: EventLog | None, body: dict, last_error: str
    ) -> DeadLetter:
        """Agotados los reintentos: la entrega muere y se abre una dead letter."""
        delivery.status = DeliveryStatus.DEAD
        delivery.next_retry_at = None

        dead_letter = self._open_dead_letter(
            event_log=event_log,
            delivery=delivery,
            event_id=event_log.event_id if event_log else None,
            event_type=event_log.event_type if event_log else body.get("eventType"),
            source_module=event_log.source_module if event_log else body.get("sourceModule"),
            target_module=delivery.target_module,
            reason_code=REASON_DELIVERY_FAILED,
            reason=(
                f"Se agotaron los {delivery.max_attempts} intentos de entrega a "
                f"'{delivery.target_module}'. Ultimo error: {last_error}"
            ),
            raw_payload=body,
            attempts=delivery.attempts,
        )
        self.retry_audit_repo.add(
            RetryAudit(
                dead_letter_id=dead_letter.id,
                delivery_id=delivery.id,
                event_id=event_log.event_id if event_log else None,
                mode=RetryMode.AUTOMATIC,
                actor="system",
                attempt_number=delivery.attempts,
                result=RetryResult.FAILURE,
                error=last_error[:2000],
                target_module=delivery.target_module,
            )
        )
        logger.warning(
            "delivery_dead_lettered",
            target=delivery.target_module,
            attempts=delivery.attempts,
        )
        return dead_letter

    def _open_dead_letter(self, **kwargs) -> DeadLetter:
        dead_letter = DeadLetter(
            event_log_id=kwargs["event_log"].id if kwargs.get("event_log") else None,
            delivery_id=kwargs["delivery"].id if kwargs.get("delivery") else None,
            event_id=kwargs.get("event_id"),
            event_type=kwargs.get("event_type"),
            source_module=kwargs.get("source_module"),
            target_module=kwargs.get("target_module"),
            reason_code=kwargs["reason_code"],
            reason=str(kwargs["reason"])[:4000],
            raw_payload=kwargs.get("raw_payload"),
            raw_body=kwargs.get("raw_body"),
            attempts=kwargs.get("attempts", 1),
            status=DeadLetterStatus.OPEN,
        )
        self.dead_letter_repo.add(dead_letter)
        return dead_letter

    # ------------------------------------------------------------------
    async def retry_dead_letter(self, dead_letter_id: uuid.UUID) -> RetryOutcome:
        """Reintenta una dead letter. Siempre queda auditado quien la disparo."""
        dead_letter = await self.dead_letter_repo.get_with_retries(dead_letter_id)
        if dead_letter is None:
            raise NotFoundError(f"No existe la dead letter {dead_letter_id}.")
        if dead_letter.status != DeadLetterStatus.OPEN:
            raise ConflictError(
                f"La dead letter ya fue resuelta (estado {dead_letter.status}). "
                "Solo se pueden reintentar las abiertas."
            )

        actor = get_actor() or "desconocido"
        attempt_number = len(dead_letter.retries) + 1

        if dead_letter.reason_code == REASON_MALFORMED_MESSAGE:
            raise ConflictError(
                "Un mensaje malformado no se puede reintentar: no tiene un sobre "
                "valido. Revisalo, corregilo en el modulo origen y descartalo con "
                "un motivo."
            )

        if dead_letter.reason_code in CONFIG_REASONS:
            outcome = await self._retry_by_reprocessing(dead_letter, attempt_number)
        else:
            outcome = await self._retry_by_republishing(dead_letter, attempt_number)

        self.retry_audit_repo.add(
            RetryAudit(
                dead_letter_id=dead_letter.id,
                delivery_id=dead_letter.delivery_id,
                event_id=dead_letter.event_id,
                mode=RetryMode.MANUAL,
                actor=actor,
                attempt_number=attempt_number,
                result=RetryResult.SUCCESS if outcome.success else RetryResult.FAILURE,
                error=None if outcome.success else outcome.message,
                target_module=dead_letter.target_module,
            )
        )

        if outcome.success:
            dead_letter.status = DeadLetterStatus.RETRIED
            dead_letter.resolved_at = utcnow()
            dead_letter.resolved_by = actor
            dead_letter.resolution_notes = outcome.message

        logger.info(
            "dead_letter_retried",
            dead_letter_id=str(dead_letter.id),
            actor=actor,
            success=outcome.success,
        )
        return outcome

    async def _retry_by_reprocessing(
        self, dead_letter: DeadLetter, attempt_number: int
    ) -> RetryOutcome:
        if dead_letter.event_log_id is None:
            return RetryOutcome(
                dead_letter.id, False, "La dead letter no referencia un evento.", attempt_number
            )

        event_log = await self.event_log_repo.get_with_deliveries(dead_letter.event_log_id)
        if event_log is None:
            return RetryOutcome(
                dead_letter.id, False, "El evento referenciado ya no existe.", attempt_number
            )

        result = await self.hub.reprocess(event_log)
        if result.accepted:
            targets = ", ".join(result.routed_to) or "sin suscriptores"
            return RetryOutcome(
                dead_letter.id, True, f"Evento reprocesado y ruteado a: {targets}.", attempt_number
            )
        return RetryOutcome(
            dead_letter.id,
            False,
            result.rejection_reason or "El evento sigue siendo invalido.",
            attempt_number,
        )

    async def _retry_by_republishing(
        self, dead_letter: DeadLetter, attempt_number: int
    ) -> RetryOutcome:
        payload = dead_letter.raw_payload
        if not payload:
            return RetryOutcome(
                dead_letter.id, False, "No conserva un payload republicable.", attempt_number
            )

        delivery = (
            await self.delivery_repo.get(dead_letter.delivery_id)
            if dead_letter.delivery_id
            else None
        )
        queue = delivery.queue_name if delivery else f"q.{dead_letter.target_module}"

        try:
            await self.broker.publish(
                OutboundMessage(
                    exchange=settings.exchange_events,
                    routing_key=queue,
                    body=payload,
                    headers={
                        HEADER_EVENT_ID: str(dead_letter.event_id or ""),
                        HEADER_TARGET: dead_letter.target_module or "",
                        HEADER_TRACE_ID: get_trace_id(),
                        HEADER_ATTEMPT: 1,
                    },
                    message_id=str(dead_letter.event_id) if dead_letter.event_id else None,
                )
            )
        except Exception as exc:
            return RetryOutcome(
                dead_letter.id, False, f"No se pudo publicar en '{queue}': {exc}", attempt_number
            )

        if delivery is not None:
            # Se reinicia el contador: el operador dio una oportunidad nueva.
            delivery.status = DeliveryStatus.DELIVERED
            delivery.attempts = 1
            delivery.delivered_at = utcnow()
            delivery.next_retry_at = None

        return RetryOutcome(
            dead_letter.id, True, f"Mensaje republicado en '{queue}'.", attempt_number
        )

    async def retry_many(self, dead_letter_ids: list[uuid.UUID]) -> BulkRetryOutcome:
        """Reintento masivo. Cada elemento se audita por separado y un fallo no
        interrumpe a los demas."""
        results: list[RetryOutcome] = []
        for dead_letter_id in dead_letter_ids:
            try:
                results.append(await self.retry_dead_letter(dead_letter_id))
            except (NotFoundError, ConflictError) as exc:
                results.append(RetryOutcome(dead_letter_id, False, exc.message, 0))
        succeeded = sum(1 for item in results if item.success)
        return BulkRetryOutcome(
            total=len(results),
            succeeded=succeeded,
            failed=len(results) - succeeded,
            results=results,
        )

    async def discard_dead_letter(self, dead_letter_id: uuid.UUID, *, reason: str) -> DeadLetter:
        """Descarta con motivo obligatorio. El registro se conserva siempre."""
        if not reason or not reason.strip():
            raise ConflictError("Para descartar una dead letter hay que indicar un motivo.")

        dead_letter = await self.dead_letter_repo.get_with_retries(dead_letter_id)
        if dead_letter is None:
            raise NotFoundError(f"No existe la dead letter {dead_letter_id}.")
        if dead_letter.status != DeadLetterStatus.OPEN:
            raise ConflictError(f"La dead letter ya esta en estado {dead_letter.status}.")

        actor = get_actor() or "desconocido"
        dead_letter.status = DeadLetterStatus.DISCARDED
        dead_letter.resolved_at = utcnow()
        dead_letter.resolved_by = actor
        dead_letter.resolution_notes = reason.strip()[:2000]

        if dead_letter.delivery_id:
            delivery = await self.delivery_repo.get(dead_letter.delivery_id)
            if delivery is not None:
                delivery.status = DeliveryStatus.DISCARDED
                delivery.next_retry_at = None

        self.retry_audit_repo.add(
            RetryAudit(
                dead_letter_id=dead_letter.id,
                delivery_id=dead_letter.delivery_id,
                event_id=dead_letter.event_id,
                mode=RetryMode.MANUAL,
                actor=actor,
                attempt_number=len(dead_letter.retries) + 1,
                result=RetryResult.FAILURE,
                error=f"Descartado manualmente: {reason.strip()[:500]}",
                target_module=dead_letter.target_module,
            )
        )
        logger.info("dead_letter_discarded", dead_letter_id=str(dead_letter.id), actor=actor)
        return dead_letter

    # ------------------------------------------------------------------
    async def process_due_retries(self, *, limit: int = 100) -> int:
        """Reintenta las entregas cuyo backoff ya vencio.

        Cubre el caso en que el broker estaba caido cuando se ruteo el evento: la
        entrega quedo `RETRYING` y el evento persistido. Cuando el broker vuelve,
        esto la completa sin perder nada.
        """
        if not await self.broker.healthy():
            raise ExternalUnavailableError(
                "El broker no esta disponible: los reintentos quedan pendientes."
            )

        now = utcnow()
        processed = 0

        for delivery in await self.delivery_repo.due_for_retry(now=now, limit=limit):
            event_log = await self.event_log_repo.get(delivery.event_log_id)
            if event_log is None:
                continue

            delivery.attempts += 1
            try:
                await self.broker.publish(
                    OutboundMessage(
                        exchange=settings.exchange_events,
                        routing_key=delivery.queue_name,
                        body=event_log.envelope,
                        headers={
                            HEADER_EVENT_ID: str(event_log.event_id),
                            HEADER_TARGET: delivery.target_module,
                            HEADER_TRACE_ID: event_log.trace_id or get_trace_id(),
                            HEADER_ATTEMPT: delivery.attempts,
                        },
                        message_id=str(event_log.event_id),
                    )
                )
            except Exception as exc:
                delivery.last_error = f"{type(exc).__name__}: {exc}"
                if delivery.attempts_exhausted:
                    await self._exhaust(delivery, event_log, event_log.envelope, str(exc))
                else:
                    delivery.next_retry_at = now + timedelta(seconds=_delay_for(delivery.attempts))
                continue

            delivery.status = DeliveryStatus.DELIVERED
            delivery.delivered_at = utcnow()
            delivery.next_retry_at = None
            processed += 1

            self.retry_audit_repo.add(
                RetryAudit(
                    delivery_id=delivery.id,
                    event_id=event_log.event_id,
                    mode=RetryMode.AUTOMATIC,
                    actor="system",
                    attempt_number=delivery.attempts,
                    result=RetryResult.SUCCESS,
                    target_module=delivery.target_module,
                )
            )

        if processed:
            logger.info("deferred_retries_processed", processed=processed)
        return processed

    async def _publish_retry(
        self, delivery: Delivery, body: dict, *, delay: int, attempt: int
    ) -> bool:
        """Publica en el exchange del escalon de backoff.

        El mensaje conserva como routing key la cola destino, asi que cuando el
        TTL de la cola de espera vence, vuelve solo a esa cola.
        """
        try:
            await self.broker.publish(
                OutboundMessage(
                    exchange=retry_exchange_for(delay),
                    routing_key=delivery.queue_name,
                    body=body,
                    headers={
                        HEADER_TARGET: delivery.target_module,
                        HEADER_ATTEMPT: attempt + 1,
                        HEADER_TRACE_ID: get_trace_id(),
                        HEADER_ERROR: (delivery.last_error or "")[:500],
                    },
                )
            )
            return True
        except Exception as exc:
            logger.warning("retry_publish_failed", target=delivery.target_module, error=str(exc))
            return False


def _delay_for(attempt: int) -> int:
    delays = settings.retry_delays or [5]
    return delays[min(max(attempt, 1), len(delays)) - 1]


def _parse_uuid(value: object) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    if isinstance(value, str):
        try:
            return uuid.UUID(value)
        except ValueError:
            return None
    return None
