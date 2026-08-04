"""Endpoints de monitoreo, tableros y auditoria."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query

from app.api.deps import (
    AuditRepoDep,
    HealthRepoDep,
    MonitoringDep,
    require_permissions,
)
from app.api.v1.schemas.common import PageResponse
from app.api.v1.schemas.monitoring import (
    AuditLogResponse,
    CommunicationsDashboardResponse,
    ComponentStatus,
    HealthCheckResponse,
    LivenessResponse,
    ModuleHealthResponse,
    ReadinessResponse,
    TechnicalDashboardResponse,
)
from app.core import permissions as perms
from app.core.config import settings

# Los endpoints de health van sin prefijo /api/v1 y sin autenticacion: los
# consumen la plataforma de despliegue y el poller de los otros modulos.
health_router = APIRouter(prefix="/health", tags=["Monitoreo"])


@health_router.get(
    "/live",
    response_model=LivenessResponse,
    summary="Liveness probe",
    description="Responde si el proceso esta vivo. No toca la base ni el broker.",
)
async def liveness() -> LivenessResponse:
    return LivenessResponse(
        module=settings.module_name, version="1.0.0", environment=settings.environment
    )


@health_router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    description=(
        "Chequea base de datos y broker.\n\n"
        "- `up`: todo en orden.\n"
        "- `degraded`: base arriba, broker caido. La API sigue respondiendo y los "
        "eventos esperan en `core.inbox` sin perderse.\n"
        "- `down`: sin base de datos."
    ),
)
async def readiness(service: MonitoringDep) -> ReadinessResponse:
    result = await service.readiness()
    return ReadinessResponse(
        status=result["status"],
        checks={
            name: ComponentStatus(**payload) for name, payload in result["checks"].items()
        },
    )


router = APIRouter(prefix="/monitoring", tags=["Monitoreo"])

_read = Depends(require_permissions(perms.MONITORING_READ))


@router.get(
    "/dashboard/technical",
    response_model=TechnicalDashboardResponse,
    dependencies=[_read],
    summary="Tablero tecnico",
    description=(
        "El pulso del hub: eventos por estado y por minuto, top de tipos, entregas "
        "por modulo, tamano de la DLQ por motivo, tiempos de procesamiento y salud "
        "de los 9 modulos."
    ),
)
async def technical_dashboard(
    service: MonitoringDep,
    window_hours: int = Query(default=24, ge=1, le=720, alias="windowHours"),
) -> TechnicalDashboardResponse:
    data = await service.technical_dashboard(window_hours=window_hours)
    return TechnicalDashboardResponse(**data)


@router.get(
    "/dashboard/communications",
    response_model=CommunicationsDashboardResponse,
    dependencies=[_read],
    summary="Tablero de comunicaciones",
    description="Notificaciones enviadas, fallidas y suprimidas por canal y plantilla.",
)
async def communications_dashboard(
    service: MonitoringDep,
    window_hours: int = Query(default=24, ge=1, le=720, alias="windowHours"),
) -> CommunicationsDashboardResponse:
    data = await service.communications_dashboard(window_hours=window_hours)
    return CommunicationsDashboardResponse(**data)


@router.get(
    "/modules",
    response_model=list[ModuleHealthResponse],
    dependencies=[_read],
    summary="Salud de los modulos de la plataforma",
    description="Ultimo sondeo de cada modulo registrado, con su disponibilidad de 24h.",
)
async def module_health(service: MonitoringDep) -> list[ModuleHealthResponse]:
    items = await service.module_health()
    return [
        ModuleHealthResponse(
            module_name=item.module_name,
            display_name=item.display_name,
            status=getattr(item.status, "value", str(item.status)),
            latency_ms=item.latency_ms,
            http_status=item.http_status,
            error=item.error,
            checked_at=item.checked_at,
            uptime_24h=item.uptime_24h,
        )
        for item in items
    ]


@router.post(
    "/modules/poll",
    response_model=list[HealthCheckResponse],
    dependencies=[_read],
    summary="Sondear ahora la salud de los modulos",
    description=(
        "Fuerza un sondeo inmediato. Tambien lo corre un worker periodico. Un modulo "
        "caido se registra como DOWN: no propaga el fallo al Core."
    ),
)
async def poll_modules(service: MonitoringDep) -> list[HealthCheckResponse]:
    checks = await service.poll_modules()
    return [HealthCheckResponse.of(check) for check in checks]


@router.get(
    "/modules/{module_name}/history",
    response_model=list[HealthCheckResponse],
    dependencies=[_read],
    summary="Historico de sondeos de un modulo",
)
async def module_history(
    module_name: str,
    repo: HealthRepoDep,
    since: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[HealthCheckResponse]:
    checks = await repo.history(module_name, since=since, limit=limit)
    return [HealthCheckResponse.of(check) for check in checks]


audit_router = APIRouter(prefix="/audit", tags=["Monitoreo"])


@audit_router.get(
    "",
    response_model=PageResponse[AuditLogResponse],
    dependencies=[Depends(require_permissions(perms.AUDIT_READ))],
    summary="Consultar la auditoria",
    description="Quien hizo que sobre que entidad, con el `traceId` de la operacion.",
)
async def list_audit(
    repo: AuditRepoDep,
    query: str | None = Query(default=None, description="Busca por resumen, actor o entidad"),
    actor: str | None = Query(default=None),
    action: str | None = Query(default=None),
    entity_type: str | None = Query(default=None, alias="entityType"),
    since: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> PageResponse[AuditLogResponse]:
    result = await repo.search(
        query=query,
        actor=actor,
        action=action,
        entity_type=entity_type,
        since=since,
        page=page,
        size=size,
    )
    return PageResponse.build(result, AuditLogResponse.of)
