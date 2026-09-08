"""Trazabilidad del pasamanos: bitacora, entregas, DLQ y auditoria de reintentos.

Es la evidencia que el dashboard muestra: que evento entro, de quien, a quien se
le entrego, en que estado quedo cada entrega y que fallo.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy import Uuid as SAUuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, JSONType, TimestampMixin, TimestampTZ


class EventStatus(str, enum.Enum):
    ROUTED = "ROUTED"
    """Entregado a todas sus suscripciones activas."""
    NO_SUBSCRIBERS = "NO_SUBSCRIBERS"
    """Valido pero nadie lo consume todavia. Se conserva igual: es la senal de
    que alguien publica algo que nadie escucha (nombre desalineado, o falta la
    suscripcion)."""
    REJECTED = "REJECTED"
    """No paso la validacion de estructura. Va a la DLQ, no se descarta."""
    DUPLICATE = "DUPLICATE"
    """Reenvio de un eventId ya visto. No genera efectos nuevos."""


class DeliveryStatus(str, enum.Enum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    RETRYING = "RETRYING"
    DEAD = "DEAD"
    DISCARDED = "DISCARDED"


class IngestionChannel(str, enum.Enum):
    AMQP = "AMQP"
    HTTP = "HTTP"


class DeadLetterStatus(str, enum.Enum):
    OPEN = "OPEN"
    RETRIED = "RETRIED"
    DISCARDED = "DISCARDED"


class RetryMode(str, enum.Enum):
    AUTOMATIC = "AUTOMATIC"
    MANUAL = "MANUAL"


class RetryResult(str, enum.Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"


class EventLog(Base, TimestampMixin):
    """Un evento que paso por el hub, con su sobre completo.

    `event_id` es UNIQUE: es la barrera de idempotencia. Un reenvio del mismo
    identificador se marca duplicado y no se vuelve a rutear.
    """

    __tablename__ = "event_log"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(SAUuid, unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String(120), index=True)
    event_version: Mapped[str] = mapped_column(String(20), default="1.0")
    source_module: Mapped[str] = mapped_column(String(60), index=True)

    occurred_at: Mapped[datetime] = mapped_column(TimestampTZ, index=True)
    received_at: Mapped[datetime] = mapped_column(TimestampTZ, index=True)

    correlation_id: Mapped[uuid.UUID | None] = mapped_column(SAUuid, index=True, default=None)
    causation_id: Mapped[uuid.UUID | None] = mapped_column(SAUuid, default=None)
    trace_id: Mapped[str | None] = mapped_column(String(60), index=True, default=None)

    envelope: Mapped[dict] = mapped_column(JSONType, default=dict)
    """El sobre tal cual llego. Es la evidencia; no se reescribe nunca."""

    status: Mapped[EventStatus] = mapped_column(String(20), default=EventStatus.ROUTED)
    rejection_code: Mapped[str | None] = mapped_column(String(60), default=None)
    rejection_reason: Mapped[str | None] = mapped_column(Text, default=None)
    ingestion_channel: Mapped[IngestionChannel] = mapped_column(
        String(10), default=IngestionChannel.AMQP
    )
    processing_ms: Mapped[int | None] = mapped_column(default=None)

    deliveries: Mapped[list[Delivery]] = relationship(
        back_populates="event", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_event_log_type_received", "event_type", "received_at"),
        Index("ix_event_log_source_received", "source_module", "received_at"),
    )


class Delivery(Base, TimestampMixin):
    """El intento de dejar un evento en la cola de un modulo suscripto.

    Una fila por (evento, modulo destino). Es lo que permite responder
    "¿le llego a Obras?" con algo mas que una suposicion.
    """

    __tablename__ = "deliveries"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    event_log_id: Mapped[uuid.UUID] = mapped_column(
        SAUuid, ForeignKey("event_log.id", ondelete="CASCADE"), index=True
    )
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(SAUuid, default=None)
    target_module: Mapped[str] = mapped_column(String(60), index=True)
    queue_name: Mapped[str] = mapped_column(String(120))
    event_type: Mapped[str | None] = mapped_column(String(120), index=True, default=None)

    status: Mapped[DeliveryStatus] = mapped_column(
        String(20), default=DeliveryStatus.PENDING, index=True
    )
    attempts: Mapped[int] = mapped_column(default=0)
    max_attempts: Mapped[int] = mapped_column(default=4)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)
    next_retry_at: Mapped[datetime | None] = mapped_column(TimestampTZ, default=None)
    delivered_at: Mapped[datetime | None] = mapped_column(TimestampTZ, default=None)

    event: Mapped[EventLog] = relationship(back_populates="deliveries")

    __table_args__ = (
        UniqueConstraint("event_log_id", "target_module", name="uq_deliveries_event_module"),
    )

    @property
    def attempts_exhausted(self) -> bool:
        return self.attempts >= self.max_attempts


class DeadLetter(Base, TimestampMixin):
    """Lo que no se pudo procesar. Nada se borra: se reintenta o se descarta con motivo.

    `event_log_id` es nulo cuando el mensaje llego tan malformado que no se pudo
    armar un sobre. Ese caso tambien queda guardado, con el cuerpo crudo.
    """

    __tablename__ = "dead_letters"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    event_log_id: Mapped[uuid.UUID | None] = mapped_column(
        SAUuid, ForeignKey("event_log.id", ondelete="SET NULL"), default=None, index=True
    )
    delivery_id: Mapped[uuid.UUID | None] = mapped_column(SAUuid, default=None, index=True)

    event_id: Mapped[uuid.UUID | None] = mapped_column(SAUuid, index=True, default=None)
    event_type: Mapped[str | None] = mapped_column(String(120), index=True, default=None)
    source_module: Mapped[str | None] = mapped_column(String(60), index=True, default=None)
    target_module: Mapped[str | None] = mapped_column(String(60), index=True, default=None)

    reason_code: Mapped[str] = mapped_column(String(60), index=True)
    reason: Mapped[str] = mapped_column(Text)
    details: Mapped[list | None] = mapped_column(JSONType, default=None)
    raw_payload: Mapped[dict | None] = mapped_column(JSONType, default=None)
    raw_body: Mapped[str | None] = mapped_column(Text, default=None)

    attempts: Mapped[int] = mapped_column(default=0)
    status: Mapped[DeadLetterStatus] = mapped_column(
        String(20), default=DeadLetterStatus.OPEN, index=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(TimestampTZ, default=None)
    resolved_by: Mapped[str | None] = mapped_column(String(120), default=None)
    resolution_notes: Mapped[str | None] = mapped_column(Text, default=None)

    retries: Mapped[list[RetryAudit]] = relationship(
        back_populates="dead_letter", cascade="all, delete-orphan", lazy="selectin"
    )


class RetryAudit(Base, TimestampMixin):
    """Bitacora de reintentos: automaticos y manuales, con quien los disparo."""

    __tablename__ = "retry_audit"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    dead_letter_id: Mapped[uuid.UUID | None] = mapped_column(
        SAUuid, ForeignKey("dead_letters.id", ondelete="CASCADE"), default=None, index=True
    )
    delivery_id: Mapped[uuid.UUID | None] = mapped_column(SAUuid, default=None, index=True)
    event_id: Mapped[uuid.UUID | None] = mapped_column(SAUuid, index=True, default=None)

    mode: Mapped[RetryMode] = mapped_column(String(12), default=RetryMode.AUTOMATIC)
    actor: Mapped[str] = mapped_column(String(120), default="system")
    attempt_number: Mapped[int] = mapped_column(default=1)
    result: Mapped[RetryResult] = mapped_column(String(10), default=RetryResult.SUCCESS)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    target_module: Mapped[str | None] = mapped_column(String(60), default=None)

    dead_letter: Mapped[DeadLetter | None] = relationship(back_populates="retries")
