"""Catalogo de eventos y versionado de contratos.

Cada tipo de evento tiene un modulo propietario y N versiones, cada una con su
JSON Schema. El Core valida los eventos entrantes contra el schema de la version
declarada y clasifica la compatibilidad al publicar una version nueva.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy import Uuid as SAUuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, JSONType, TimestampMixin, TimestampTZ


class EventTypeStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"


class Compatibility(str, enum.Enum):
    """Resultado de comparar una version contra la anterior.

    BACKWARD: un consumidor viejo puede leer datos nuevos.
    FORWARD:  un consumidor nuevo puede leer datos viejos.
    FULL:     ambas.
    BREAKING: rompe a alguno de los dos lados.
    """

    BACKWARD = "BACKWARD"
    FORWARD = "FORWARD"
    FULL = "FULL"
    BREAKING = "BREAKING"


class EventType(Base, TimestampMixin):
    __tablename__ = "event_types"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    # Nombre tal como viaja en el sobre: "ReclamoDerivado", "PagoRegistrado".
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    # Cada dato tiene un unico modulo propietario (regla 8 del enunciado).
    owner_module: Mapped[str] = mapped_column(String(60), index=True)
    status: Mapped[EventTypeStatus] = mapped_column(String(20), default=EventTypeStatus.ACTIVE)

    versions: Mapped[list[EventContractVersion]] = relationship(
        back_populates="event_type",
        cascade="all, delete-orphan",
        order_by="EventContractVersion.created_at",
        lazy="selectin",
    )

    @property
    def latest_version(self) -> EventContractVersion | None:
        published = [v for v in self.versions if v.published_at is not None]
        return published[-1] if published else (self.versions[-1] if self.versions else None)


class EventContractVersion(Base, TimestampMixin):
    __tablename__ = "event_contract_versions"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    event_type_id: Mapped[uuid.UUID] = mapped_column(
        SAUuid, ForeignKey("event_types.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[str] = mapped_column(String(20))
    # JSON Schema draft 2020-12 que describe el campo `data` del sobre.
    json_schema: Mapped[dict] = mapped_column(JSONType, default=dict)
    compatibility: Mapped[Compatibility | None] = mapped_column(String(20), default=None)
    compatibility_notes: Mapped[list] = mapped_column(JSONType, default=list)
    published_at: Mapped[datetime | None] = mapped_column(TimestampTZ, default=None)
    deprecated_at: Mapped[datetime | None] = mapped_column(TimestampTZ, default=None)
    # Ejemplo valido, usado en la documentacion generada del catalogo.
    example: Mapped[dict | None] = mapped_column(JSONType, default=None)

    event_type: Mapped[EventType] = relationship(back_populates="versions")

    __table_args__ = (
        UniqueConstraint("event_type_id", "version", name="uq_contract_type_version"),
    )

    @property
    def is_published(self) -> bool:
        return self.published_at is not None and self.deprecated_at is None


class RegisteredModule(Base, TimestampMixin):
    """Un modulo de la plataforma dado de alta en el registry de integracion."""

    __tablename__ = "modules"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    team: Mapped[str] = mapped_column(String(120), default="")
    base_url: Mapped[str | None] = mapped_column(String(255), default=None)
    health_url: Mapped[str | None] = mapped_column(String(255), default=None)
    contact_email: Mapped[str | None] = mapped_column(String(255), default=None)
    # Cola destino del modulo. El Core la declara y le bindea sus suscripciones.
    queue_name: Mapped[str | None] = mapped_column(String(120), default=None)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    producers: Mapped[list[Producer]] = relationship(
        back_populates="module", cascade="all, delete-orphan"
    )
    subscriptions: Mapped[list[Subscription]] = relationship(
        back_populates="module", cascade="all, delete-orphan"
    )

    @property
    def effective_queue_name(self) -> str:
        return self.queue_name or f"q.{self.name}"


class Producer(Base, TimestampMixin):
    """Declaracion de que un modulo publica un tipo de evento."""

    __tablename__ = "producers"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    module_id: Mapped[uuid.UUID] = mapped_column(
        SAUuid, ForeignKey("modules.id", ondelete="CASCADE"), index=True
    )
    event_type_id: Mapped[uuid.UUID] = mapped_column(
        SAUuid, ForeignKey("event_types.id", ondelete="CASCADE"), index=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    module: Mapped[RegisteredModule] = relationship(back_populates="producers")
    event_type: Mapped[EventType] = relationship(lazy="joined")

    __table_args__ = (
        UniqueConstraint("module_id", "event_type_id", name="uq_producers_module_event"),
    )


class Subscription(Base, TimestampMixin):
    """Declaracion de que un modulo consume un tipo de evento.

    Es la tabla que gobierna el ruteo: el hub entrega un evento a las
    suscripciones activas de ese tipo, y nada mas.
    """

    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    module_id: Mapped[uuid.UUID] = mapped_column(
        SAUuid, ForeignKey("modules.id", ondelete="CASCADE"), index=True
    )
    event_type_id: Mapped[uuid.UUID] = mapped_column(
        SAUuid, ForeignKey("event_types.id", ondelete="CASCADE"), index=True
    )
    # Cola propia de la suscripcion; si es nula se usa la del modulo.
    queue_name: Mapped[str | None] = mapped_column(String(120), default=None)
    max_attempts: Mapped[int] = mapped_column(default=4)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    module: Mapped[RegisteredModule] = relationship(back_populates="subscriptions")
    event_type: Mapped[EventType] = relationship(lazy="joined")

    __table_args__ = (
        UniqueConstraint("module_id", "event_type_id", name="uq_subscriptions_module_event"),
    )

    @property
    def target_queue(self) -> str:
        return self.queue_name or self.module.effective_queue_name
