"""Consumidor interno del Core (`q.core.internal`).

El Core, ademas de rutear, es consumidor de eventos de negocio para dos cosas
propias:

1. **Provisionar cuentas de acceso** cuando Ciudadanos registra un ciudadano o
   una organizacion. El Core es dueno de la credencial; el dato personal sigue
   siendo de Ciudadanos.
2. **Notificar**, aplicando las reglas configuradas en la base.

Ambas pasan por la misma barrera de idempotencia: un evento reprocesado no
provisiona la cuenta dos veces ni manda el mail dos veces (regla 1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

from app.core.database import utcnow
from app.messaging.broker import InboundMessage
from app.models.events import IngestionChannel
from app.models.notifications import Notification, NotificationStatus
from app.repositories.event_repository import ProcessedEventRepository
from app.services.envelope import EventEnvelope
from app.services.event_hub_service import EventHubService
from app.services.notification_service import (
    EVENT_NOTIFICATION_FAILED,
    EVENT_NOTIFICATION_SENT,
    NotificationService,
)
from app.services.registry_service import IDENTITY_EVENT_TYPES
from app.services.user_service import UserService

logger = structlog.get_logger(__name__)

CONSUMER_NAME = "core-internal"

CORE_OWN_EVENTS = frozenset({EVENT_NOTIFICATION_SENT, EVENT_NOTIFICATION_FAILED})
"""Eventos que publica el propio Core.

