"""Modulos, sus credenciales y sus suscripciones.

El Core no administra usuarios de la plataforma ni ciudadanos: administra
**modulos**. Cada equipo tiene una cuenta con la que entra al dashboard y con
la que publica eventos. Nada mas.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy import Uuid as SAUuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, JSONType, TimestampMixin, TimestampTZ


class ModuleAccount(Base, TimestampMixin):
    """Un modulo de la plataforma, con su credencial.

    Es a la vez la identidad para el dashboard y la credencial para publicar.
    `is_admin` distingue al equipo 9: ve los eventos de todos los modulos, no
    solo los propios.
    """

    __tablename__ = "modules"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    # Identificador tecnico en minuscula. Es el `sourceModule` de sus eventos y
    # define el nombre de su cola.
    name: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(160))
    team: Mapped[str] = mapped_column(String(80), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    contact_email: Mapped[str | None] = mapped_column(String(255), default=None)

    # Credencial para el dashboard y para publicar. Solo se guarda el hash.
    secret_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    queue_name: Mapped[str | None] = mapped_column(String(120), default=None)
    last_login_at: Mapped[datetime | None] = mapped_column(TimestampTZ, default=None)
    last_publish_at: Mapped[datetime | None] = mapped_column(TimestampTZ, default=None)

    subscriptions: Mapped[list[Subscription]] = relationship(
        back_populates="module", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def effective_queue_name(self) -> str:
        return self.queue_name or f"q.{self.name}"


class EventType(Base, TimestampMixin):
    """Un tipo de evento que circula por el hub.

    **Se auto-registra la primera vez que se ve.** El Core es un pasamanos: no
    exige que un tipo este declarado de antemano para dejarlo pasar. Eso importa
    porque los equipos todavia estan alineando nombres, y un tipo que aparece
    solo se hace visible en el dashboard en vez de trabar la integracion.

    El `json_schema` es **opcional**. Sin schema el evento pasa sin mirarle el
    `data`; con schema se valida la estructura del payload y lo que no cumple va
    a la DLQ. Asi cada equipo decide cuando quiere la red de contencion, sin
    frenar a los que todavia estan acomodando nombres.
    """

    __tablename__ = "event_types"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    # Modulo que se declara dueno del evento. Informativo, no se valida.
    owner_module: Mapped[str | None] = mapped_column(String(60), index=True, default=None)
    # True cuando aparecio por el hub sin estar declarado antes. Es la senal de
    # "alguien publica esto y nadie lo habia anunciado".
    discovered: Mapped[bool] = mapped_column(Boolean, default=False)

    # JSON Schema (draft 2020-12) del campo `data`. Nulo = no se valida.
    json_schema: Mapped[dict | None] = mapped_column(JSONType, default=None)
    first_seen_at: Mapped[datetime | None] = mapped_column(TimestampTZ, default=None)
    last_seen_at: Mapped[datetime | None] = mapped_column(TimestampTZ, default=None)
    total_received: Mapped[int] = mapped_column(default=0)

    subscriptions: Mapped[list[Subscription]] = relationship(
        back_populates="event_type", cascade="all, delete-orphan"
    )


class Subscription(Base, TimestampMixin):
    """Un modulo quiere recibir un tipo de evento.

    Es la unica tabla que gobierna el ruteo. El hub entrega un evento a las
    suscripciones activas de ese tipo, y a nadie mas.
    """

    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    module_id: Mapped[uuid.UUID] = mapped_column(
        SAUuid, ForeignKey("modules.id", ondelete="CASCADE"), index=True
    )
    event_type_id: Mapped[uuid.UUID] = mapped_column(
        SAUuid, ForeignKey("event_types.id", ondelete="CASCADE"), index=True
    )
    max_attempts: Mapped[int] = mapped_column(default=4)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    module: Mapped[ModuleAccount] = relationship(back_populates="subscriptions", lazy="joined")
    event_type: Mapped[EventType] = relationship(back_populates="subscriptions", lazy="joined")

    __table_args__ = (
        UniqueConstraint("module_id", "event_type_id", name="uq_subscriptions_module_event"),
    )

    @property
    def target_queue(self) -> str:
        return self.module.effective_queue_name


class Publication(Base, TimestampMixin):
    """Un modulo declara que publica un tipo de evento.

    Es documentacion, no un permiso: sirve para que el dashboard muestre el mapa
    de quien manda que. No se valida al publicar.
    """

    __tablename__ = "publications"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    module_id: Mapped[uuid.UUID] = mapped_column(
        SAUuid, ForeignKey("modules.id", ondelete="CASCADE"), index=True
    )
    event_type_id: Mapped[uuid.UUID] = mapped_column(
        SAUuid, ForeignKey("event_types.id", ondelete="CASCADE"), index=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    module: Mapped[ModuleAccount] = relationship(lazy="joined")
    event_type: Mapped[EventType] = relationship(lazy="joined")

    __table_args__ = (
        UniqueConstraint("module_id", "event_type_id", name="uq_publications_module_event"),
    )
