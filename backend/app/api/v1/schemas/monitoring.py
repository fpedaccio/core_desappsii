"""DTOs de monitoreo y auditoria."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from app.api.v1.schemas.common import CamelModel
from app.models.monitoring import AuditLog, HealthCheck, HealthStatus


class HealthCheckResponse(CamelModel):
    id: uuid.UUID
    module_name: str
    status: HealthStatus
    latency_ms: int | None
    http_status: int | None
    error: str | None
    checked_at: datetime

    @classmethod
    def of(cls, check: HealthCheck) -> HealthCheckResponse:
        return cls.model_validate(check)


class ModuleHealthResponse(CamelModel):
    module_name: str
    display_name: str
    status: str
    latency_ms: int | None
    http_status: int | None
    error: str | None
    checked_at: datetime | None
    uptime_24h: float = Field(description="Proporcion de sondeos exitosos en 24h (0..1).")


class LivenessResponse(CamelModel):
    status: str = "up"
    module: str
    version: str
    environment: str


class ComponentStatus(CamelModel):
    status: str
    error: str | None = None
    detail: str | None = None


class ReadinessResponse(CamelModel):
    """Readiness del Core.

    `degraded` significa base de datos arriba y broker caido: la API responde y
    los eventos esperan en `core.inbox` sin perderse.
    """

    status: str = Field(examples=["up", "degraded", "down"])
    checks: dict[str, ComponentStatus]


class AuditLogResponse(CamelModel):
    id: uuid.UUID
    actor: str
    action: str
    entity_type: str
    entity_id: str | None
    summary: str
    changes: dict[str, Any] | None
    trace_id: str | None
    occurred_at: datetime

    @classmethod
    def of(cls, entry: AuditLog) -> AuditLogResponse:
        return cls.model_validate(entry)


class TechnicalDashboardResponse(CamelModel):
    """Tablero tecnico. Se devuelve laxo a proposito: son metricas agregadas y el
    FE las grafica sin necesitar un contrato rigido por metrica."""

    window_hours: int
    generated_at: datetime
    events: dict[str, Any]
    deliveries: dict[str, Any]
    dead_letters: dict[str, Any]
    modules: list[dict[str, Any]]
    broker: dict[str, Any]


class CommunicationsDashboardResponse(CamelModel):
    window_hours: int
    generated_at: datetime
    total: int
    by_status: dict[str, int]
    by_channel: list[dict[str, Any]]
    top_templates: list[dict[str, Any]]
    success_rate: float | None