Se excluyen del despacho de notificaciones: si alguien configurara una regla
sobre `NotificacionEnviada`, notificar generaria otro `NotificacionEnviada` y el
ciclo no terminaria nunca. El corte esta aca, en un solo lugar.
"""

# Rutas candidatas dentro de `data` para los campos de identidad. Son varias
# porque los equipos nombran distinto y el Core no puede imponer una forma:
# se prueba en orden y gana la primera que trae algo.
#
# Esto NO es logica de negocio de Ciudadanos: son los unicos campos que el Core
# necesita para crear una credencial, que es su propia responsabilidad.
IDENTITY_FIELD_CANDIDATES: dict[str, tuple[str, ...]] = {
    "external_id": ("ciudadanoId", "id", "organizacionId", "personaId", "externalId"),
    "email": ("email", "correo", "contacto.email", "datosContacto.email", "mail"),
    "full_name": ("nombreCompleto", "razonSocial", "nombreFantasia", "fullName", "nombre"),
    "document_number": ("dni", "documento", "cuit", "numeroDocumento", "documentNumber"),
}


@dataclass
class ConsumeResult:
    event_type: str | None = None
    skipped_duplicate: bool = False
    account_provisioned: bool = False
    account_updated: bool = False
    notifications_sent: int = 0
    notifications_failed: int = 0
    published_events: list[str] = field(default_factory=list)


class InternalConsumerService:
    def __init__(
        self,
        *,
        hub: EventHubService,
        user_service: UserService,
        notification_service: NotificationService,
        processed_repo: ProcessedEventRepository,
    ) -> None:
        self.hub = hub
        self.user_service = user_service
        self.notification_service = notification_service
        self.processed_repo = processed_repo

    async def handle_message(self, message: InboundMessage) -> ConsumeResult:
        """Procesa un mensaje de `q.core.internal`."""
        try:
            envelope = EventEnvelope.model_validate(message.json())
        except Exception as exc:
            # No se puede reintentar lo que no se entiende: se guarda crudo.
            await self.hub.record_malformed(raw_body=message.text, queue=message.queue)
            logger.warning("internal_consumer_malformed", error=str(exc))
            return ConsumeResult()

        return await self.handle_event(envelope)

    async def handle_event(self, envelope: EventEnvelope) -> ConsumeResult:
        result = ConsumeResult(event_type=envelope.event_type)

        if await self.processed_repo.was_processed(CONSUMER_NAME, envelope.event_id):
            logger.info(
                "internal_consumer_duplicate_skipped",
                event_id=str(envelope.event_id),
                event_type=envelope.event_type,
            )
            result.skipped_duplicate = True
            return result

        if envelope.event_type in IDENTITY_EVENT_TYPES:
            await self._provision_identity(envelope, result)

        if envelope.event_type not in CORE_OWN_EVENTS:
            await self._notify(envelope, result)

        await self.processed_repo.mark(
            consumer=CONSUMER_NAME,
            event_id=envelope.event_id,
            event_type=envelope.event_type,
            processed_at=utcnow(),
            result=(
                f"provisioned={result.account_provisioned} "
                f"sent={result.notifications_sent} failed={result.notifications_failed}"
            ),
        )
        return result

    # ------------------------------------------------------------------
    async def _provision_identity(
        self, envelope: EventEnvelope, result: ConsumeResult
    ) -> None:
        fields = _extract_identity_fields(envelope.data)
        external_id = fields.get("external_id")

        if not external_id:
            logger.warning(
                "identity_event_without_id",
                event_type=envelope.event_type,
                event_id=str(envelope.event_id),
                hint=(
                    "El evento no trae un identificador reconocible. Candidatos "
                    f"buscados: {IDENTITY_FIELD_CANDIDATES['external_id']}"
                ),
            )
            return

        _, created = await self.user_service.provision_from_citizen_event(
            external_id=str(external_id),
            email=fields.get("email"),
            full_name=str(fields.get("full_name") or ""),
            document_number=(
                str(fields["document_number"]) if fields.get("document_number") else None
            ),
            source_module=envelope.source_module,
        )
        result.account_provisioned = created
        result.account_updated = not created

    async def _notify(self, envelope: EventEnvelope, result: ConsumeResult) -> None:
        dispatch = await self.notification_service.dispatch_for_event(envelope)
        result.notifications_sent = len(dispatch.sent)
        result.notifications_failed = len(dispatch.failed)

        # Cada envio genera su propio evento: los modulos 2, 4, 5, 6 y 8 declaran
        # consumir NotificacionEnviada / NotificacionFallida.
        for notification in dispatch.sent:
            published = await self._publish_notification_event(
                notification, envelope, EVENT_NOTIFICATION_SENT
            )
            if published:
                result.published_events.append(EVENT_NOTIFICATION_SENT)

        for notification in dispatch.failed:
            published = await self._publish_notification_event(
                notification, envelope, EVENT_NOTIFICATION_FAILED
            )
            if published:
                result.published_events.append(EVENT_NOTIFICATION_FAILED)

    async def _publish_notification_event(
        self, notification: Notification, source: EventEnvelope, event_type: str
    ) -> bool:
        """Publica el resultado del envio *a traves del propio hub*.

        El Core no tiene un atajo para publicar: sus eventos se validan contra el
        catalogo, quedan en `event_log` y se rutean como los de cualquier otro
        modulo. Si el tipo no esta registrado, el evento va a la DLQ y se ve en el
        panel, igual que le pasaria a otro equipo.
        """
        import uuid

        envelope = EventEnvelope(
            eventId=uuid.uuid4(),
            eventType=event_type,
            eventVersion="1.0",
            occurredAt=notification.sent_at or utcnow(),
            sourceModule="core",
            # Se conserva la correlacion del evento que origino el aviso, para que
            # la journey se lea completa en el explorador.
            correlationId=source.correlation_id,
            causationId=source.event_id,
            data={
                "notificationId": str(notification.id),
                "channel": _value(notification.channel),
                "recipient": notification.recipient,
                "templateCode": notification.template_code,
                "originEventId": str(source.event_id),
                "originEventType": source.event_type,
                "status": _value(notification.status),
                "error": notification.error,
            },
        )

        outcome = await self.hub.ingest(envelope, channel=IngestionChannel.HTTP)
        if not outcome.accepted:
            logger.warning(
                "notification_event_not_published",
                event_type=event_type,
                reason=outcome.rejection_code,
                hint="Registra el tipo de evento en el catalogo para poder publicarlo.",
            )
        return outcome.accepted


def _extract_identity_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Toma del payload solo los campos que el Core necesita para la credencial."""
    extracted: dict[str, Any] = {}
    for field_name, candidates in IDENTITY_FIELD_CANDIDATES.items():
        for path in candidates:
            value = _dig(data, path)
            if value not in (None, ""):
                extracted[field_name] = value
                break
    return extracted


def _dig(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _value(value: object) -> str:
    return str(getattr(value, "value", value))


__all__ = [
    "CONSUMER_NAME",
    "CORE_OWN_EVENTS",
    "ConsumeResult",
    "InternalConsumerService",
    "NotificationStatus",
]
