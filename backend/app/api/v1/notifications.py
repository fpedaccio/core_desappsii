"""Endpoints de notificaciones: plantillas, reglas, preferencias e historial."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import (
    NotificationDep,
    NotificationRepoDep,
    PrincipalDep,
    require_permissions,
)
from app.api.v1.schemas.common import MessageResponse, PageResponse
from app.api.v1.schemas.notifications import (
    NotificationDetailResponse,
    NotificationResponse,
    PreferenceResponse,
    PreferenceUpsert,
    RuleCreate,
    RuleResponse,
    RuleUpdate,
    TemplateCreate,
    TemplatePreviewRequest,
    TemplatePreviewResponse,
    TemplateResponse,
    TemplateUpdate,
)
from app.core import permissions as perms
from app.core.errors import NotFoundError
from app.models.notifications import Channel, NotificationStatus

router = APIRouter(prefix="/notifications", tags=["Notificaciones"])

_read = Depends(require_permissions(perms.NOTIFICATIONS_READ))
_write = Depends(require_permissions(perms.NOTIFICATIONS_WRITE))


# ----------------------------------------------------------------------
# Plantillas
# ----------------------------------------------------------------------
@router.get(
    "/templates",
    response_model=PageResponse[TemplateResponse],
    dependencies=[_read],
    summary="Listar plantillas",
)
async def list_templates(
    service: NotificationDep,
    query: str | None = Query(default=None),
    channel: Channel | None = Query(default=None),
    active: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> PageResponse[TemplateResponse]:
    result = await service.search_templates(
        query=query, channel=channel, active=active, page=page, size=size
    )
    return PageResponse.build(result, TemplateResponse.of)


@router.post(
    "/templates",
    response_model=TemplateResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_write],
    summary="Crear plantilla",
    description=(
        "Plantilla Jinja2 con el sobre del evento como contexto "
        "(`{{ data.reclamoId }}`, `{{ occurredAt }}`). La sintaxis se valida al "
        "guardar, para que una plantilla rota no llegue al momento del envio."
    ),
)
async def create_template(payload: TemplateCreate, service: NotificationDep) -> TemplateResponse:
    template = await service.create_template(
        code=payload.code,
        name=payload.name,
        channel=payload.channel,
        subject_template=payload.subject_template,
        body_template=payload.body_template,
        locale=payload.locale,
    )
    return TemplateResponse.of(template)


@router.patch(
    "/templates/{template_id}",
    response_model=TemplateResponse,
    dependencies=[_write],
    summary="Editar plantilla",
)
async def update_template(
    template_id: uuid.UUID, payload: TemplateUpdate, service: NotificationDep
) -> TemplateResponse:
    template = await service.update_template(
        template_id,
        name=payload.name,
        subject_template=payload.subject_template,
        body_template=payload.body_template,
        active=payload.active,
    )
    return TemplateResponse.of(template)


@router.post(
    "/templates/{template_id}/preview",
    response_model=TemplatePreviewResponse,
    dependencies=[_read],
    summary="Previsualizar una plantilla",
    description="Renderiza con un sobre de ejemplo. No envia nada ni deja historial.",
)
async def preview_template(
    template_id: uuid.UUID, payload: TemplatePreviewRequest, service: NotificationDep
) -> TemplatePreviewResponse:
    rendered = await service.preview_template(template_id, sample=payload.sample)
    return TemplatePreviewResponse(**rendered)


# ----------------------------------------------------------------------
# Reglas
# ----------------------------------------------------------------------
@router.get(
    "/rules",
    response_model=list[RuleResponse],
    dependencies=[_read],
    summary="Listar reglas de notificacion",
    description=(
        "Cada regla une un tipo de evento con una plantilla y una forma de resolver "
        "el destinatario. Es lo que permite que el Core notifique por eventos de "
        "otras areas sin implementar sus reglas de negocio."
    ),
)
async def list_rules(service: NotificationDep) -> list[RuleResponse]:
    return [RuleResponse.of(rule) for rule in await service.list_rules()]


@router.post(
    "/rules",
    response_model=RuleResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_write],
    summary="Crear regla de notificacion",
    description=(
        "Despues de crear una regla conviene correr "
        "`POST /registry/core-subscriptions/sync`, para que el Core quede suscripto "
        "al tipo de evento y empiece a recibirlo."
    ),
)
async def create_rule(payload: RuleCreate, service: NotificationDep) -> RuleResponse:
    rule = await service.create_rule(
        event_type=payload.event_type,
        template_code=payload.template_code,
        recipient_source=payload.recipient_source,
        recipient_expression=payload.recipient_expression,
        priority=payload.priority,
    )
    return RuleResponse.of(rule)


@router.patch(
    "/rules/{rule_id}",
    response_model=RuleResponse,
    dependencies=[_write],
    summary="Editar regla",
)
async def update_rule(
    rule_id: uuid.UUID, payload: RuleUpdate, service: NotificationDep
) -> RuleResponse:
    rule = await service.update_rule(
        rule_id,
        active=payload.active,
        recipient_expression=payload.recipient_expression,
        priority=payload.priority,
    )
    return RuleResponse.of(rule)


@router.delete(
    "/rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_write],
    summary="Eliminar regla",
)
async def delete_rule(rule_id: uuid.UUID, service: NotificationDep) -> None:
    await service.delete_rule(rule_id)


# ----------------------------------------------------------------------
# Preferencias
# ----------------------------------------------------------------------
@router.get(
    "/preferences/{subject_ref}",
    response_model=list[PreferenceResponse],
    dependencies=[_read],
    summary="Ver las preferencias de un destinatario",
)
async def list_preferences(
    subject_ref: str, service: NotificationDep
) -> list[PreferenceResponse]:
    return [
        PreferenceResponse.of(preference)
        for preference in await service.list_preferences(subject_ref)
    ]


@router.put(
    "/preferences",
    response_model=PreferenceResponse,
    dependencies=[_write],
    summary="Definir una preferencia de notificacion",
    description=(
        "Opt-out por canal, opcionalmente acotado a un tipo de evento. La preferencia "
        "especifica del tipo pisa la general del canal. Un evento suprimido queda "
        "igual en el historial como SUPPRESSED, con la evidencia de por que no se envio."
    ),
)
async def set_preference(
    payload: PreferenceUpsert, service: NotificationDep
) -> PreferenceResponse:
    preference = await service.set_preference(
        subject_ref=payload.subject_ref,
        channel=payload.channel,
        event_type=payload.event_type,
        enabled=payload.enabled,
    )
    return PreferenceResponse.of(preference)


# ----------------------------------------------------------------------
# Historial
# ----------------------------------------------------------------------
@router.get(
    "",
    response_model=PageResponse[NotificationResponse],
    dependencies=[_read],
    summary="Historial de notificaciones",
)
async def list_notifications(
    service: NotificationDep,
    query: str | None = Query(default=None, description="Busca por destinatario o asunto"),
    channel: Channel | None = Query(default=None),
    status_filter: NotificationStatus | None = Query(default=None, alias="status"),
    event_type: str | None = Query(default=None, alias="eventType"),
    recipient: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> PageResponse[NotificationResponse]:
    result = await service.search_notifications(
        query=query,
        channel=channel,
        status=status_filter,
        event_type=event_type,
        recipient=recipient,
        page=page,
        size=size,
    )
    return PageResponse.build(result, NotificationResponse.of)


@router.get(
    "/inbox",
    response_model=list[NotificationResponse],
    summary="Bandeja in-app del usuario autenticado",
    description="Notificaciones del canal IN_APP dirigidas al email del token.",
)
async def inbox(
    principal: PrincipalDep,
    service: NotificationDep,
    unread_only: bool = Query(default=False, alias="unreadOnly"),
) -> list[NotificationResponse]:
    if not principal.email:
        return []
    items = await service.inbox(principal.email, unread_only=unread_only)
    return [NotificationResponse.of(item) for item in items]


@router.get(
    "/{notification_id}",
    response_model=NotificationDetailResponse,
    dependencies=[_read],
    summary="Ver una notificacion con su cuerpo renderizado",
)
async def get_notification(
    notification_id: uuid.UUID, repo: NotificationRepoDep
) -> NotificationDetailResponse:
    notification = await repo.get(notification_id)
    if notification is None:
        raise NotFoundError(f"No existe la notificacion {notification_id}.")
    return NotificationDetailResponse.of_detail(notification)


@router.post(
    "/{notification_id}/mark-read",
    response_model=MessageResponse,
    summary="Marcar una notificacion in-app como leida",
)
async def mark_read(
    notification_id: uuid.UUID, service: NotificationDep, principal: PrincipalDep
) -> MessageResponse:
    await service.mark_read(notification_id)
    return MessageResponse(message="Notificacion marcada como leida.")


@router.post(
    "/{notification_id}/retry",
    response_model=NotificationDetailResponse,
    dependencies=[Depends(require_permissions(perms.NOTIFICATIONS_SEND))],
    summary="Reintentar un envio fallido",
    description="Reenvia el contenido ya renderizado, sin volver a evaluar la regla.",
)
async def retry_notification(
    notification_id: uuid.UUID, service: NotificationDep
) -> NotificationDetailResponse:
    notification = await service.retry_notification(notification_id)
    return NotificationDetailResponse.of_detail(notification)
