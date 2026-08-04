"""Registry de integracion: modulos, productores, suscripciones y topologia.

El registry es la fuente de verdad del ruteo. Cuando cambia una suscripcion, la
topologia del broker se recalcula desde estas tablas: no hay colas ni bindings
escritos a mano en ningun lado.
"""

from __future__ import annotations

import uuid

import structlog

from app.core.errors import ConflictError, ExternalUnavailableError, NotFoundError
from app.messaging.broker import Broker
from app.messaging.topology import CORE_INTERNAL_QUEUE, Topology, full_topology
from app.models.contracts import Producer, RegisteredModule, Subscription
from app.repositories.contract_repository import (
    EventTypeRepository,
    ModuleRepository,
    ProducerRepository,
    SubscriptionRepository,
)
from app.repositories.notification_repository import NotificationRuleRepository
from app.services.audit_service import AuditService

logger = structlog.get_logger(__name__)

CORE_MODULE_NAME = "core"


class RegistryService:
    def __init__(
        self,
        *,
        module_repo: ModuleRepository,
        producer_repo: ProducerRepository,
        subscription_repo: SubscriptionRepository,
        event_type_repo: EventTypeRepository,
        rule_repo: NotificationRuleRepository,
        broker: Broker,
        audit: AuditService,
    ) -> None:
        self.module_repo = module_repo
        self.producer_repo = producer_repo
        self.subscription_repo = subscription_repo
        self.event_type_repo = event_type_repo
        self.rule_repo = rule_repo
        self.broker = broker
        self.audit = audit

    # ------------------------------------------------------------------
    # Modulos
    # ------------------------------------------------------------------
    async def list_modules(self) -> list[RegisteredModule]:
        return await self.module_repo.list_ordered()

    async def get_module(self, module_id: uuid.UUID) -> RegisteredModule:
        module = await self.module_repo.get(module_id)
        if module is None:
            raise NotFoundError(f"No existe el modulo {module_id}.")
        return module

    async def get_module_by_name(self, name: str) -> RegisteredModule:
        module = await self.module_repo.get_by_name(_normalize_name(name))
        if module is None:
            raise NotFoundError(f"No existe el modulo '{name}'.")
        return module

    async def register_module(
        self,
        *,
        name: str,
        display_name: str,
        description: str = "",
        team: str = "",
        base_url: str | None = None,
        health_url: str | None = None,
        contact_email: str | None = None,
        queue_name: str | None = None,
    ) -> RegisteredModule:
        normalized = _normalize_name(name)
        if await self.module_repo.get_by_name(normalized) is not None:
            raise ConflictError(f"Ya existe el modulo '{normalized}'.")

        module = RegisteredModule(
            name=normalized,
            display_name=display_name.strip(),
            description=description,
            team=team,
            base_url=base_url,
            health_url=health_url,
            contact_email=contact_email,
            queue_name=queue_name or f"q.{normalized}",
        )
        self.module_repo.add(module)
        await self.module_repo.flush()

        self.audit.record(
            action="MODULE_REGISTERED",
            entity_type="RegisteredModule",
            entity_id=str(module.id),
            summary=f"Modulo '{normalized}' registrado con cola {module.effective_queue_name}.",
        )
        logger.info("module_registered", module=normalized, queue=module.effective_queue_name)
        return module

    async def update_module(
        self,
        module_id: uuid.UUID,
        *,
        display_name: str | None = None,
        description: str | None = None,
        team: str | None = None,
        base_url: str | None = None,
        health_url: str | None = None,
        contact_email: str | None = None,
        active: bool | None = None,
    ) -> RegisteredModule:
        module = await self.get_module(module_id)
        if display_name is not None:
            module.display_name = display_name.strip()
        if description is not None:
            module.description = description
        if team is not None:
            module.team = team
        if base_url is not None:
            module.base_url = base_url
        if health_url is not None:
            module.health_url = health_url
        if contact_email is not None:
            module.contact_email = contact_email
        if active is not None:
            # Desactivar un modulo deja de entregarle eventos sin tocar la
            # topologia: sus suscripciones siguen declaradas para cuando vuelva.
            module.active = active

        self.audit.record(
            action="MODULE_UPDATED",
            entity_type="RegisteredModule",
            entity_id=str(module.id),
            summary=f"Modulo '{module.name}' actualizado.",
        )
        return module

    # ------------------------------------------------------------------
    # Productores
    # ------------------------------------------------------------------
    async def list_producers(self) -> list[Producer]:
        return await self.producer_repo.list_all()

    async def declare_producer(self, *, module_name: str, event_type_name: str) -> Producer:
        module = await self.get_module_by_name(module_name)
        event_type = await self._get_event_type(event_type_name)

        existing = await self.producer_repo.find_pair(module.id, event_type.id)
        if existing is not None:
            existing.active = True
            return existing

        producer = Producer(module_id=module.id, event_type_id=event_type.id)
        self.producer_repo.add(producer)
        await self.producer_repo.flush()

        self.audit.record(
            action="PRODUCER_DECLARED",
            entity_type="Producer",
            entity_id=str(producer.id),
            summary=f"'{module.name}' declarado productor de '{event_type.name}'.",
        )
        return producer

    async def remove_producer(self, producer_id: uuid.UUID) -> None:
        producer = await self.producer_repo.get_required(producer_id)
        await self.producer_repo.delete(producer)
        self.audit.record(
            action="PRODUCER_REMOVED",
            entity_type="Producer",
            entity_id=str(producer_id),
            summary="Declaracion de productor eliminada.",
        )

    # ------------------------------------------------------------------
    # Suscripciones
    # ------------------------------------------------------------------
    async def list_subscriptions(self) -> list[Subscription]:
        return await self.subscription_repo.list_all()

    async def subscribe(
        self,
        *,
        module_name: str,
        event_type_name: str,
        queue_name: str | None = None,
        max_attempts: int = 4,
    ) -> Subscription:
        """Suscribe un modulo a un tipo de evento y aplica la topologia."""
        module = await self.get_module_by_name(module_name)
        event_type = await self._get_event_type(event_type_name)

        existing = await self.subscription_repo.find_pair(module.id, event_type.id)
        if existing is not None:
            existing.active = True
            if queue_name:
                existing.queue_name = queue_name
            existing.max_attempts = max_attempts
            await self.apply_topology(raise_on_error=False)
            return existing

        subscription = Subscription(
            module_id=module.id,
            event_type_id=event_type.id,
            queue_name=queue_name,
            max_attempts=max_attempts,
        )
        self.subscription_repo.add(subscription)
        await self.subscription_repo.flush()

        self.audit.record(
            action="SUBSCRIPTION_CREATED",
            entity_type="Subscription",
            entity_id=str(subscription.id),
            summary=(
                f"'{module.name}' suscripto a '{event_type.name}' "
                f"(cola {queue_name or module.effective_queue_name})."
            ),
        )
        # La topologia se aplica en el acto para que la cola exista antes de que
        # llegue el primer evento del tipo suscripto.
        await self.apply_topology(raise_on_error=False)
        return subscription

    async def update_subscription(
        self,
        subscription_id: uuid.UUID,
        *,
        active: bool | None = None,
        max_attempts: int | None = None,
        queue_name: str | None = None,
    ) -> Subscription:
        subscription = await self.subscription_repo.get_required(subscription_id)
        if active is not None:
            subscription.active = active
        if max_attempts is not None:
            subscription.max_attempts = max_attempts
        if queue_name is not None:
            subscription.queue_name = queue_name

        self.audit.record(
            action="SUBSCRIPTION_UPDATED",
            entity_type="Subscription",
            entity_id=str(subscription.id),
            summary=f"Suscripcion {subscription_id} actualizada.",
        )
        await self.apply_topology(raise_on_error=False)
        return subscription

    async def unsubscribe(self, subscription_id: uuid.UUID) -> None:
        subscription = await self.subscription_repo.get_required(subscription_id)
        await self.subscription_repo.delete(subscription)
        self.audit.record(
            action="SUBSCRIPTION_REMOVED",
            entity_type="Subscription",
            entity_id=str(subscription_id),
            summary="Suscripcion eliminada.",
        )

    async def _get_event_type(self, event_type_name: str):
        event_type = await self.event_type_repo.get_by_name(event_type_name.strip())
        if event_type is None:
            raise NotFoundError(
                f"El tipo de evento '{event_type_name}' no esta en el catalogo. "
                "Registralo antes de declarar productores o suscripciones."
            )
        return event_type

    # ------------------------------------------------------------------
    # Topologia
    # ------------------------------------------------------------------
    async def planned_topology(self) -> Topology:
        """La topologia que corresponde al estado actual del registry."""
        queues = await self.subscription_repo.active_queue_names()
        return full_topology(queues)

    async def apply_topology(self, *, raise_on_error: bool = True) -> Topology:
        """Declara la topologia en el broker. Es idempotente.

        Si el broker no responde, la operacion de negocio (por ejemplo crear una
        suscripcion) **no se revierte**: queda declarada en el registry y se
        aplica en el proximo arranque o al reintentar desde el panel. Es la
        tolerancia a indisponibilidad aplicada al propio Core.
        """
        topology = await self.planned_topology()
        try:
            await self.broker.declare(topology)
        except Exception as exc:
            logger.warning("topology_apply_failed", error=str(exc))
            if raise_on_error:
                raise ExternalUnavailableError(
                    f"No se pudo aplicar la topologia en el broker: {exc}"
                ) from exc
            return topology

        logger.info(
            "topology_applied",
            queues=len(topology.queues),
            bindings=len(topology.bindings),
        )
        return topology

    async def ensure_core_module(self) -> RegisteredModule:
        """Da de alta el Core como un modulo mas del registry.

        El Core consume eventos de negocio (para provisionar identidades y para
        notificar). En vez de tener un atajo interno, se registra como modulo y
        usa el mismo camino de suscripciones que los otros 8: el ruteo tiene una
        sola implementacion y el panel muestra sus suscripciones como cualquiera.
        """
        module = await self.module_repo.get_by_name(CORE_MODULE_NAME)
        if module is not None:
            return module

        return await self.register_module(
            name=CORE_MODULE_NAME,
            display_name="Core - Identidad, Integracion, Notificaciones y Monitoreo",
            description=(
                "Modulo 9. Hub de eventos, proveedor de identidad, catalogos "
                "globales, DLQ, notificaciones y monitoreo."
            ),
            team="Equipo 9",
            queue_name=CORE_INTERNAL_QUEUE,
        )

    async def sync_core_subscriptions(self) -> list[str]:
        """Suscribe al Core a los tipos de evento que necesita consumir.

        Son dos grupos, y ninguno implica conocer reglas de negocio ajenas:

        * los eventos de identidad (`CiudadanoRegistrado`, ...), para provisionar
          las cuentas de acceso;
        * los tipos que tengan una regla de notificacion configurada.

        El segundo grupo se lee de `notification_rules`: si un operador agrega una
        regla para `ReclamoResuelto`, el Core se suscribe solo.
        """
        core = await self.ensure_core_module()
        wanted = set(IDENTITY_EVENT_TYPES) | set(await self.rule_repo.distinct_event_types())

        subscribed: list[str] = []
        for event_type_name in sorted(wanted):
            event_type = await self.event_type_repo.get_by_name(event_type_name)
            if event_type is None:
                # El tipo todavia no esta en el catalogo: se intentara de nuevo en
                # el proximo arranque o cuando el equipo dueno lo registre.
                continue
            existing = await self.subscription_repo.find_pair(core.id, event_type.id)
            if existing is None:
                self.subscription_repo.add(
                    Subscription(
                        module_id=core.id,
                        event_type_id=event_type.id,
                        queue_name=CORE_INTERNAL_QUEUE,
                    )
                )
                subscribed.append(event_type_name)
            elif not existing.active:
                existing.active = True
                subscribed.append(event_type_name)

        if subscribed:
            await self.subscription_repo.flush()
            logger.info("core_subscriptions_synced", added=subscribed)
        return subscribed


IDENTITY_EVENT_TYPES = (
    "CiudadanoRegistrado",
    "CiudadanoActualizado",
    "OrganizacionRegistrada",
)
"""Eventos del modulo Ciudadanos con los que el Core mantiene las cuentas de acceso."""


def build_registry_service(session, broker: Broker) -> RegistryService:
    """Arma el servicio a partir de una sesion.

    Lo usan el arranque de la aplicacion y los workers, que no pasan por el grafo
    de dependencias de FastAPI pero necesitan el mismo servicio.
    """
    from app.repositories.contract_repository import (
        EventTypeRepository,
        ModuleRepository,
        ProducerRepository,
        SubscriptionRepository,
    )
    from app.repositories.monitoring_repository import AuditLogRepository
    from app.repositories.notification_repository import NotificationRuleRepository

    return RegistryService(
        module_repo=ModuleRepository(session),
        producer_repo=ProducerRepository(session),
        subscription_repo=SubscriptionRepository(session),
        event_type_repo=EventTypeRepository(session),
        rule_repo=NotificationRuleRepository(session),
        broker=broker,
        audit=AuditService(AuditLogRepository(session)),
    )


def _normalize_name(name: str) -> str:
    return name.strip().lower()
