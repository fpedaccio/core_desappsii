"""DTOs del hub de eventos, entregas y DLQ."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from app.api.v1.schemas.common import CamelModel
from app.models.events import (
    DeadLetter,
    DeadLetterStatus,
    Delivery,
    DeliveryStatus,
    EventLog,
    EventStatus,
    IngestionChannel,
    ProcessedEvent,
    RetryAudit,
    RetryMode,
    RetryResult,
)
from app.services.event_hub_service import IngestResult


class DeliveryResponse(CamelModel):
    id: uuid.UUID
    target_module: str
    queue_name: str
    status: DeliveryStatus
    attempts: int
    max_attempts: int
    last_error: str | None
    next_retry_at: datetime | None
    delivered_at: datetime | None

    @classmethod
    def of(cls, delivery: Delivery) -> DeliveryResponse:
        return cls.model_validate(delivery)


class EventLogResponse(CamelModel):
    id: uuid.UUID
    event_id: uuid.UUID
    event_type: str
    event_version: str
    source_module: str
    occurred_at: datetime
    received_at: datetime
    correlation_id: uuid.UUID | None
    causation_id: uuid.UUID | None
    trace_id: str | None
    status: EventStatus
    rejection_code: str | None
    rejection_reason: str | None
    ingestion_channel: IngestionChannel
    processing_ms: int | None
    envelope: dict[str, Any]
    deliveries: list[DeliveryResponse]

    @classmethod
    def of(cls, event: EventLog) -> EventLogResponse:
        return cls(
            id=event.id,
            event_id=event.event_id,
            event_type=event.event_type,
            event_version=event.event_version,
            source_module=event.source_module,
            occurred_at=event.occurred_at,
            received_at=event.received_at,
            correlation_id=event.correlation_id,
            causation_id=event.causation_id,
            trace_id=event.trace_id,
            status=event.status,
            rejection_code=event.rejection_code,
            rejection_reason=event.rejection_reason,
            ingestion_channel=event.ingestion_channel,
            processing_ms=event.processing_ms,
            envelope=event.envelope or {},
            deliveries=[DeliveryResponse.of(d) for d in event.deliveries],
        )


class EventSummaryResponse(CamelModel):
    """Version liviana para el listado del explorador (sin el sobre completo)."""

    id: uuid.UUID
    event_id: uuid.UUID
    event_type: str
    event_version: str
    source_module: str
    occurred_at: datetime
    received_at: datetime
    correlation_id: uuid.UUID | None
    status: EventStatus
    rejection_code: str | None
    ingestion_channel: IngestionChannel
    processing_ms: int | None
    delivery_count: int
    delivered_count: int

    @classmethod
    def of(cls, event: EventLog) -> EventSummaryResponse:
        return cls(
            id=event.id,
            event_id=event.event_id,
            event_type=event.event_type,
            event_version=event.event_version,
            source_module=event.source_module,
            occurred_at=event.occurred_at,
            received_at=event.received_at,
            correlation_id=event.correlation_id,
            status=event.status,
            rejection_code=event.rejection_code,
            ingestion_channel=event.ingestion_channel,
            processing_ms=event.processing_ms,
            delivery_count=len(event.deliveries),
            delivered_count=sum(
                1 for d in event.deliveries if d.status == DeliveryStatus.DELIVERED
            ),
        )


class IngestResponse(CamelModel):
    """Resultado de publicar un evento en el hub."""

    event_id: uuid.UUID
    status: EventStatus
    accepted: bool
    duplicate: bool = Field(
        description="El eventId ya se habia procesado: no se generaron efectos nuevos."
    )
    routed_to: list[str]
    deferred_to: list[str] = Field(
        description="Suscriptores a los que no se pudo publicar ahora; quedan para reintento."
    )
    already_delivered: list[str] = Field(default_factory=list)
    rejection_code: str | None = None
    rejection_reason: str | None = None
    details: list[Any] = Field(default_factory=list)

    @classmethod
    def of(cls, result: IngestResult) -> IngestResponse:
        return cls(
            event_id=result.event_log.event_id,
            status=result.status,
            accepted=result.accepted,
            duplicate=result.duplicate,
            routed_to=result.routed_to,
            deferred_to=result.deferred_to,
            already_delivered=result.already_delivered,
            rejection_code=result.rejection_code,
            rejection_reason=result.rejection_reason,
            details=result.details,
        )


class ProcessedEventResponse(CamelModel):
    consumer: str
    event_id: uuid.UUID
    event_type: str | None
    processed_at: datetime
    result: str | None

    @classmethod
    def of(cls, processed: ProcessedEvent) -> ProcessedEventResponse:
        return cls.model_validate(processed)


class JourneyResponse(CamelModel):
    """Todos los eventos de una misma journey, en orden cronologico."""

    correlation_id: uuid.UUID
    event_count: int
    modules_involved: list[str]
    events: list[EventSummaryResponse]


# ----------------------------------------------------------------------
# DLQ
# ----------------------------------------------------------------------
class RetryAuditResponse(CamelModel):
    id: uuid.UUID
    mode: RetryMode
    actor: str
    attempt_number: int
    result: RetryResult
    error: str | None
    target_module: str | None
    created_at: datetime

    @classmethod
    def of(cls, audit: RetryAudit) -> RetryAuditResponse:
        return cls.model_validate(audit)


class DeadLetterResponse(CamelModel):
    id: uuid.UUID
    event_log_id: uuid.UUID | None
    event_id: uuid.UUID | None
    event_type: str | None
    source_module: str | None
    target_module: str | None
    reason_code: str
    reason: str
    attempts: int
    status: DeadLetterStatus
    resolved_at: datetime | None
    resolved_by: str | None
    resolution_notes: str | None
    created_at: datetime
    retry_count: int
    retryable: bool = Field(
        description="Un mensaje malformado no se puede reintentar: hay que descartarlo."
    )

    @classmethod
    def of(cls, dead_letter: DeadLetter) -> DeadLetterResponse:
        from app.services.event_hub_service import REASON_MALFORMED_MESSAGE

        return cls(
            id=dead_letter.id,
            event_log_id=dead_letter.event_log_id,
            event_id=dead_letter.event_id,
            event_type=dead_letter.event_type,
            source_module=dead_letter.source_module,
            target_module=dead_letter.target_module,
            reason_code=dead_letter.reason_code,
            reason=dead_letter.reason,
            attempts=dead_letter.attempts,
            status=dead_letter.status,
            resolved_at=dead_letter.resolved_at,
            resolved_by=dead_letter.resolved_by,
            resolution_notes=dead_letter.resolution_notes,
            created_at=dead_letter.created_at,
            retry_count=len(dead_letter.retries),
            retryable=(
                dead_letter.status == DeadLetterStatus.OPEN
                and dead_letter.reason_code != REASON_MALFORMED_MESSAGE
            ),
        )


class DeadLetterDetailResponse(DeadLetterResponse):
    raw_payload: dict[str, Any] | None
    raw_body: str | None
    retries: list[RetryAuditResponse]

    @classmethod
    def of_detail(cls, dead_letter: DeadLetter) -> DeadLetterDetailResponse:
        base = DeadLetterResponse.of(dead_letter)
        return cls(
            **base.model_dump(),
            raw_payload=dead_letter.raw_payload,
            raw_body=dead_letter.raw_body,
            retries=[RetryAuditResponse.of(r) for r in dead_letter.retries],
        )


class RetryResultResponse(CamelModel):
    dead_letter_id: uuid.UUID
    success: bool
    message: str
    attempt_number: int


class BulkRetryRequest(CamelModel):
    dead_letter_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)


class BulkRetryResponse(CamelModel):
    total: int
    succeeded: int
    failed: int
    results: list[RetryResultResponse]


class DiscardRequest(CamelModel):
    reason: str = Field(
        min_length=3,
        max_length=2000,
        description="Obligatorio: queda en la auditoria del descarte.",
    )
