"""DTOs de la API.

La API expone **camelCase** hacia afuera y trabaja en snake_case adentro. La
conversion la hace el alias generator de `CamelModel`, una sola vez.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import EmailStr, Field

from app.api.v1.schemas.common import CamelModel
from app.models.events import (
    DeadLetter,
    DeadLetterStatus,
    Delivery,
    DeliveryStatus,
    EventLog,
    EventStatus,
    IngestionChannel,
    RetryAudit,
    RetryMode,
    RetryResult,
)
from app.models.registry import EventType, ModuleAccount, Publication, Subscription
from app.models.users import User as DashboardUser
from app.services.event_hub_service import IngestResult

SCHEMA_EXAMPLE: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "ticketId": {"type": "string"},
        "status": {"type": "string", "enum": ["OPEN", "IN_PROGRESS", "RESOLVED"]},
    },
    "required": ["ticketId"],
    "additionalProperties": True,
}


# ----------------------------------------------------------------------
# Autenticacion
# ----------------------------------------------------------------------
class LoginRequest(CamelModel):
    """Login de una persona en el dashboard."""

    email: EmailStr = Field(examples=["ana@obras.uade.edu.ar"])
    password: str = Field(min_length=1)


class ModuleTokenRequest(CamelModel):
    """Token para el backend de un modulo, para publicar eventos.

    El secret vive en la config del equipo, no lo usa ninguna persona.
    """

    module: str = Field(examples=["obras"], description="Nombre tecnico del modulo")
    secret: str = Field(min_length=1, description="El secret de maquina del modulo")


class TokenResponse(CamelModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int = Field(description="Segundos hasta que el token expire")
    module: str
    display_name: str
    is_admin: bool = Field(
        description="Solo el equipo 9. Habilita ver el trafico de todos los modulos."
    )
    kind: str = Field(
        description="'user' si entro una persona, 'module' si es un backend.",
        examples=["user"],
    )
    actor: str = Field(description="Lo que queda en la auditoria: el email, o module:<nombre>.")


class MeResponse(CamelModel):
    module: str
    display_name: str
    is_admin: bool
    kind: str
    email: str | None = None
    name: str | None = None


# ----------------------------------------------------------------------
# Personas del dashboard
# ----------------------------------------------------------------------
class UserResponse(CamelModel):
    id: uuid.UUID
    email: str
    full_name: str
    module_name: str
    active: bool
    last_login_at: datetime | None
    created_at: datetime

    @classmethod
    def of(cls, user: DashboardUser) -> UserResponse:
        return cls(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            module_name=user.module.name,
            active=user.active,
            last_login_at=user.last_login_at,
            created_at=user.created_at,
        )


class UserCreate(CamelModel):
    email: EmailStr = Field(examples=["ana@obras.uade.edu.ar"])
    full_name: str = Field(min_length=2, max_length=180, examples=["Ana Perez"])
    password: str = Field(
        min_length=8, description="Al menos 8 caracteres, combinando letras y numeros."
    )
    module: str | None = Field(
        default=None,
        description=(
            "Solo el equipo 9 puede crear cuentas en otro modulo. Si se omite, se "
            "usa el modulo de quien esta autenticado."
        ),
    )


class UserUpdate(CamelModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=180)
    active: bool | None = None


class PasswordUpdate(CamelModel):
    password: str = Field(min_length=8)


# ----------------------------------------------------------------------
# Modulos
# ----------------------------------------------------------------------
class ModuleResponse(CamelModel):
    id: uuid.UUID
    name: str
    display_name: str
    team: str
    description: str
    contact_email: str | None
    queue_name: str
    is_admin: bool
    active: bool
    subscription_count: int
    last_login_at: datetime | None
    last_publish_at: datetime | None

    @classmethod
    def of(cls, module: ModuleAccount) -> ModuleResponse:
        return cls(
            id=module.id,
            name=module.name,
            display_name=module.display_name,
            team=module.team,
            description=module.description,
            contact_email=module.contact_email,
            queue_name=module.effective_queue_name,
            is_admin=module.is_admin,
            active=module.active,
            subscription_count=sum(1 for s in module.subscriptions if s.active),
            last_login_at=module.last_login_at,
            last_publish_at=module.last_publish_at,
        )


class ModuleCreate(CamelModel):
    name: str = Field(
        min_length=2,
        max_length=60,
        examples=["obras"],
        description="Identificador tecnico en minuscula. Es el `sourceModule` de sus eventos.",
    )
    display_name: str = Field(min_length=2, max_length=160, examples=["Obras Publicas"])
    team: str = Field(default="", examples=["Equipo 3"])
    description: str = ""
    contact_email: str | None = None


class ModuleUpdate(CamelModel):
    display_name: str | None = Field(default=None, min_length=2, max_length=160)
    team: str | None = None
    description: str | None = None
    contact_email: str | None = None
    active: bool | None = None


class SecretResponse(CamelModel):
    module: str
    secret: str
    warning: str = "Guardalo ahora: el Core solo conserva su hash y no lo puede volver a mostrar."


# ----------------------------------------------------------------------
# Tipos de evento
# ----------------------------------------------------------------------
class EventTypeResponse(CamelModel):
    id: uuid.UUID
    name: str
    description: str
    owner_module: str | None
    discovered: bool = Field(
        description="Se auto-registro al aparecer por el hub: nadie lo habia declarado."
    )
    validates: bool = Field(description="Tiene JSON Schema declarado y se valida el `data`.")
    json_schema: dict[str, Any] | None
    total_received: int
    first_seen_at: datetime | None
    last_seen_at: datetime | None

    @classmethod
    def of(cls, event_type: EventType) -> EventTypeResponse:
        return cls(
            id=event_type.id,
            name=event_type.name,
            description=event_type.description,
            owner_module=event_type.owner_module,
            discovered=event_type.discovered,
            validates=event_type.json_schema is not None,
            json_schema=event_type.json_schema,
            total_received=event_type.total_received,
            first_seen_at=event_type.first_seen_at,
            last_seen_at=event_type.last_seen_at,
        )


class EventTypeCreate(CamelModel):
    name: str = Field(min_length=2, max_length=120, examples=["ticketCreated"])
    owner_module: str | None = Field(default=None, examples=["atencion-ciudadana"])
    description: str = ""
    json_schema: dict[str, Any] | None = Field(
        default=None,
        examples=[SCHEMA_EXAMPLE],
        description=(
            "**Opcional.** Sin schema el evento pasa sin que le miren el `data`. "
            "Con schema se valida la estructura del payload y lo que no cumple va "
            "a la DLQ."
        ),
    )


class SchemaUpdate(CamelModel):
    json_schema: dict[str, Any] | None = Field(
        default=None,
        examples=[SCHEMA_EXAMPLE],
        description="`null` desactiva la validacion y el evento vuelve a pasar sin mirar.",
    )


class EventTypeMapEntry(CamelModel):
    """Una fila del mapa de integracion: quien publica y quien consume cada tipo."""

    event_type: str
    description: str
    owner_module: str | None
    discovered: bool
    validates: bool
    total_received: int
    first_seen_at: datetime | None
    last_seen_at: datetime | None
    published_by: list[str]
    consumed_by: list[str]


# ----------------------------------------------------------------------
# Suscripciones y publicaciones
# ----------------------------------------------------------------------
class SubscriptionResponse(CamelModel):
    id: uuid.UUID
    module_name: str
    event_type: str
    queue_name: str
    max_attempts: int
    active: bool

    @classmethod
    def of(cls, subscription: Subscription) -> SubscriptionResponse:
        return cls(
            id=subscription.id,
            module_name=subscription.module.name,
            event_type=subscription.event_type.name,
            queue_name=subscription.target_queue,
            max_attempts=subscription.max_attempts,
            active=subscription.active,
        )


class SubscriptionCreate(CamelModel):
    event_type: str = Field(examples=["ticketCreated"])
    module: str | None = Field(
        default=None,
        description=(
            "Solo el admin puede suscribir a otro modulo. Si se omite, se usa el "
            "modulo autenticado."
        ),
    )
    max_attempts: int = Field(
        default=4, ge=1, le=10, description="Intentos antes de mandar el mensaje a la DLQ."
    )


class PublicationResponse(CamelModel):
    id: uuid.UUID
    module_name: str
    event_type: str
    active: bool

    @classmethod
    def of(cls, publication: Publication) -> PublicationResponse:
        return cls(
            id=publication.id,
            module_name=publication.module.name,
            event_type=publication.event_type.name,
            active=publication.active,
        )


class PublicationCreate(CamelModel):
    event_type: str = Field(examples=["workOrderScheduled"])
    module: str | None = Field(
        default=None, description="Solo el admin puede declarar por otro modulo."
    )


# ----------------------------------------------------------------------
# Eventos
# ----------------------------------------------------------------------
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


class EventSummaryResponse(CamelModel):
    """Version liviana para el listado (sin el sobre completo)."""

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


class EventDetailResponse(EventSummaryResponse):
    causation_id: uuid.UUID | None
    trace_id: str | None
    rejection_reason: str | None
    envelope: dict[str, Any]
    deliveries: list[DeliveryResponse]

    @classmethod
    def of_detail(cls, event: EventLog) -> EventDetailResponse:
        base = EventSummaryResponse.of(event)
        return cls(
            **base.model_dump(),
            causation_id=event.causation_id,
            trace_id=event.trace_id,
            rejection_reason=event.rejection_reason,
            envelope=event.envelope or {},
            deliveries=[DeliveryResponse.of(d) for d in event.deliveries],
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
    event_type_discovered: bool = Field(
        description="El tipo se registro solo: nadie lo habia declarado."
    )
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
            event_type_discovered=result.event_type_discovered,
            rejection_code=result.rejection_code,
            rejection_reason=result.rejection_reason,
            details=result.details,
        )


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
    details: list[Any] | None
    raw_payload: dict[str, Any] | None
    raw_body: str | None
    retries: list[RetryAuditResponse]

    @classmethod
    def of_detail(cls, dead_letter: DeadLetter) -> DeadLetterDetailResponse:
        base = DeadLetterResponse.of(dead_letter)
        return cls(
            **base.model_dump(),
            details=dead_letter.details,
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


# ----------------------------------------------------------------------
# Dashboard
# ----------------------------------------------------------------------
class IntegrationAlert(CamelModel):
    severity: str = Field(examples=["warning", "info"])
    kind: str = Field(
        examples=["NO_SUBSCRIBERS", "SIMILAR_NAMES", "UNDECLARED_TYPE", "NEVER_RECEIVED"]
    )
    event_type: str
    detail: str


class ModuleDashboardResponse(CamelModel):
    """El tablero de un modulo: solo su trafico."""

    module: str
    window_hours: int
    generated_at: datetime
    published: dict[str, Any]
    received: dict[str, Any]
    dead_letters: dict[str, Any]
    subscriptions: dict[str, Any]
    publications: dict[str, Any]
    volume_by_hour: list[dict[str, Any]]
    processing: dict[str, Any]


class GlobalDashboardResponse(CamelModel):
    """El tablero del equipo 9: el hub completo."""

    window_hours: int
    generated_at: datetime
    events: dict[str, Any]
    deliveries: dict[str, Any]
    dead_letters: dict[str, Any]
    modules: list[dict[str, Any]]
    volume_by_hour: list[dict[str, Any]]
    broker: dict[str, Any]
    integration_alerts: list[IntegrationAlert]


# ----------------------------------------------------------------------
# Topologia y salud
# ----------------------------------------------------------------------
class TopologyResponse(CamelModel):
    exchanges: list[dict[str, Any]]
    queues: list[dict[str, Any]]
    bindings: list[dict[str, Any]]

    @classmethod
    def of(cls, topology) -> TopologyResponse:
        return cls(
            exchanges=[
                {"name": e.name, "type": e.type, "durable": e.durable} for e in topology.exchanges
            ],
            queues=[
                {"name": q.name, "durable": q.durable, "arguments": q.arguments or {}}
                for q in topology.queues
            ],
            bindings=[
                {"queue": b.queue, "exchange": b.exchange, "routingKey": b.routing_key}
                for b in topology.bindings
            ],
        )


class LivenessResponse(CamelModel):
    status: str = "up"
    module: str
    version: str
    environment: str


class ReadinessResponse(CamelModel):
    """`degraded` = base arriba y broker caido: la API responde y los eventos
    esperan en `core.inbox` sin perderse."""

    status: str = Field(examples=["up", "degraded", "down"])
    checks: dict[str, Any]
