"""Endpoints del hub de eventos: ingesta HTTP y explorador de trazabilidad."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import (
    EventLogRepoDep,
    HubDep,
    InternalConsumerDep,
    PrincipalDep,
    ProcessedRepoDep,
    require_permissions,
)
from app.api.v1.schemas.common import PageResponse
from app.api.v1.schemas.events import (
    EventLogResponse,
    EventSummaryResponse,
    IngestResponse,
    JourneyResponse,
    ProcessedEventResponse,
)
from app.core import permissions as perms
from app.core.errors import NotFoundError
from app.models.events import EventStatus, IngestionChannel
from app.services.envelope import EventEnvelope
from app.services.registry_service import IDENTITY_EVENT_TYPES

router = APIRouter(prefix="/events", tags=["Hub de eventos"])


@router.post(
    "",
    response_model=IngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_permissions(perms.EVENTS_PUBLISH))],
    summary="Publicar un evento en el hub",
    description=(
        "Ingesta HTTP, equivalente a publicar en el exchange `muni.inbox`. Pasa por "
        "el mismo pipeline: idempotencia, validacion de contrato, evidencia y ruteo.\n\n"
        "**Codigos de estado**\n"
        "- `202` el evento se acepto y ruteo a sus suscriptores.\n"
        "- `200` el `eventId` ya se habia procesado: no se generan efectos nuevos.\n"
        "- `422` el sobre o el contrato no validan. El evento **igual queda "
        "registrado y en la DLQ**, y la respuesta trae el motivo.\n\n"
        "La respuesta siempre tiene la misma forma, incluso al rechazar, para que el "
        "modulo productor pueda seguir su evento en el panel."
    ),
)
async def ingest_event(
    envelope: EventEnvelope,
    hub: HubDep,
    consumer: InternalConsumerDep,
    principal: PrincipalDep,
    response: Response,
) -> IngestResponse:
    result = await hub.ingest(envelope, channel=IngestionChannel.HTTP)

    if result.duplicate:
        response.status_code = status.HTTP_200_OK
    elif not result.accepted:
        response.status_code = status.HTTP_422_UNPROCESSABLE_CONTENT

    # Si el Core esta suscripto al tipo, se procesa en linea: por HTTP no hay
    # entrega AMQP a `q.core.internal` que dispare el consumidor interno.
    if result.accepted and not result.duplicate and "core" in result.routed_to:
        await consumer.handle_event(envelope)

    return IngestResponse.of(result)


@router.get(
    "",
    response_model=PageResponse[EventSummaryResponse],
    dependencies=[Depends(require_permissions(perms.EVENTS_READ))],
    summary="Explorar la bitacora de eventos",
    description="Filtros por tipo, modulo origen, estado, correlacion y rango de fechas.",
)
async def search_events(
    repo: EventLogRepoDep,
    query: str | None = Query(default=None, description="Busca por tipo o modulo origen"),
    event_type: str | None = Query(default=None, alias="eventType"),
    source_module: str | None = Query(default=None, alias="sourceModule"),
    status_filter: EventStatus | None = Query(default=None, alias="status"),
    correlation_id: uuid.UUID | None = Query(default=None, alias="correlationId"),
    since: datetime | None = Query(default=None, description="Recibidos desde (ISO-8601)"),
    until: datetime | None = Query(default=None, description="Recibidos hasta (ISO-8601)"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> PageResponse[EventSummaryResponse]:
    result = await repo.search(
        query=query,
        event_type=event_type,
        source_module=source_module,
        status=status_filter,
        correlation_id=correlation_id,
        since=since,
        until=until,
        page=page,
        size=size,
    )
    return PageResponse.build(result, EventSummaryResponse.of)


@router.get(
    "/journey/{correlation_id}",
    response_model=JourneyResponse,
    dependencies=[Depends(require_permissions(perms.EVENTS_READ))],
    summary="Journey completa de una correlacion",
    description=(
        "Todos los eventos que comparten `correlationId`, en orden cronologico. Es "
        "la vista que reconstruye el recorrido del ciudadano entre modulos."
    ),
)
async def get_journey(
    correlation_id: uuid.UUID, repo: EventLogRepoDep
) -> JourneyResponse:
    events = await repo.by_correlation(correlation_id)
    if not events:
        raise NotFoundError(f"No hay eventos con correlationId {correlation_id}.")

    modules = sorted(
        {event.source_module for event in events}
        | {delivery.target_module for event in events for delivery in event.deliveries}
    )
    return JourneyResponse(
        correlation_id=correlation_id,
        event_count=len(events),
        modules_involved=modules,
        events=[EventSummaryResponse.of(event) for event in events],
    )


@router.get(
    "/by-event-id/{event_id}",
    response_model=EventLogResponse,
    dependencies=[Depends(require_permissions(perms.EVENTS_READ))],
    summary="Buscar un evento por su eventId de negocio",
    description=(
        "Busca por el `eventId` del sobre, que es el identificador que conoce el "
        "modulo productor."
    ),
)
async def get_event_by_event_id(
    event_id: uuid.UUID, repo: EventLogRepoDep
) -> EventLogResponse:
    event = await repo.get_by_event_id(event_id)
    if event is None:
        raise NotFoundError(f"No se registro ningun evento con eventId {event_id}.")
    return EventLogResponse.of(event)


@router.get(
    "/{log_id}",
    response_model=EventLogResponse,
    dependencies=[Depends(require_permissions(perms.EVENTS_READ))],
    summary="Ver un evento con sus entregas",
)
async def get_event(log_id: uuid.UUID, repo: EventLogRepoDep) -> EventLogResponse:
    event = await repo.get_with_deliveries(log_id)
    if event is None:
        raise NotFoundError(f"No existe el evento {log_id}.")
    return EventLogResponse.of(event)


@router.get(
    "/{event_id}/processed-by",
    response_model=list[ProcessedEventResponse],
    dependencies=[Depends(require_permissions(perms.EVENTS_READ))],
    summary="Consumidores que ya procesaron un evento",
    description=(
        "Marcas de idempotencia por consumidor. Los otros modulos pueden consultarlo "
        "para saber si ya aplicaron un evento antes de volver a procesarlo."
    ),
)
async def processed_by(
    event_id: uuid.UUID, repo: ProcessedRepoDep
) -> list[ProcessedEventResponse]:
    return [ProcessedEventResponse.of(item) for item in await repo.list_for_event(event_id)]


meta_router = APIRouter(prefix="/events-meta", tags=["Hub de eventos"])


@meta_router.get(
    "/envelope-schema",
    summary="Contrato del sobre comun de eventos",
    description=(
        "Devuelve el JSON Schema del sobre que comparten los 9 modulos, generado "
        "desde el modelo que el hub realmente valida. Es la referencia para los "
        "otros equipos."
    ),
)
async def envelope_schema(principal: PrincipalDep) -> dict:
    return {
        "schema": EventEnvelope.model_json_schema(by_alias=True),
        "notes": [
            "occurredAt exige offset de zona horaria: un timestamp sin offset se rechaza.",
            "eventId es la clave de idempotencia: reenviarlo no genera efectos nuevos.",
            "correlationId es opcional pero recomendado; habilita la vista de journey.",
            "El campo data se valida contra el JSON Schema de la version declarada.",
        ],
        "identityEventTypes": list(IDENTITY_EVENT_TYPES),
    }
