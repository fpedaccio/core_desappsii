"""Endpoints del catalogo de eventos y de los contratos.

El catalogo documentado que pide el enunciado se genera desde estas tablas
(`GET /event-types/catalog.md`), asi que siempre refleja lo que el hub valida.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import PlainTextResponse

from app.api.deps import ContractDep, require_permissions
from app.api.v1.schemas.common import PageResponse
from app.api.v1.schemas.integration import (
    CompatibilityCheckRequest,
    CompatibilityCheckResponse,
    ContractVersionCreate,
    ContractVersionResponse,
    EventTypeCreate,
    EventTypeResponse,
    EventTypeUpdate,
    ValidateSampleRequest,
    ValidateSampleResponse,
)
from app.core import permissions as perms
from app.models.contracts import EventTypeStatus

router = APIRouter(prefix="/event-types", tags=["Catalogo de eventos"])


@router.get(
    "",
    response_model=PageResponse[EventTypeResponse],
    dependencies=[Depends(require_permissions(perms.CONTRACTS_READ))],
    summary="Listar tipos de evento",
)
async def list_event_types(
    service: ContractDep,
    query: str | None = Query(default=None, description="Busca por nombre o descripcion"),
    owner_module: str | None = Query(default=None, alias="ownerModule"),
    status_filter: EventTypeStatus | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> PageResponse[EventTypeResponse]:
    result = await service.search_types(
        query=query, owner_module=owner_module, status=status_filter, page=page, size=size
    )
    return PageResponse.build(result, EventTypeResponse.of)


@router.get(
    "/catalog.md",
    response_class=PlainTextResponse,
    dependencies=[Depends(require_permissions(perms.CONTRACTS_READ))],
    summary="Catalogo de eventos documentado (Markdown)",
    description=(
        "Documento generado desde el catalogo real. Es el archivo que se publica "
        "como `docs/catalogo-eventos.md` para los otros 8 equipos."
    ),
)
async def catalog_markdown(service: ContractDep) -> PlainTextResponse:
    return PlainTextResponse(
        await service.render_catalog_markdown(), media_type="text/markdown; charset=utf-8"
    )


@router.post(
    "",
    response_model=EventTypeResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(perms.CONTRACTS_WRITE))],
    summary="Registrar un tipo de evento",
    description=(
        "Un tipo sin registrar no se puede publicar en el hub: sin catalogo el Core "
        "no sabe validarlo ni a quien entregarlo."
    ),
)
async def create_event_type(payload: EventTypeCreate, service: ContractDep) -> EventTypeResponse:
    event_type = await service.create_type(
        name=payload.name, owner_module=payload.owner_module, description=payload.description
    )
    return EventTypeResponse.of(event_type)


@router.get(
    "/{event_type_id}",
    response_model=EventTypeResponse,
    dependencies=[Depends(require_permissions(perms.CONTRACTS_READ))],
    summary="Ver un tipo de evento con todas sus versiones",
)
async def get_event_type(event_type_id: uuid.UUID, service: ContractDep) -> EventTypeResponse:
    event_type = await service.get_type(event_type_id)
    return EventTypeResponse.of(event_type, include_versions=True)


@router.patch(
    "/{event_type_id}",
    response_model=EventTypeResponse,
    dependencies=[Depends(require_permissions(perms.CONTRACTS_WRITE))],
    summary="Editar un tipo de evento",
)
async def update_event_type(
    event_type_id: uuid.UUID, payload: EventTypeUpdate, service: ContractDep
) -> EventTypeResponse:
    event_type = await service.update_type(
        event_type_id,
        description=payload.description,
        owner_module=payload.owner_module,
        status=payload.status,
    )
    return EventTypeResponse.of(event_type, include_versions=True)


@router.get(
    "/{event_type_id}/versions",
    response_model=list[ContractVersionResponse],
    dependencies=[Depends(require_permissions(perms.CONTRACTS_READ))],
    summary="Listar versiones de contrato",
)
async def list_versions(
    event_type_id: uuid.UUID, service: ContractDep
) -> list[ContractVersionResponse]:
    versions = await service.list_versions(event_type_id)
    return [ContractVersionResponse.of(version) for version in versions]


@router.post(
    "/{event_type_id}/versions",
    response_model=ContractVersionResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(perms.CONTRACTS_WRITE))],
    summary="Crear una version de contrato",
    description=(
        "Registra un JSON Schema (draft 2020-12) y lo clasifica contra la ultima "
        "version publicada: BACKWARD, FORWARD, FULL o BREAKING. La clasificacion "
        "queda guardada con la version."
    ),
)
async def create_version(
    event_type_id: uuid.UUID, payload: ContractVersionCreate, service: ContractDep
) -> ContractVersionResponse:
    version = await service.create_version(
        event_type_id,
        version=payload.version,
        json_schema=payload.json_schema,
        example=payload.example,
        publish=payload.publish,
    )
    return ContractVersionResponse.of(version)


@router.post(
    "/{event_type_id}/compatibility-check",
    response_model=CompatibilityCheckResponse,
    dependencies=[Depends(require_permissions(perms.CONTRACTS_READ))],
    summary="Clasificar un schema candidato sin publicarlo",
    description=(
        "Compara un schema contra la ultima version publicada y explica cada cambio "
        "que rompe compatibilidad, y en que direccion. No persiste nada."
    ),
)
async def compatibility_check(
    event_type_id: uuid.UUID, payload: CompatibilityCheckRequest, service: ContractDep
) -> CompatibilityCheckResponse:
    result = await service.check_compatibility(
        event_type_id, candidate_schema=payload.json_schema
    )
    return CompatibilityCheckResponse(**result)


@router.post(
    "/versions/{version_id}/publish",
    response_model=ContractVersionResponse,
    dependencies=[Depends(require_permissions(perms.CONTRACTS_PUBLISH))],
    summary="Publicar una version en borrador",
)
async def publish_version(version_id: uuid.UUID, service: ContractDep) -> ContractVersionResponse:
    return ContractVersionResponse.of(await service.publish_version(version_id))


@router.post(
    "/versions/{version_id}/deprecate",
    response_model=ContractVersionResponse,
    dependencies=[Depends(require_permissions(perms.CONTRACTS_PUBLISH))],
    summary="Marcar una version como obsoleta",
    description=(
        "Deprecar avisa a los equipos pero **no** rompe la integracion: el hub sigue "
        "aceptando la version, porque hay eventos en vuelo que la declaran."
    ),
)
async def deprecate_version(
    version_id: uuid.UUID, service: ContractDep
) -> ContractVersionResponse:
    return ContractVersionResponse.of(await service.deprecate_version(version_id))


@router.post(
    "/validate-sample",
    response_model=ValidateSampleResponse,
    dependencies=[Depends(require_permissions(perms.CONTRACTS_READ))],
    summary="Probar un payload contra un contrato",
    description=(
        "Herramienta para los otros equipos: valida un `data` de ejemplo contra el "
        "contrato antes de publicar el evento de verdad. Si no cumple, responde 422 "
        "con los campos que fallaron."
    ),
)
async def validate_sample(
    payload: ValidateSampleRequest, service: ContractDep
) -> ValidateSampleResponse:
    await service.validate_sample(
        event_type_name=payload.event_type, version=payload.version, data=payload.data
    )
    return ValidateSampleResponse(
        valid=True,
        message=(
            f"El payload cumple el contrato de '{payload.event_type}' "
            f"v{payload.version}."
        ),
    )
