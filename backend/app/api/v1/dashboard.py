"""El dashboard: estadisticas por modulo y la vista global del administrador."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import AdminDep, CallerDep, StatsDep
from app.api.v1.schemas.dto import (
    GlobalDashboardResponse,
    IntegrationAlert,
    ModuleDashboardResponse,
)
from app.core.errors import ForbiddenError

router = APIRouter(tags=["Dashboard"])


@router.get(
    "/dashboard",
    response_model=ModuleDashboardResponse,
    summary="Mi tablero",
    description=(
        "El tablero del modulo autenticado: cuantos eventos publico, cuantos "
        "recibio y en que estado quedaron, sus dead letters abiertas, sus "
        "suscripciones y el volumen por hora."
    ),
)
async def my_dashboard(
    caller: CallerDep,
    stats: StatsDep,
    window_hours: int = Query(default=24, ge=1, le=720, alias="windowHours"),
) -> ModuleDashboardResponse:
    data = await stats.module_dashboard(caller.module, window_hours=window_hours)
    return ModuleDashboardResponse(**data)


@router.get(
    "/dashboard/modules/{module_name}",
    response_model=ModuleDashboardResponse,
    summary="El tablero de un modulo",
    description=(
        "Un modulo solo puede pedir el propio (para eso esta `/dashboard`). El "
        "administrador puede pedir el de cualquiera."
    ),
)
async def module_dashboard(
    module_name: str,
    caller: CallerDep,
    stats: StatsDep,
    window_hours: int = Query(default=24, ge=1, le=720, alias="windowHours"),
) -> ModuleDashboardResponse:
    if not caller.is_admin and module_name.strip().lower() != caller.module:
        raise ForbiddenError(
            f"Estas autenticado como '{caller.module}' y solo podes ver tu propio tablero."
        )
    data = await stats.module_dashboard(module_name.strip().lower(), window_hours=window_hours)
    return ModuleDashboardResponse(**data)


@router.get(
    "/dashboard/global",
    response_model=GlobalDashboardResponse,
    summary="El tablero del hub",
    description=(
        "Solo el administrador. El pulso completo del pasamanos: eventos por "
        "estado y por minuto, entregas por modulo, DLQ por motivo, estado del "
        "broker y las alertas de integracion."
    ),
)
async def global_dashboard(
    admin: AdminDep,
    stats: StatsDep,
    window_hours: int = Query(default=24, ge=1, le=720, alias="windowHours"),
) -> GlobalDashboardResponse:
    data = await stats.global_dashboard(window_hours=window_hours)
    return GlobalDashboardResponse(**data)


@router.get(
    "/dashboard/integration-alerts",
    response_model=list[IntegrationAlert],
    summary="Alertas de integracion",
    description=(
        "Los agujeros de la integracion, detectados de los datos reales:\n\n"
        "- `NO_SUBSCRIBERS`: llegaron eventos de un tipo y nadie esta suscripto. "
        "Falta la suscripcion, o el nombre no coincide con el que espera el consumidor.\n"
        "- `SIMILAR_NAMES`: dos tipos con nombres casi iguales (`debtOverdue` vs "
        "`overdueDebt`, o un typo). Si son el mismo evento, hay que unificarlo.\n"
        "- `UNDECLARED_TYPE`: un tipo que se auto-registro al aparecer por el hub.\n"
        "- `NEVER_RECEIVED`: hay suscriptores esperando un tipo que nunca llego.\n\n"
        "Es lo que el pasamanos puede detectar sin conocer una sola regla de "
        "negocio: solo mirando quien manda que y quien escucha que."
    ),
)
async def integration_alerts(caller: CallerDep, stats: StatsDep) -> list[IntegrationAlert]:
    return [IntegrationAlert(**alert) for alert in await stats.integration_alerts()]
