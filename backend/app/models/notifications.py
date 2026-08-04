"""Notificaciones: plantillas, reglas, preferencias e historial de envios.

La relacion evento -> plantilla vive en `notification_rules`, en la base, no en
el codigo. Es lo que permite que el Core notifique por `ReclamoResuelto` o
`HabilitacionAprobada` sin conocer ni una sola regla de negocio de esas areas
(seccion 9 del enunciado).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy import Uuid as SAUuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, JSONType, TimestampMixin, TimestampTZ


class Channel(str, enum.Enum):
    EMAIL = "EMAIL"
    IN_APP = "IN_APP"
    SMS = "SMS"
    PUSH = "PUSH"


class NotificationStatus(str, enum.Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    SUPPRESSED = "SUPPRESSED"
    """El destinatario tiene desactivado ese canal para ese tipo de evento."""


class RecipientSource(str, enum.Enum):
    """De donde sale el destinatario, sin interpretar el negocio del evento."""

    PAYLOAD_FIELD = "PAYLOAD_FIELD"
    """De un campo del `data` (ej. `ciudadano.email`), configurado por regla."""
    EXTERNAL_USER = "EXTERNAL_USER"
    """Del campo que trae el id externo del ciudadano; se resuelve en `users`."""
    ROLE = "ROLE"
    """A todos los usuarios que tengan un rol dado (avisos internos)."""
    FIXED = "FIXED"
    """Direccion fija, configurada en la regla."""


class NotificationTemplate(Base, TimestampMixin):
    __tablename__ = "notification_templates"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    channel: Mapped[Channel] = mapped_column(String(10), index=True)
    subject_template: Mapped[str] = mapped_column(String(255), default="")
    body_template: Mapped[str] = mapped_column(Text)
    """Plantilla Jinja2. Recibe el sobre completo como contexto."""
    locale: Mapped[str] = mapped_column(String(10), default="es-AR")
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    rules: Mapped[list[NotificationRule]] = relationship(back_populates="template")


class NotificationRule(Base, TimestampMixin):
    """Configuracion: cuando llegue este evento, notificar con esta plantilla."""

    __tablename__ = "notification_rules"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(String(120), index=True)
    template_id: Mapped[uuid.UUID] = mapped_column(
        SAUuid, ForeignKey("notification_templates.id", ondelete="CASCADE"), index=True
    )
    recipient_source: Mapped[RecipientSource] = mapped_column(
        String(20), default=RecipientSource.PAYLOAD_FIELD
    )
    # Ruta con puntos dentro de `data`, o el codigo de rol, o la direccion fija.
    recipient_expression: Mapped[str] = mapped_column(String(255), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(default=100)

    template: Mapped[NotificationTemplate] = relationship(back_populates="rules", lazy="joined")

    __table_args__ = (
        UniqueConstraint("event_type", "template_id", name="uq_rules_event_template"),
    )


class NotificationPreference(Base, TimestampMixin):
    """Opt-out por destinatario, canal y (opcionalmente) tipo de evento."""

    __tablename__ = "notification_preferences"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    subject_ref: Mapped[str] = mapped_column(String(255), index=True)
    """Email o id externo del destinatario."""
    channel: Mapped[Channel] = mapped_column(String(10))
    event_type: Mapped[str | None] = mapped_column(String(120), default=None)
    """Nulo = aplica a todos los tipos de evento."""
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (
        UniqueConstraint(
            "subject_ref", "channel", "event_type", name="uq_pref_subject_channel_event"
        ),
    )


class Notification(Base, TimestampMixin):
    """Historial de envios. Es la evidencia del lado de comunicaciones."""

    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID | None] = mapped_column(SAUuid, index=True, default=None)
    event_type: Mapped[str | None] = mapped_column(String(120), index=True, default=None)
    rule_id: Mapped[uuid.UUID | None] = mapped_column(SAUuid, default=None)
    template_code: Mapped[str | None] = mapped_column(String(80), index=True, default=None)

    channel: Mapped[Channel] = mapped_column(String(10), index=True)
    recipient: Mapped[str] = mapped_column(String(255), index=True)
    subject: Mapped[str] = mapped_column(String(255), default="")
    body: Mapped[str] = mapped_column(Text, default="")

    status: Mapped[NotificationStatus] = mapped_column(
        String(12), default=NotificationStatus.PENDING, index=True
    )
    attempts: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    provider_response: Mapped[dict | None] = mapped_column(JSONType, default=None)
    sent_at: Mapped[datetime | None] = mapped_column(TimestampTZ, default=None)
    read_at: Mapped[datetime | None] = mapped_column(TimestampTZ, default=None)
    """Solo para el canal in-app."""
