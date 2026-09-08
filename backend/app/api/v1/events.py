"""El pasamanos: publicar eventos y consultar la bitacora."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Query, Response, status

from app.api.deps import CallerDep, EventLogRepoDep, HubDep, ModuleRepoDep
from app.api.v1.schemas.common import PageResponse
from app.api.v1.schemas.dto import (
    EventDetailResponse,
    EventSummaryResponse,
    IngestResponse,
    JourneyResponse,
)
from app.core.database import utcnow
from app.core.errors import ForbiddenError, NotFoundError
from app.models.events import EventStatus, IngestionChannel
from app.services.envelope import ENVELOPE_EXAMPLE, EventEnvelope

router = APIRouter(tags=["Eventos"])


@router.post(
    "/events",
    response_model=IngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Publicar un evento",
    description=(
        "Ingesta por HTTP, equivalente a publicar en el exchange `muni.inbox`.\n\n"
        "**Que hace el Core con el evento:**\n"
        "1. Si el `eventId` ya se vio, responde `200` con `duplicate: true` y no "
        "hace nada mas.\n"
        "2. Valida el sobre. `occurredAt` **necesita offset de zona horaria**.\n"
        "3. Si el tipo tiene JSON Schema declarado, valida el `data`. Si no, pasa "
        "sin mirarlo.\n"
        "4. Guarda el sobre como evidencia.\n"
        "5. Lo entrega a las suscripciones activas de ese tipo.\n\n"
        "Un tipo de evento que nadie declaro **no se rechaza**: se registra solo y "
        "queda marcado en el dashboard. Un evento que no cumple el schema tampoco "
        "se pierde: va a la DLQ con el detalle del campo."
    ),
    responses={
        202: {"description": "Aceptado y ruteado"},
        200: {"description": "Duplicado: ese eventId ya se habia procesado"},
        422: {"description": "El sobre o el `data` no validan. El evento queda en la DLQ."},
    },
)
async def publish_event(
    envelope: EventEnvelope,
    hub: HubDep,
    caller: CallerDep,
    module_repo: ModuleRepoDep,
    response: Response,
) -> IngestResponse:
    # Un modulo solo publica en su propio nombre. Si no, cualquiera podria
    # inyectar eventos haciendose pasar por otro equipo.
    if not caller.is_admin and envelope.source_module != caller.module:
        raise ForbiddenError(
            f"Estas autenticado como '{caller.module}' y el evento declara "
            f"sourceModule '{envelope.source_module}'. Solo podes publicar en tu "
            "propio nombre."
        )

    result = await hub.ingest(envelope, channel=IngestionChannel.HTTP)

    module = await module_repo.get_by_name(envelope.source_module)
    if module is not None:
        module.last_publish_at = utcnow()

    if result.duplicate:
        response.status_code = status.HTTP_200_OK
    elif result.status == EventStatus.REJECTED:
        response.status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    return IngestResponse.of(result)


@router.get(
    "/events",
    response_model=PageResponse[EventSummaryResponse],
    summary="Explorar la bitacora",
    description=(
        "Un modulo ve **solo su trafico**: lo que publico mas lo que le entregaron. "
        "El administrador ve todo. El filtro se aplica en la consulta, no con query "
        "params, asi que no se puede pedir el trafico de otro modulo."
    ),
)
async def list_events(
    caller: CallerDep,
    event_log_repo: EventLogRepoDep,
    query: str | None = Query(default=None, description="Busca por tipo o modulo origen"),
    event_type: str | None = Query(default=None, alias="eventType"),
    source_module: str | None = Query(default=None, alias="sourceModule"),
    target_module: str | None = Query(default=None, alias="targetModule"),
    status_filter: EventStatus | None = Query(default=None, alias="status"),
    correlation_id: uuid.UUID | None = Query(default=None, alias="correlationId"),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=25, ge=1, le=200),
) -> PageResponse[EventSummaryResponse]:
    result = await event_log_repo.search(
        module_scope=caller.scope,
        query=query,
        event_type=event_type,
        source_module=source_module,
        target_module=target_module,
        status=status_filter,
        correlation_id=correlation_id,
        since=since,
        until=until,
        page=page,
        size=size,
    )
    return PageResponse.build(result, EventSummaryResponse.of)


@router.get(
    "/events/{event_id}",
    response_model=EventDetailResponse,
    summary="Detalle de un evento",
    description=(
        "Por el `eventId` de negocio (el que mando el modulo). Trae el sobre "
        "completo y el estado de cada entrega."
    ),
)
async def get_event(
    event_id: uuid.UUID, caller: CallerDep, event_log_repo: EventLogRepoDep
) -> EventDetailResponse:
    event = await event_log_repo.get_by_event_id(event_id)
    if event is None:
        raise NotFoundError(f"No hay ningun evento con eventId {event_id}.")

    if caller.scope and not _visible_to(event, caller.scope):
        raise NotFoundError(f"No hay ningun evento con eventId {event_id}.")
    return EventDetailResponse.of_detail(event)


@router.get(
    "/events/journey/{correlation_id}",
    response_model=JourneyResponse,
    summary="La journey completa",
    description=(
        "Todos los eventos que comparten un `correlationId`, en orden cronologico. "
        "Es la vista que reconstruye el recorrido de un tramite entre modulos."
    ),
)
async def get_journey(correlation_id: uuid.UUID, caller: CallerDep, hub: HubDep) -> JourneyResponse:
    events = await hub.journey(correlation_id)
    if caller.scope:
        events = [e for e in events if _visible_to(e, caller.scope)]

    modules = sorted(
        {e.source_module for e in events} | {d.target_module for e in events for d in e.deliveries}
    )
    return JourneyResponse(
        correlation_id=correlation_id,
        event_count=len(events),
        modules_involved=modules,
        events=[EventSummaryResponse.of(e) for e in events],
    )


@router.get(
    "/events-meta/envelope-schema",
    summary="El contrato del sobre",
    description="El formato que tienen que respetar todos los eventos de la plataforma.",
)
async def envelope_schema() -> dict:
    return {
        "schema": EventEnvelope.model_json_schema(by_alias=True),
        "example": ENVELOPE_EXAMPLE,
        "rules": [
            "eventId es un UUID nuevo por evento. Es la clave de idempotencia: "
            "reenviarlo no genera efectos nuevos.",
            "occurredAt necesita offset de zona horaria (ej. -03:00). Un timestamp "
            "sin offset se rechaza.",
            "sourceModule tiene que coincidir con el modulo autenticado.",
            "correlationId es opcional pero se recomienda: propagalo cuando tu "
            "evento sale de consumir otro, y con eso se reconstruye la journey.",
            "data es libre. Solo se valida si el tipo de evento declaro un JSON Schema.",
        ],
    }


def _visible_to(event, module: str) -> bool:
    """Un modulo ve los eventos que publico y los que le entregaron."""
    return event.source_module == module or any(d.target_module == module for d in event.deliveries)
