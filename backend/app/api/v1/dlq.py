"""Dead Letter Queue: lo que fallo, y como recuperarlo."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from app.api.deps import (
    AdminDep,
    CallerDep,
    DeadLetterRepoDep,
    DeliveryDep,
    DeliveryRepoDep,
    RetryAuditRepoDep,
)
from app.api.v1.schemas.common import MessageResponse, PageResponse
from app.api.v1.schemas.dto import (
    BulkRetryRequest,
    BulkRetryResponse,
    DeadLetterDetailResponse,
    DeadLetterResponse,
    DeliveryResponse,
    DiscardRequest,
    RetryAuditResponse,
    RetryResultResponse,
)
from app.core.errors import NotFoundError
from app.models.events import DeadLetterStatus, DeliveryStatus

router = APIRouter(tags=["DLQ y entregas"])


@router.get(
    "/dlq",
    response_model=PageResponse[DeadLetterResponse],
    summary="Listar la DLQ",
    description=(
        "Un modulo ve las dead letters que lo involucran (como origen o como "
        "destino); el administrador ve todas.\n\n"
        "**Motivos posibles:**\n"
        "- `SCHEMA_VIOLATION`: el `data` no cumple el schema declarado del tipo. Se "
        "arregla corrigiendo el schema (o el evento) y reintentando.\n"
        "- `DELIVERY_FAILED`: el modulo destino agoto sus intentos. Cuando vuelve, "
        "se reintenta.\n"
        "- `MALFORMED_MESSAGE`: no era JSON valido. **No se puede reintentar**, hay "
        "que descartarlo con motivo."
    ),
)
async def list_dead_letters(
    caller: CallerDep,
    dead_letter_repo: DeadLetterRepoDep,
    query: str | None = Query(default=None),
    status_filter: DeadLetterStatus | None = Query(default=None, alias="status"),
    event_type: str | None = Query(default=None, alias="eventType"),
    target_module: str | None = Query(default=None, alias="targetModule"),
    reason_code: str | None = Query(default=None, alias="reasonCode"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=25, ge=1, le=200),
) -> PageResponse[DeadLetterResponse]:
    result = await dead_letter_repo.search(
        module_scope=caller.scope,
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
    "/dlq/{dead_letter_id}",
    response_model=DeadLetterDetailResponse,
    summary="Detalle de una dead letter",
    description="Con el payload crudo, el detalle del error y el historial de reintentos.",
)
async def get_dead_letter(
    dead_letter_id: uuid.UUID, caller: CallerDep, dead_letter_repo: DeadLetterRepoDep
) -> DeadLetterDetailResponse:
    dead_letter = await dead_letter_repo.get_with_retries(dead_letter_id)
    if dead_letter is None:
        raise NotFoundError(f"No existe la dead letter {dead_letter_id}.")

    if caller.scope and caller.scope not in {
        dead_letter.source_module,
        dead_letter.target_module,
    }:
        raise NotFoundError(f"No existe la dead letter {dead_letter_id}.")
    return DeadLetterDetailResponse.of_detail(dead_letter)


@router.post(
    "/dlq/{dead_letter_id}/retry",
    response_model=RetryResultResponse,
    summary="Reintentar",
    description=(
        "El Core elige el camino segun la causa, no hace falta decidirlo:\n\n"
        "- **`SCHEMA_VIOLATION`**: reprocesa el evento que ya tiene guardado. No "
        "hay que pedirle al modulo origen que lo publique de nuevo.\n"
        "- **`DELIVERY_FAILED`**: republica en la cola del destino con el contador "
        "de intentos reiniciado.\n\n"
        "Queda auditado con el modulo que lo disparo."
    ),
)
async def retry_dead_letter(
    dead_letter_id: uuid.UUID, admin: AdminDep, delivery: DeliveryDep
) -> RetryResultResponse:
    outcome = await delivery.retry_dead_letter(dead_letter_id)
    return RetryResultResponse(
        dead_letter_id=outcome.dead_letter_id,
        success=outcome.success,
        message=outcome.message,
        attempt_number=outcome.attempt_number,
    )


@router.post(
    "/dlq/retry-bulk",
    response_model=BulkRetryResponse,
    summary="Reintento masivo",
    description=(
        "Hasta 200 dead letters. Cada una se audita por separado y un fallo no "
        "interrumpe a las demas."
    ),
)
async def retry_bulk(
    payload: BulkRetryRequest, admin: AdminDep, delivery: DeliveryDep
) -> BulkRetryResponse:
    outcome = await delivery.retry_many(payload.dead_letter_ids)
    return BulkRetryResponse(
        total=outcome.total,
        succeeded=outcome.succeeded,
        failed=outcome.failed,
        results=[
            RetryResultResponse(
                dead_letter_id=r.dead_letter_id,
                success=r.success,
                message=r.message,
                attempt_number=r.attempt_number,
            )
            for r in outcome.results
        ],
    )


@router.post(
    "/dlq/{dead_letter_id}/discard",
    response_model=DeadLetterResponse,
    summary="Descartar con motivo",
    description=(
        "El motivo es **obligatorio** y queda en la auditoria. El registro se "
        "conserva siempre: descartar no borra nada."
    ),
)
async def discard_dead_letter(
    dead_letter_id: uuid.UUID,
    payload: DiscardRequest,
    admin: AdminDep,
    delivery: DeliveryDep,
) -> DeadLetterResponse:
    dead_letter = await delivery.discard_dead_letter(dead_letter_id, reason=payload.reason)
    return DeadLetterResponse.of(dead_letter)


@router.get(
    "/dlq/{dead_letter_id}/audit",
    response_model=PageResponse[RetryAuditResponse],
    summary="Auditoria de reintentos",
    description=(
        "Cada intento (automatico o manual) con quien lo hizo, cuando y que resultado dio."
    ),
)
async def dead_letter_audit(
    dead_letter_id: uuid.UUID,
    caller: CallerDep,
    retry_audit_repo: RetryAuditRepoDep,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=25, ge=1, le=200),
) -> PageResponse[RetryAuditResponse]:
    result = await retry_audit_repo.search(dead_letter_id=dead_letter_id, page=page, size=size)
    return PageResponse.build(result, RetryAuditResponse.of)


# ----------------------------------------------------------------------
# Entregas
# ----------------------------------------------------------------------
@router.get(
    "/deliveries",
    response_model=PageResponse[DeliveryResponse],
    summary="Listar entregas",
    description=("El estado de las entregas hacia un modulo. Un modulo solo ve las propias."),
)
async def list_deliveries(
    caller: CallerDep,
    delivery_repo: DeliveryRepoDep,
    status_filter: DeliveryStatus | None = Query(default=None, alias="status"),
    event_type: str | None = Query(default=None, alias="eventType"),
    target_module: str | None = Query(default=None, alias="targetModule"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=25, ge=1, le=200),
) -> PageResponse[DeliveryResponse]:
    # Un modulo comun queda fijado a lo suyo, ignorando el query param.
    scoped_target = caller.scope or target_module
    result = await delivery_repo.search(
        target_module=scoped_target,
        status=status_filter,
        event_type=event_type,
        page=page,
        size=size,
    )
    return PageResponse.build(result, DeliveryResponse.of)


@router.post(
    "/deliveries/process-due-retries",
    response_model=MessageResponse,
    summary="Completar reintentos vencidos",
    description=(
        "Solo el administrador. Completa las entregas que quedaron pendientes "
        "porque el broker estaba caido al momento de rutear. Nada se perdio: los "
        "eventos ya estaban persistidos."
    ),
)
async def process_due_retries(admin: AdminDep, delivery: DeliveryDep) -> MessageResponse:
    processed = await delivery.process_due_retries()
    return MessageResponse(message=f"Se completaron {processed} entrega(s) pendiente(s).")
