"""Monitoreo y auditoria: health checks de los modulos y bitacora de acciones."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Index, String, Text
from sqlalchemy import Uuid as SAUuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, JSONType, TimestampMixin, TimestampTZ


class HealthStatus(str, enum.Enum):
    UP = "UP"
    DEGRADED = "DEGRADED"
    DOWN = "DOWN"
    UNKNOWN = "UNKNOWN"


class HealthCheck(Base, TimestampMixin):
    """Resultado de un sondeo al `health_url` de un modulo registrado.

    Se guarda historico (una fila por sondeo) para poder mostrar disponibilidad
    en el tiempo, no solo el estado actual.
    """

    __tablename__ = "health_checks"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    module_name: Mapped[str] = mapped_column(String(60), index=True)
    status: Mapped[HealthStatus] = mapped_column(String(10), default=HealthStatus.UNKNOWN)
    latency_ms: Mapped[int | None] = mapped_column(default=None)
    http_status: Mapped[int | None] = mapped_column(default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    checked_at: Mapped[datetime] = mapped_column(TimestampTZ, index=True)

    __table_args__ = (Index("ix_health_module_checked", "module_name", "checked_at"),)


class AuditLog(Base, TimestampMixin):
    """Quien hizo que sobre que entidad. Lo consume el rol AUDITOR."""

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    actor: Mapped[str] = mapped_column(String(180), index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(80), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(80), default=None)
    summary: Mapped[str] = mapped_column(String(255), default="")
    changes: Mapped[dict | None] = mapped_column(JSONType, default=None)
    trace_id: Mapped[str | None] = mapped_column(String(60), index=True, default=None)
    occurred_at: Mapped[datetime] = mapped_column(TimestampTZ, index=True)
