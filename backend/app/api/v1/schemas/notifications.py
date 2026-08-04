"""DTOs de notificaciones."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from app.api.v1.schemas.common import CamelModel
from app.models.notifications import (
    Channel,
    Notification,
    NotificationPreference,
    NotificationRule,
    NotificationStatus,
    NotificationTemplate,
    RecipientSource,
)


class TemplateResponse(CamelModel):
    id: uuid.UUID
    code: str
    name: str
    channel: Channel
    subject_template: str
    body_template: str
    locale: str
    active: bool

    @classmethod
    def of(cls, template: NotificationTemplate) -> TemplateResponse:
        return cls.model_validate(template)


class TemplateCreate(CamelModel):
    code: str = Field(min_length=2, max_length=80, examples=["RECLAMO_RESUELTO_EMAIL"])
    name: str = Field(min_length=2, max_length=160)
    channel: Channel = Channel.EMAIL
    subject_template: str = Field(
        default="",
        examples=["Tu reclamo {{ data.reclamoId }} fue resuelto"],
    )
    body_template: str = Field(
        min_length=1,
        description="Plantilla Jinja2. El contexto es el sobre completo del evento.",
        examples=[
            "Hola, tu reclamo {{ data.reclamoId }} fue resuelto el "
            "{{ occurredAt }}.\n\nMunicipalidad de Ciudad UADE."
        ],
    )
    locale: str = "es-AR"


class TemplateUpdate(CamelModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    subject_template: str | None = None
    body_template: str | None = Field(default=None, min_length=1)
    active: bool | None = None


class TemplatePreviewRequest(CamelModel):
    """Sobre de ejemplo para previsualizar la plantilla sin enviar nada."""

    sample: dict[str, Any] = Field(
        examples=[
            {
                "eventType": "ReclamoResuelto",
                "occurredAt": "2026-08-04T12:34:56-03:00",
                "data": {"reclamoId": "RC-2026-00184", "solucion": "Bache reparado"},
            }
        ]
    )


class TemplatePreviewResponse(CamelModel):
    subject: str
    body: str


class RuleResponse(CamelModel):
    id: uuid.UUID
    event_type: str
    template_id: uuid.UUID
    template_code: str
    channel: Channel
    recipient_source: RecipientSource
    recipient_expression: str
    priority: int
    active: bool

    @classmethod
    def of(cls, rule: NotificationRule) -> RuleResponse:
        return cls(
            id=rule.id,
            event_type=rule.event_type,
            template_id=rule.template_id,
            template_code=rule.template.code if rule.template else "",
            channel=rule.template.channel if rule.template else Channel.EMAIL,
            recipient_source=rule.recipient_source,
            recipient_expression=rule.recipient_expression,
            priority=rule.priority,
            active=rule.active,
        )


class RuleCreate(CamelModel):
    """Configura que se notifica ante que evento, y a quien.

    Es lo que permite que el Core notifique por eventos de otras areas sin
    conocer sus reglas de negocio: todo esta aca, no en el codigo.
    """

    event_type: str = Field(examples=["ReclamoResuelto"])
    template_code: str = Field(examples=["RECLAMO_RESUELTO_EMAIL"])
    recipient_source: RecipientSource = Field(
        default=RecipientSource.PAYLOAD_FIELD,
        description=(
            "PAYLOAD_FIELD: ruta con puntos dentro de `data`. "
            "EXTERNAL_USER: ruta al id externo del ciudadano, resuelto contra las "
            "cuentas del Core. ROLE: codigo de rol (avisos internos). "
            "FIXED: direccion literal."
        ),
    )
    recipient_expression: str = Field(default="", examples=["ciudadano.email"])
    priority: int = Field(default=100, ge=1, le=1000)


class RuleUpdate(CamelModel):
    active: bool | None = None
    recipient_expression: str | None = None
    priority: int | None = Field(default=None, ge=1, le=1000)


class PreferenceResponse(CamelModel):
    id: uuid.UUID
    subject_ref: str
    channel: Channel
    event_type: str | None
    enabled: bool

    @classmethod
    def of(cls, preference: NotificationPreference) -> PreferenceResponse:
        return cls.model_validate(preference)


class PreferenceUpsert(CamelModel):
    subject_ref: str = Field(
        min_length=1,
        max_length=255,
        description="Email o id externo del destinatario.",
    )
    channel: Channel
    event_type: str | None = Field(
        default=None, description="Nulo: aplica a todos los tipos de evento."
    )
    enabled: bool = True


class NotificationResponse(CamelModel):
    id: uuid.UUID
    event_id: uuid.UUID | None
    event_type: str | None
    template_code: str | None
    channel: Channel
    recipient: str
    subject: str
    status: NotificationStatus
    attempts: int
    error: str | None
    sent_at: datetime | None
    read_at: datetime | None
    created_at: datetime

    @classmethod
    def of(cls, notification: Notification) -> NotificationResponse:
        return cls.model_validate(notification)


class NotificationDetailResponse(NotificationResponse):
    body: str
    provider_response: dict[str, Any] | None

    @classmethod
    def of_detail(cls, notification: Notification) -> NotificationDetailResponse:
        return cls.model_validate(notification)
