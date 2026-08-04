"""Trazabilidad tecnica del hub: bitacora de eventos, entregas, DLQ y auditoria.

Estas cuatro tablas son la "evidencia de los eventos publicados y procesados"
que pide la regla 3 del enunciado, y el soporte de la idempotencia (regla 1) y
de la DLQ con reintentos auditados (regla 2).
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
    RECEIVED = "RECEIVED"
    """Sobre valido, todavia no ruteado."""
    ROUTED = "ROUTED"
    """Entregado a todas sus suscripciones activas."""
    NO_SUBSCRIBERS = "NO_SUBSCRIBERS"
    """Valido pero nadie lo consume todavia. Se conserva igual como evidencia."""
    REJECTED = "REJECTED"
    """Sobre o contrato invalido. Va a la DLQ, no se descarta."""
    DUPLICATE = "DUPLICATE"
    """Reenvio de un eventId ya procesado. No genera efectos nuevos."""


class DeliveryStatus(str, enum.Enum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    RETRYING = "RETRYING"
    DEAD = "DEAD"
    """Agotados los reintentos: el mensaje esta en la DLQ."""
    DISCARDED = "DISCARDED"
    """Descartado manualmente por un operador, con motivo."""


class IngestionChannel(str, enum.Enum):
    AMQP = "AMQP"
    HTTP = "HTTP"


class DeadLetterStatus(str, enum.Enum):
    OPEN = "OPEN"
    RETRIED = "RETRIED"
    RESOLVED = "RESOLVED"
    DISCARDED = "DISCARDED"


class RetryMode(str, enum.Enum):
    AUTOMATIC = "AUTOMATIC"
    MANUAL = "MANUAL"


class RetryResult(str, enum.Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"


class EventLog(Base, TimestampMixin):
    """Un evento recibido por el hub, con su sobre completo.

    `event_id` es UNIQUE: es la barrera de idempotencia. Un reenvio del mismo
    identificador se registra como duplicado y no se vuelve a rutear.
    """

    __tablename__ = "event_log"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(SAUuid, unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String(120), index=True)
    event_version: Mapped[str] = mapped_column(String(20), default="1.0")
    source_module: Mapped[str] = mapped_column(String(60), index=True)

    # Cuando ocurrio en el modulo origen (con zona horaria) vs cuando lo recibimos.
    occurred_at: Mapped[datetime] = mapped_column(TimestampTZ, index=True)
    received_at: Mapped[datetime] = mapped_column(TimestampTZ, index=True)

    correlation_id: Mapped[uuid.UUID | None] = mapped_column(SAUuid, index=True, default=None)
    causation_id: Mapped[uuid.UUID | None] = mapped_column(SAUuid, default=None)
    trace_id: Mapped[str | None] = mapped_column(String(60), index=True, default=None)

    envelope: Mapped[dict] = mapped_column(JSONType, default=dict)
    """Sobre tal cual llego. Es la evidencia; no se reescribe nunca."""

    status: Mapped[EventStatus] = mapped_column(String(20), default=EventStatus.RECEIVED)
    rejection_code: Mapped[str | None] = mapped_column(String(60), default=None)
    rejection_reason: Mapped[str | None] = mapped_column(Text, default=None)
    ingestion_channel: Mapped[IngestionChannel] = mapped_column(
        String(10), default=IngestionChannel.AMQP
    )
    # Cuantos milisegundos tardo el pipeline validar + persistir + rutear.
    processing_ms: Mapped[int | None] = mapped_column(default=None)

    deliveries: Mapped[list[Delivery]] = relationship(
        back_populates="event", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (Index("ix_event_log_type_received", "event_type", "received_at"),)

    @property
    def data(self) -> dict:
        return self.envelope.get("data", {}) if isinstance(self.envelope, dict) else {}


class Delivery(Base, TimestampMixin):
    """Intento de entrega de un evento a un modulo suscripto."""

    __tablename__ = "deliveries"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    event_log_id: Mapped[uuid.UUID] = mapped_column(
        SAUuid, ForeignKey("event_log.id", ondelete="CASCADE"), index=True
    )
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(SAUuid, default=None)
    target_module: Mapped[str] = mapped_column(String(60), index=True)
    queue_name: Mapped[str] = mapped_column(String(120))

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
    """Mensaje que no se pudo procesar. Nada se borra: se conserva y se reintenta.

    `event_log_id` es nulo cuando el mensaje llego tan malformado que no se pudo
    construir un sobre (por ejemplo, JSON invalido en la cola). Ese caso tambien
    tiene que quedar guardado: "los mensajes fallidos no deberan perderse".
    """

    __tablename__ = "dead_letters"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    event_log_id: Mapped[uuid.UUID | None] = mapped_column(
        SAUuid, ForeignKey("event_log.id", ondelete="SET NULL"), default=None, index=True
    )
    delivery_id: Mapped[uuid.UUID | None] = mapped_column(SAUuid, default=None, index=True)

    event_id: Mapped[uuid.UUID | None] = mapped_column(SAUuid, index=True, default=None)
    event_type: Mapped[str | None] = mapped_column(String(120), index=True, default=None)
    source_module: Mapped[str | None] = mapped_column(String(60), default=None)
    target_module: Mapped[str | None] = mapped_column(String(60), index=True, default=None)

    reason_code: Mapped[str] = mapped_column(String(60), index=True)
    reason: Mapped[str] = mapped_column(Text)
    raw_payload: Mapped[dict | None] = mapped_column(JSONType, default=None)
    raw_body: Mapped[str | None] = mapped_column(Text, default=None)
    """Cuerpo crudo, para los casos en que ni siquiera era JSON valido."""

    attempts: Mapped[int] = mapped_column(default=0)
    status: Mapped[DeadLetterStatus] = mapped_column(
        String(20), default=DeadLetterStatus.OPEN, index=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(TimestampTZ, default=None)
    resolved_by: Mapped[str | None] = mapped_column(String(180), default=None)
    resolution_notes: Mapped[str | None] = mapped_column(Text, default=None)

    retries: Mapped[list[RetryAudit]] = relationship(
        back_populates="dead_letter", cascade="all, delete-orphan", lazy="selectin"
    )


class RetryAudit(Base, TimestampMixin):
    """Bitacora de reintentos: "los reintentos deberan quedar auditados".

    Se escribe tanto para los reintentos automaticos (backoff) como para los
    manuales disparados desde el panel, con el usuario que los ejecuto.
    """

    __tablename__ = "retry_audit"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    dead_letter_id: Mapped[uuid.UUID | None] = mapped_column(
        SAUuid, ForeignKey("dead_letters.id", ondelete="CASCADE"), default=None, index=True
    )
    delivery_id: Mapped[uuid.UUID | None] = mapped_column(SAUuid, default=None, index=True)
    event_id: Mapped[uuid.UUID | None] = mapped_column(SAUuid, index=True, default=None)

    mode: Mapped[RetryMode] = mapped_column(String(12), default=RetryMode.AUTOMATIC)
    actor: Mapped[str] = mapped_column(String(180), default="system")
    attempt_number: Mapped[int] = mapped_column(default=1)
    result: Mapped[RetryResult] = mapped_column(String(10), default=RetryResult.SUCCESS)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    target_module: Mapped[str | None] = mapped_column(String(60), default=None)

    dead_letter: Mapped[DeadLetter | None] = relationship(back_populates="retries")


class ProcessedEvent(Base, TimestampMixin):
    """Marca de idempotencia por consumidor.

    La usan los consumidores internos del Core (notificaciones, provision de
    identidad) para no aplicar dos veces el mismo evento, y se expone por API
    para que los otros modulos puedan hacer lo mismo.
    """

    __tablename__ = "processed_events"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    consumer: Mapped[str] = mapped_column(String(80), index=True)
    event_id: Mapped[uuid.UUID] = mapped_column(SAUuid, index=True)
    event_type: Mapped[str | None] = mapped_column(String(120), default=None)
    processed_at: Mapped[datetime] = mapped_column(TimestampTZ)
    result: Mapped[str | None] = mapped_column(String(60), default=None)

    __table_args__ = (
        UniqueConstraint("consumer", "event_id", name="uq_processed_consumer_event"),
    )
