"""Notificaciones dirigidas por configuracion.

El Core notifica por eventos de otras areas (`ReclamoResuelto`,
`HabilitacionAprobada`, `DeudaVencida`, ...) **sin conocer ni una regla de
negocio de esas areas**. Todo lo que decide que se manda y a quien vive en
`notification_rules` y `notification_templates`, en la base:

    evento  ->  regla  ->  plantilla  +  como resolver el destinatario

Si manana Rentas quiere avisar por `PlanPagoIncumplido`, se agrega una regla
desde el panel. No se toca este archivo.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog
from jinja2 import TemplateError
from jinja2.sandbox import SandboxedEnvironment

from app.core.database import utcnow
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models.notifications import (
    Channel,
    Notification,
    NotificationPreference,
    NotificationRule,
    NotificationStatus,
    NotificationTemplate,
    RecipientSource,
)
from app.notifications.channels import ChannelRegistry
from app.repositories.base import Page
from app.repositories.identity_repository import UserRepository
from app.repositories.notification_repository import (
    NotificationPreferenceRepository,
    NotificationRepository,
    NotificationRuleRepository,
    NotificationTemplateRepository,
)
from app.services.audit_service import AuditService
from app.services.envelope import EventEnvelope

logger = structlog.get_logger(__name__)

EVENT_NOTIFICATION_SENT = "NotificacionEnviada"
EVENT_NOTIFICATION_FAILED = "NotificacionFallida"

# Sandbox: las plantillas las editan operadores desde el panel, o sea que son
# entrada no confiable. El entorno restringido evita que una plantilla acceda a
# atributos internos de los objetos del contexto.
_jinja = SandboxedEnvironment(autoescape=False, trim_blocks=True, lstrip_blocks=True)

MAX_RECIPIENTS_PER_RULE = 50
"""Tope de destinatarios por regla, para que un aviso a un rol muy poblado no
genere miles de envios de una sola vez."""


@dataclass
class DispatchResult:
    """Que notificaciones genero un evento."""

    sent: list[Notification] = field(default_factory=list)
    failed: list[Notification] = field(default_factory=list)
    suppressed: list[Notification] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.sent) + len(self.failed) + len(self.suppressed)


class NotificationService:
    def __init__(
        self,
        *,
        template_repo: NotificationTemplateRepository,
        rule_repo: NotificationRuleRepository,
        preference_repo: NotificationPreferenceRepository,
        notification_repo: NotificationRepository,
        user_repo: UserRepository,
        channels: ChannelRegistry,
        audit: AuditService,
    ) -> None:
        self.template_repo = template_repo
        self.rule_repo = rule_repo
        self.preference_repo = preference_repo
        self.notification_repo = notification_repo
        self.user_repo = user_repo
        self.channels = channels
        self.audit = audit

    # ------------------------------------------------------------------
    # Despacho a partir de un evento
    # ------------------------------------------------------------------
    async def dispatch_for_event(self, envelope: EventEnvelope) -> DispatchResult:
        """Aplica todas las reglas activas del tipo de evento."""
        result = DispatchResult()
        rules = await self.rule_repo.active_for_event_type(envelope.event_type)
        if not rules:
            return result

        context = self._context_for(envelope)

        for rule in rules:
            template = rule.template
            if template is None or not template.active:
                continue

            recipients = await self._resolve_recipients(rule, envelope)
            if not recipients:
                logger.info(
                    "notification_without_recipient",
                    event_type=envelope.event_type,
                    rule_id=str(rule.id),
                    source=str(rule.recipient_source),
                    expression=rule.recipient_expression,
                )
                continue

            for recipient in recipients[:MAX_RECIPIENTS_PER_RULE]:
                notification = await self._deliver(
                    rule=rule, template=template, recipient=recipient, envelope=envelope,
                    context=context,
                )
                if notification.status == NotificationStatus.SENT:
                    result.sent.append(notification)
                elif notification.status == NotificationStatus.SUPPRESSED:
                    result.suppressed.append(notification)
                else:
                    result.failed.append(notification)

        logger.info(
            "notifications_dispatched",
            event_type=envelope.event_type,
            sent=len(result.sent),
            failed=len(result.failed),
            suppressed=len(result.suppressed),
        )
        return result

    async def _deliver(
        self,
        *,
        rule: NotificationRule,
        template: NotificationTemplate,
        recipient: str,
        envelope: EventEnvelope,
        context: dict[str, Any],
    ) -> Notification:
        notification = Notification(
            event_id=envelope.event_id,
            event_type=envelope.event_type,
            rule_id=rule.id,
            template_code=template.code,
            channel=template.channel,
            recipient=recipient,
            # Explicitos: el despacho los lee y modifica antes del flush, y los
            # defaults de columna de SQLAlchemy recien se aplican al INSERT.
            attempts=0,
            status=NotificationStatus.PENDING,
            subject="",
            body="",
        )
        self.notification_repo.add(notification)

        # Opt-out del destinatario: se registra igual como SUPPRESSED, para que
        # quede la evidencia de que el evento se evaluo y por que no se mando.
        enabled = await self.preference_repo.is_enabled(
            subject_ref=recipient, channel=template.channel, event_type=envelope.event_type
        )
        if not enabled:
            notification.status = NotificationStatus.SUPPRESSED
            notification.error = "El destinatario tiene el canal desactivado para este evento."
            return notification

        try:
            notification.subject = _render(template.subject_template, context)[:255]
            notification.body = _render(template.body_template, context)
        except TemplateError as exc:
            notification.status = NotificationStatus.FAILED
            notification.error = f"Error al renderizar la plantilla: {exc}"
            logger.warning(
                "template_render_failed", template=template.code, error=str(exc)
            )
            return notification

        notification.attempts += 1
        adapter = self.channels.get(template.channel)
        outcome = await adapter.send(
            recipient=recipient, subject=notification.subject, body=notification.body
        )

        notification.provider_response = outcome.provider_response
        if outcome.delivered:
            notification.status = NotificationStatus.SENT
            notification.sent_at = utcnow()
        else:
            notification.status = NotificationStatus.FAILED
            notification.error = outcome.error
        return notification

    def _context_for(self, envelope: EventEnvelope) -> dict[str, Any]:
        """Contexto de la plantilla: el sobre completo, en camelCase.

        Se expone `data` al tope tambien, porque es lo que casi siempre se usa
        (`{{ data.reclamoId }}`).
        """
        wire = envelope.to_wire()
        return {**wire, "event": wire, "data": wire.get("data", {})}

    # ------------------------------------------------------------------
    # Resolucion de destinatarios
    # ------------------------------------------------------------------
    async def _resolve_recipients(
        self, rule: NotificationRule, envelope: EventEnvelope
    ) -> list[str]:
        expression = (rule.recipient_expression or "").strip()

        if rule.recipient_source == RecipientSource.FIXED:
            return [expression] if expression else []

        if rule.recipient_source == RecipientSource.ROLE:
            return await self.user_repo.emails_for_role(expression)

        value = _dig(envelope.data, expression)

        if rule.recipient_source == RecipientSource.PAYLOAD_FIELD:
            return _as_recipients(value)

        if rule.recipient_source == RecipientSource.EXTERNAL_USER:
            # El evento trae el id del ciudadano; el email lo tiene el Core en la
            # cuenta que provisiono al recibir `CiudadanoRegistrado`.
            resolved: list[str] = []
            for external_id in _as_recipients(value):
                user = await self.user_repo.get_by_external("ciudadanos", external_id)
                if user is not None and "@sin-email.local" not in user.email:
                    resolved.append(user.email)
                else:
                    logger.info(
                        "recipient_not_resolvable",
                        external_id=external_id,
                        reason="sin cuenta o sin email",
                    )
            return resolved

        return []

    # ------------------------------------------------------------------
    # Plantillas
    # ------------------------------------------------------------------
    async def search_templates(self, **kwargs: Any) -> Page[NotificationTemplate]:
        return await self.template_repo.search(**kwargs)

    async def create_template(
        self,
        *,
        code: str,
        name: str,
        channel: Channel,
        body_template: str,
        subject_template: str = "",
        locale: str = "es-AR",
    ) -> NotificationTemplate:
        normalized = code.strip().upper()
        if await self.template_repo.get_by_code(normalized) is not None:
            raise ConflictError(f"Ya existe la plantilla {normalized}.")

        _assert_template_compiles(subject_template, "asunto")
        _assert_template_compiles(body_template, "cuerpo")

        template = NotificationTemplate(
            code=normalized,
            name=name.strip(),
            channel=channel,
            subject_template=subject_template,
            body_template=body_template,
            locale=locale,
        )
        self.template_repo.add(template)
        await self.template_repo.flush()

        self.audit.record(
            action="TEMPLATE_CREATED",
            entity_type="NotificationTemplate",
            entity_id=str(template.id),
            summary=f"Plantilla {normalized} creada para el canal {channel}.",
        )
        return template

    async def update_template(
        self,
        template_id: uuid.UUID,
        *,
        name: str | None = None,
        subject_template: str | None = None,
        body_template: str | None = None,
        active: bool | None = None,
    ) -> NotificationTemplate:
        template = await self.template_repo.get_required(template_id)
        if name is not None:
            template.name = name.strip()
        if subject_template is not None:
            _assert_template_compiles(subject_template, "asunto")
            template.subject_template = subject_template
        if body_template is not None:
            _assert_template_compiles(body_template, "cuerpo")
            template.body_template = body_template
        if active is not None:
            template.active = active

        self.audit.record(
            action="TEMPLATE_UPDATED",
            entity_type="NotificationTemplate",
            entity_id=str(template.id),
            summary=f"Plantilla {template.code} actualizada.",
        )
        return template

    async def preview_template(
        self, template_id: uuid.UUID, *, sample: dict[str, Any]
    ) -> dict[str, str]:
        """Renderiza la plantilla con un sobre de ejemplo, sin enviar nada."""
        template = await self.template_repo.get_required(template_id)
        context = {**sample, "data": sample.get("data", {}), "event": sample}
        try:
            return {
                "subject": _render(template.subject_template, context),
                "body": _render(template.body_template, context),
            }
        except TemplateError as exc:
            raise ValidationError(f"La plantilla no se pudo renderizar: {exc}") from exc

    # ------------------------------------------------------------------
    # Reglas
    # ------------------------------------------------------------------
    async def list_rules(self) -> list[NotificationRule]:
        return await self.rule_repo.list_all()

    async def create_rule(
        self,
        *,
        event_type: str,
        template_code: str,
        recipient_source: RecipientSource,
        recipient_expression: str,
        priority: int = 100,
    ) -> NotificationRule:
        template = await self.template_repo.get_by_code(template_code.strip().upper())
        if template is None:
            raise NotFoundError(f"No existe la plantilla {template_code}.")

        normalized_event = event_type.strip()
        if await self.rule_repo.find_pair(normalized_event, template.id) is not None:
            raise ConflictError(
                f"Ya hay una regla que notifica '{normalized_event}' con la plantilla "
                f"{template.code}."
            )

        if recipient_source != RecipientSource.FIXED and not recipient_expression.strip():
            raise ValidationError(
                f"El origen de destinatario {recipient_source} necesita una expresion "
                "(ruta del payload, codigo de rol o direccion)."
            )

        rule = NotificationRule(
            event_type=normalized_event,
            template_id=template.id,
            recipient_source=recipient_source,
            recipient_expression=recipient_expression.strip(),
            priority=priority,
        )
        self.rule_repo.add(rule)
        await self.rule_repo.flush()

        self.audit.record(
            action="NOTIFICATION_RULE_CREATED",
            entity_type="NotificationRule",
            entity_id=str(rule.id),
            summary=(
                f"Regla creada: '{normalized_event}' notifica con {template.code} "
                f"a {recipient_source}:{recipient_expression}."
            ),
        )
        return rule

    async def update_rule(
        self,
        rule_id: uuid.UUID,
        *,
        active: bool | None = None,
        recipient_expression: str | None = None,
        priority: int | None = None,
    ) -> NotificationRule:
        rule = await self.rule_repo.get_required(rule_id)
        if active is not None:
            rule.active = active
        if recipient_expression is not None:
            rule.recipient_expression = recipient_expression.strip()
        if priority is not None:
            rule.priority = priority

        self.audit.record(
            action="NOTIFICATION_RULE_UPDATED",
            entity_type="NotificationRule",
            entity_id=str(rule.id),
            summary=f"Regla {rule_id} actualizada.",
        )
        return rule

    async def delete_rule(self, rule_id: uuid.UUID) -> None:
        rule = await self.rule_repo.get_required(rule_id)
        await self.rule_repo.delete(rule)
        self.audit.record(
            action="NOTIFICATION_RULE_DELETED",
            entity_type="NotificationRule",
            entity_id=str(rule_id),
            summary=f"Regla de notificacion {rule_id} eliminada.",
        )

    # ------------------------------------------------------------------
    # Preferencias e historial
    # ------------------------------------------------------------------
    async def set_preference(
        self,
        *,
        subject_ref: str,
        channel: Channel,
        event_type: str | None,
        enabled: bool,
    ) -> NotificationPreference:
        existing = await self.preference_repo.find_exact(
            subject_ref=subject_ref.strip(), channel=channel, event_type=event_type
        )
        if existing is not None:
            existing.enabled = enabled
            return existing

        preference = NotificationPreference(
            subject_ref=subject_ref.strip(),
            channel=channel,
            event_type=event_type,
            enabled=enabled,
        )
        self.preference_repo.add(preference)
        await self.preference_repo.flush()
        return preference

    async def list_preferences(self, subject_ref: str) -> list[NotificationPreference]:
        return await self.preference_repo.list_for_subject(subject_ref.strip())

    async def search_notifications(self, **kwargs: Any) -> Page[Notification]:
        return await self.notification_repo.search(**kwargs)

    async def inbox(self, recipient: str, *, unread_only: bool = False) -> list[Notification]:
        return await self.notification_repo.list_inbox(recipient, unread_only=unread_only)

    async def mark_read(self, notification_id: uuid.UUID) -> Notification:
        notification = await self.notification_repo.get_required(notification_id)
        if notification.read_at is None:
            notification.read_at = utcnow()
        return notification

    async def retry_notification(self, notification_id: uuid.UUID) -> Notification:
        """Reintenta un envio fallido con el mismo contenido ya renderizado."""
        notification = await self.notification_repo.get_required(notification_id)
        if notification.status != NotificationStatus.FAILED:
            raise ConflictError(
                f"Solo se reintentan las notificaciones fallidas (esta esta en "
                f"{notification.status})."
            )

        notification.attempts += 1
        adapter = self.channels.get(notification.channel)
        outcome = await adapter.send(
            recipient=notification.recipient,
            subject=notification.subject,
            body=notification.body,
        )
        notification.provider_response = outcome.provider_response
        if outcome.delivered:
            notification.status = NotificationStatus.SENT
            notification.sent_at = utcnow()
            notification.error = None
        else:
            notification.error = outcome.error

        self.audit.record(
            action="NOTIFICATION_RETRIED",
            entity_type="Notification",
            entity_id=str(notification.id),
            summary=(
                f"Reintento de notificacion a {notification.recipient}: "
                f"{'exito' if outcome.delivered else 'fallo'}."
            ),
        )
        return notification


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _render(template_source: str, context: dict[str, Any]) -> str:
    if not template_source:
        return ""
    return _jinja.from_string(template_source).render(**context)


def _assert_template_compiles(template_source: str, label: str) -> None:
    """Falla al guardar, no al enviar: una plantilla rota no llega a produccion."""
    if not template_source:
        return
    try:
        _jinja.from_string(template_source)
    except TemplateError as exc:
        raise ValidationError(f"La plantilla de {label} tiene un error de sintaxis: {exc}") from exc


def _dig(payload: dict[str, Any], path: str) -> Any:
    """Navega una ruta con puntos dentro del payload: `ciudadano.contacto.email`."""
    if not path:
        return None
    current: Any = payload
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _as_recipients(value: Any) -> list[str]:
    """Acepta un destinatario o una lista, y descarta lo que no sea texto util."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value)]
