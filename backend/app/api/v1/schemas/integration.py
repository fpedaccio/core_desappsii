"""DTOs del catalogo de eventos y del registry de integracion."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import EmailStr, Field

from app.api.v1.schemas.common import CamelModel
from app.models.contracts import (
    Compatibility,
    EventContractVersion,
    EventType,
    EventTypeStatus,
    Producer,
    RegisteredModule,
    Subscription,
)

SCHEMA_EXAMPLE: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "reclamoId": {"type": "string"},
        "categoria": {"type": "string"},
        "areaDestino": {"type": "string"},
        "prioridad": {"type": "string", "enum": ["BAJA", "MEDIA", "ALTA", "CRITICA"]},
    },
    "required": ["reclamoId", "areaDestino"],
    "additionalProperties": True,
}


# ----------------------------------------------------------------------
# Contratos
# ----------------------------------------------------------------------
class ContractVersionResponse(CamelModel):
    id: uuid.UUID
    event_type_id: uuid.UUID
    version: str
    json_schema: dict[str, Any]
    compatibility: Compatibility | None
    compatibility_notes: list[Any]
    example: dict[str, Any] | None
    published_at: datetime | None
    deprecated_at: datetime | None
    is_published: bool

    @classmethod
    def of(cls, version: EventContractVersion) -> ContractVersionResponse:
        return cls(
            id=version.id,
            event_type_id=version.event_type_id,
            version=version.version,
            json_schema=version.json_schema or {},
            compatibility=version.compatibility,
            compatibility_notes=version.compatibility_notes or [],
            example=version.example,
            published_at=version.published_at,
            deprecated_at=version.deprecated_at,
            is_published=version.is_published,
        )


class ContractVersionCreate(CamelModel):
    version: str = Field(min_length=1, max_length=20, examples=["1.0"])
    json_schema: dict[str, Any] = Field(examples=[SCHEMA_EXAMPLE])
    example: dict[str, Any] | None = Field(
        default=None,
        description="Ejemplo de `data`. Si se envia, se valida contra el propio schema.",
    )
    publish: bool = Field(
        default=True,
        description="Publicar de inmediato. Sin publicar queda como borrador.",
    )


class EventTypeResponse(CamelModel):
    id: uuid.UUID
    name: str
    description: str
    owner_module: str
    status: EventTypeStatus
    version_count: int
    latest_version: str | None
    versions: list[ContractVersionResponse] = Field(default_factory=list)

    @classmethod
    def of(cls, event_type: EventType, *, include_versions: bool = False) -> EventTypeResponse:
        latest = event_type.latest_version
        return cls(
            id=event_type.id,
            name=event_type.name,
            description=event_type.description,
            owner_module=event_type.owner_module,
            status=event_type.status,
            version_count=len(event_type.versions),
            latest_version=latest.version if latest else None,
            versions=(
                [ContractVersionResponse.of(v) for v in event_type.versions]
                if include_versions
                else []
            ),
        )


class EventTypeCreate(CamelModel):
    name: str = Field(min_length=2, max_length=120, examples=["ReclamoDerivado"])
    owner_module: str = Field(min_length=2, max_length=60, examples=["atencion-ciudadana"])
    description: str = ""


class EventTypeUpdate(CamelModel):
    description: str | None = None
    owner_module: str | None = Field(default=None, min_length=2, max_length=60)
    status: EventTypeStatus | None = None


class CompatibilityCheckRequest(CamelModel):
    json_schema: dict[str, Any] = Field(examples=[SCHEMA_EXAMPLE])


class CompatibilityCheckResponse(CamelModel):
    compatibility: Compatibility
    base_version: str | None
    summary: str
    notes: list[dict[str, str]]


class ValidateSampleRequest(CamelModel):
    """Prueba un payload contra un contrato sin publicar nada.

    Es la herramienta que usan los otros equipos para verificar que su evento va
    a pasar el hub antes de mandarlo de verdad.
    """

    event_type: str = Field(examples=["ReclamoDerivado"])
    version: str = Field(default="1.0", examples=["1.0"])
    data: dict[str, Any]


class ValidateSampleResponse(CamelModel):
    valid: bool
    message: str


# ----------------------------------------------------------------------
# Registry
# ----------------------------------------------------------------------
class ModuleResponse(CamelModel):
    id: uuid.UUID
    name: str
    display_name: str
    description: str
    team: str
    base_url: str | None
    health_url: str | None
    contact_email: str | None
    queue_name: str
    active: bool

    @classmethod
    def of(cls, module: RegisteredModule) -> ModuleResponse:
        return cls(
            id=module.id,
            name=module.name,
            display_name=module.display_name,
            description=module.description,
            team=module.team,
            base_url=module.base_url,
            health_url=module.health_url,
            contact_email=module.contact_email,
            queue_name=module.effective_queue_name,
            active=module.active,
        )


class ModuleCreate(CamelModel):
    name: str = Field(
        min_length=2,
        max_length=60,
        examples=["obras"],
        description="Identificador tecnico en minuscula. Es el `sourceModule` de sus eventos.",
    )
    display_name: str = Field(min_length=2, max_length=160, examples=["Obras Publicas"])
    description: str = ""
    team: str = ""
    base_url: str | None = None
    health_url: str | None = Field(
        default=None,
        description="Endpoint que el Core sondea para el tablero de salud.",
        examples=["https://obras.onrender.com/health/live"],
    )
    contact_email: EmailStr | None = None
    queue_name: str | None = Field(
        default=None, description="Por defecto q.<nombre>."
    )


class ModuleUpdate(CamelModel):
    display_name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = None
    team: str | None = None
    base_url: str | None = None
    health_url: str | None = None
    contact_email: EmailStr | None = None
    active: bool | None = None


class ProducerResponse(CamelModel):
    id: uuid.UUID
    module_name: str
    event_type: str
    active: bool

    @classmethod
    def of(cls, producer: Producer) -> ProducerResponse:
        return cls(
            id=producer.id,
            module_name=producer.module.name,
            event_type=producer.event_type.name,
            active=producer.active,
        )


class ProducerCreate(CamelModel):
    module_name: str = Field(examples=["atencion-ciudadana"])
    event_type: str = Field(examples=["ReclamoDerivado"])


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
    module_name: str = Field(examples=["obras"])
    event_type: str = Field(examples=["ReclamoDerivado"])
    queue_name: str | None = Field(default=None, description="Por defecto, la cola del modulo.")
    max_attempts: int = Field(
        default=4,
        ge=1,
        le=10,
        description="Intentos antes de mandar el mensaje a la DLQ.",
    )


class SubscriptionUpdate(CamelModel):
    active: bool | None = None
    max_attempts: int | None = Field(default=None, ge=1, le=10)
    queue_name: str | None = None


# ----------------------------------------------------------------------
# Topologia
# ----------------------------------------------------------------------
class ExchangeInfo(CamelModel):
    name: str
    type: str
    durable: bool


class QueueInfo(CamelModel):
    name: str
    durable: bool
    arguments: dict[str, Any]


class BindingInfo(CamelModel):
    queue: str
    exchange: str
    routing_key: str


class TopologyResponse(CamelModel):
    """Topologia derivada del registry. Es lo que el Core declara en el broker."""

    exchanges: list[ExchangeInfo]
    queues: list[QueueInfo]
    bindings: list[BindingInfo]
    applied: bool = Field(description="Si se logro declararla en el broker en esta llamada.")

    @classmethod
    def of(cls, topology, *, applied: bool) -> TopologyResponse:
        return cls(
            exchanges=[
                ExchangeInfo(name=e.name, type=e.type, durable=e.durable)
                for e in topology.exchanges
            ],
            queues=[
                QueueInfo(name=q.name, durable=q.durable, arguments=q.arguments or {})
                for q in topology.queues
            ],
            bindings=[
                BindingInfo(queue=b.queue, exchange=b.exchange, routing_key=b.routing_key)
                for b in topology.bindings
            ],
            applied=applied,
        )
