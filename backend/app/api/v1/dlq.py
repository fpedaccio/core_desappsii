"""Endpoints de la Dead Letter Queue.

Nada se borra: los mensajes fallidos se reintentan o se descartan con motivo, y
las dos cosas quedan auditadas con el usuario que las ejecuto.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query

from app.api.deps import (
    DeadLetterRepoDep,
    DeliveryDep,
    DeliveryRepoDep,
    RetryAuditRepoDep,
    require_permissions,
)
from app.api.v1.schemas.common import PageResponse
from app.api.v1.schemas.events import (
    BulkRetryRequest,
    BulkRetryResponse,
    DeadLetterDetailResponse,
    DeadLetterResponse,
    DeliveryResponse,
    DiscardRequest,
    RetryAuditResponse,
    RetryResultResponse,
)
from app.core import permissions as perms
from app.core.errors import NotFoundError
from app.models.events import DeadLetterStatus, DeliveryStatus

router = APIRouter(prefix="/dlq", tags=["Dead Letter Queue"])


@router.get(
    "",
    response_model=PageResponse[DeadLetterResponse],
    dependencies=[Depends(require_permissions(perms.DLQ_READ))],
    summary="Listar mensajes en la DLQ",
)
async def list_dead_letters(
    repo: DeadLetterRepoDep,
    query: str | None = Query(default=None, description="Busca por tipo, motivo o codigo"),
    status_filter: DeadLetterStatus | None = Query(default=None, alias="status"),
    event_type: str | None = Query(default=None, alias="eventType"),
    target_module: str | None = Query(default=None, alias="targetModule"),
    reason_code: str | None = Query(
        default=None,
        alias="reasonCode",
        description="SCHEMA_VIOLATION, UNKNOWN_EVENT_TYPE, DELIVERY_FAILED, ...",
    ),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> PageResponse[DeadLetterResponse]:
    result = await repo.search(
        query=query,
        status=status_filter,
        event_type=event_type,
        target_module=target_module,
        reason_code=reason_code,
        page=page,
        size=size,
    )
    return PageResponse.build(result, DeadLetterResponse.of)


@router.get(
    "/{dead_letter_id}",
    response_model=DeadLetterDetailResponse,
    dependencies=[Depends(require_permissions(perms.DLQ_READ))],
    summary="Ver un mensaje de la DLQ con su payload y sus reintentos",
)
async def get_dead_letter(
    dead_letter_id: uuid.UUID, repo: DeadLetterRepoDep
) -> DeadLetterDetailResponse:
    dead_letter = await repo.get_with_retries(dead_letter_id)
    if dead_letter is None:
        raise NotFoundError(f"No existe la dead letter {dead_letter_id}.")
    return DeadLetterDetailResponse.of_detail(dead_letter)


@router.post(
    "/{dead_letter_id}/retry",
    response_model=RetryResultResponse,
    dependencies=[Depends(require_permissions(perms.DLQ_RETRY))],
    summary="Reintentar un mensaje",
    description=(
        "Segun la causa hay dos caminos:\n\n"
        "- **Problema de configuracion del Core** (`UNKNOWN_EVENT_TYPE`, "
        "`UNKNOWN_CONTRACT_VERSION`, `SCHEMA_VIOLATION`): se reprocesa el evento ya "
        "guardado. Registra el tipo o corregi el schema y reintenta, sin pedirle al "
        "modulo origen que publique de nuevo.\n"
        "- **Entrega fallida** (`DELIVERY_FAILED`): se republica en la cola del "
        "modulo destino con el contador de intentos reiniciado.\n\n"
        "Un `MALFORMED_MESSAGE` no se puede reintentar: no tiene sobre valido, hay "
        "que descartarlo con motivo."
    ),
)
async def retry_dead_letter(
    dead_letter_id: uuid.UUID, service: DeliveryDep
) -> RetryResultResponse:
    outcome = await service.retry_dead_letter(dead_letter_id)
    return RetryResultResponse(
        dead_letter_id=outcome.dead_letter_id,
        success=outcome.success,
        message=outcome.message,
        attempt_number=outcome.attempt_number,
    )


@router.post(
    "/retry-bulk",
    response_model=BulkRetryResponse,
    dependencies=[Depends(require_permissions(perms.DLQ_RETRY))],
    summary="Reintentar varios mensajes",
    description=(
        "Reintento masivo. Cada mensaje se procesa y se audita por separado: un "
        "fallo no interrumpe los demas."
    ),
)
async def retry_bulk(payload: BulkRetryRequest, service: DeliveryDep) -> BulkRetryResponse:
    outcome = await service.retry_many(payload.dead_letter_ids)
    return BulkRetryResponse(
        total=outcome.total,
        succeeded=outcome.succeeded,
        failed=outcome.failed,
        results=[
            RetryResultResponse(
                dead_letter_id=item.dead_letter_id,
                success=item.success,
                message=item.message,
                attempt_number=item.attempt_number,
            )
            for item in outcome.results
        ],
    )


@router.post(
    "/{dead_letter_id}/discard",
    response_model=DeadLetterDetailResponse,
    dependencies=[Depends(require_permissions(perms.DLQ_DISCARD))],
    summary="Descartar un mensaje con motivo",
    description="El motivo es obligatorio y queda en la auditoria. El registro se conserva.",
)
async def discard_dead_letter(
    dead_letter_id: uuid.UUID, payload: DiscardRequest, service: DeliveryDep
) -> DeadLetterDetailResponse:
    dead_letter = await service.discard_dead_letter(dead_letter_id, reason=payload.reason)
    return DeadLetterDetailResponse.of_detail(dead_letter)


@router.get(
    "/{dead_letter_id}/audit",
    response_model=PageResponse[RetryAuditResponse],
    dependencies=[Depends(require_permissions(perms.DLQ_READ))],
    summary="Auditoria de reintentos de un mensaje",
)
async def retry_audit(
    dead_letter_id: uuid.UUID,
    repo: RetryAuditRepoDep,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> PageResponse[RetryAuditResponse]:
    result = await repo.search(dead_letter_id=dead_letter_id, page=page, size=size)
    return PageResponse.build(result, RetryAuditResponse.of)


deliveries_router = APIRouter(prefix="/deliveries", tags=["Dead Letter Queue"])


@deliveries_router.get(
    "",
    response_model=PageResponse[DeliveryResponse],
    dependencies=[Depends(require_permissions(perms.EVENTS_READ))],
    summary="Listar entregas",
    description="Estado de entrega por modulo destino: pendientes, entregadas, en reintento.",
)
async def list_deliveries(
    repo: DeliveryRepoDep,
    target_module: str | None = Query(default=None, alias="targetModule"),
    status_filter: DeliveryStatus | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> PageResponse[DeliveryResponse]:
    result = await repo.search(
        target_module=target_module, status=status_filter, page=page, size=size
    )
    return PageResponse.build(result, DeliveryResponse.of)


@deliveries_router.post(
    "/process-due-retries",
    dependencies=[Depends(require_permissions(perms.DLQ_RETRY))],
    summary="Procesar reintentos vencidos",
    description=(
        "Completa las entregas que quedaron pendientes porque el broker estaba "
        "caido al momento del ruteo. Lo corre tambien un worker en background; este "
        "endpoint permite forzarlo desde el panel cuando el broker vuelve."
    ),
)
async def process_due_retries(
    service: DeliveryDep,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    processed = await service.process_due_retries(limit=limit)
    return {"processed": processed}
