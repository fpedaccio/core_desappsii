"""Registry: modulos, tipos de evento y suscripciones.

Es la fuente de verdad del ruteo. Cuando cambia una suscripcion, la topologia del
broker se recalcula desde estas tablas: no hay colas ni bindings escritos a mano.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog

from app.core.errors import (
    ConflictError,
    ExternalUnavailableError,
    ForbiddenError,
    NotFoundError,
)
from app.messaging.broker import Broker
from app.messaging.topology import Topology, full_topology
from app.models.registry import EventType, ModuleAccount, Publication, Subscription
from app.repositories.base import Page
from app.repositories.registry_repository import (
    EventTypeRepository,
    ModuleRepository,
    PublicationRepository,
    SubscriptionRepository,
)
from app.services.validation import assert_valid_schema

logger = structlog.get_logger(__name__)


class RegistryService:
    def __init__(
        self,
        *,
        module_repo: ModuleRepository,
        event_type_repo: EventTypeRepository,
        subscription_repo: SubscriptionRepository,
        publication_repo: PublicationRepository,
        broker: Broker,
    ) -> None:
        self.module_repo = module_repo
        self.event_type_repo = event_type_repo
        self.subscription_repo = subscription_repo
        self.publication_repo = publication_repo
        self.broker = broker

    # ------------------------------------------------------------------
    # Modulos
    # ------------------------------------------------------------------
    async def list_modules(self) -> list[ModuleAccount]:
        return await self.module_repo.list_ordered()

    async def get_module_by_name(self, name: str) -> ModuleAccount:
        module = await self.module_repo.get_by_name(name)
        if module is None:
            raise NotFoundError(f"No existe el modulo '{name}'.")
        return module

    async def register_module(
        self,
        *,
        name: str,
        display_name: str,
        team: str = "",
        description: str = "",
        contact_email: str | None = None,
        is_admin: bool = False,
    ) -> ModuleAccount:
        normalized = name.strip().lower()
        if await self.module_repo.get_by_name(normalized) is not None:
            raise ConflictError(f"Ya existe el modulo '{normalized}'.")

        module = ModuleAccount(
            name=normalized,
            display_name=display_name.strip(),
            team=team,
            description=description,
            contact_email=contact_email,
            is_admin=is_admin,
            active=True,
            queue_name=f"q.{normalized}",
        )
        self.module_repo.add(module)
        await self.module_repo.flush()
        logger.info("module_registered", module=normalized)
        return module

    async def update_module(
        self,
        module_name: str,
        *,
        display_name: str | None = None,
        team: str | None = None,
        description: str | None = None,
        contact_email: str | None = None,
        active: bool | None = None,
    ) -> ModuleAccount:
        module = await self.get_module_by_name(module_name)
        if display_name is not None:
            module.display_name = display_name.strip()
        if team is not None:
            module.team = team
        if description is not None:
            module.description = description
        if contact_email is not None:
            module.contact_email = contact_email
        if active is not None:
            # Dar de baja deja de entregarle eventos sin borrar sus
            # suscripciones: quedan declaradas para cuando vuelva.
            module.active = active
        return module

    # ------------------------------------------------------------------
    # Tipos de evento
    # ------------------------------------------------------------------
    async def search_event_types(self, **kwargs: Any) -> Page[EventType]:
        return await self.event_type_repo.search(**kwargs)

    async def list_event_types(self) -> list[EventType]:
        return await self.event_type_repo.list_ordered()

    async def get_event_type(self, name: str) -> EventType:
        event_type = await self.event_type_repo.get_by_name(name)
        if event_type is None:
            raise NotFoundError(f"No existe el tipo de evento '{name}'.")
        return event_type

    async def declare_event_type(
        self,
        *,
        name: str,
        owner_module: str | None = None,
        description: str = "",
        json_schema: dict | None = None,
    ) -> EventType:
        """Declara un tipo de evento.

        Si ya existia (porque se auto-registro al aparecer por el hub), se le
        completan los datos y se le quita la marca de `discovered`.
        """
        if json_schema:
            assert_valid_schema(json_schema)

        normalized = name.strip()
        existing = await self.event_type_repo.get_by_name(normalized)
        if existing is not None:
            existing.discovered = False
            if description:
                existing.description = description
            if owner_module:
                existing.owner_module = owner_module.strip().lower()
            if json_schema is not None:
                existing.json_schema = json_schema
            return existing

        event_type = EventType(
            name=normalized,
            owner_module=owner_module.strip().lower() if owner_module else None,
            description=description,
            json_schema=json_schema,
            discovered=False,
            total_received=0,
        )
        self.event_type_repo.add(event_type)
        await self.event_type_repo.flush()
        return event_type

    async def set_schema(self, name: str, *, json_schema: dict | None) -> EventType:
        """Activa o quita la validacion de estructura de un tipo.

        `None` desactiva la validacion: el evento vuelve a pasar sin que le miren
        el `data`.
        """
        event_type = await self.get_event_type(name)
        if json_schema:
            assert_valid_schema(json_schema)
        event_type.json_schema = json_schema
        logger.info(
            "event_type_schema_updated",
            event_type=event_type.name,
            validating=bool(json_schema),
        )
        return event_type

    # ------------------------------------------------------------------
    # Suscripciones
    # ------------------------------------------------------------------
    async def list_subscriptions(self) -> list[Subscription]:
        return await self.subscription_repo.list_all()

    async def list_subscriptions_for(self, module_name: str) -> list[Subscription]:
        module = await self.get_module_by_name(module_name)
        return await self.subscription_repo.list_for_module(module.id)

    async def subscribe(
        self,
        *,
        module_name: str,
        event_type_name: str,
        max_attempts: int = 4,
        actor_module: str | None = None,
        actor_is_admin: bool = False,
    ) -> Subscription:
        """Suscribe un modulo a un tipo de evento y aplica la topologia.

        Un modulo solo puede suscribirse a si mismo. El admin puede hacerlo por
        cualquiera, para poder acomodar la integracion desde el panel.
        """
        self._assert_can_act_on(module_name, actor_module, actor_is_admin)

        module = await self.get_module_by_name(module_name)
        # Suscribirse a un tipo que todavia nadie publico es valido: el equipo se
        # anticipa y cuando el evento llegue, ya tiene destino.
        event_type = await self.event_type_repo.get_by_name(event_type_name)
        if event_type is None:
            event_type = await self.declare_event_type(name=event_type_name)

        existing = await self.subscription_repo.find_pair(module.id, event_type.id)
        if existing is not None:
            existing.active = True
            existing.max_attempts = max_attempts
            await self.apply_topology(raise_on_error=False)
            return existing

        subscription = Subscription(
            module_id=module.id,
            event_type_id=event_type.id,
            max_attempts=max_attempts,
            active=True,
        )
        self.subscription_repo.add(subscription)
        await self.subscription_repo.flush()

        # Se aplica en el acto para que la cola exista antes del primer evento.
        await self.apply_topology(raise_on_error=False)
        logger.info("subscribed", module=module.name, event_type=event_type.name)
        return subscription

    async def unsubscribe(
        self,
        subscription_id: uuid.UUID,
        *,
        actor_module: str | None = None,
        actor_is_admin: bool = False,
    ) -> None:
        subscription = await self.subscription_repo.get_required(subscription_id)
        self._assert_can_act_on(subscription.module.name, actor_module, actor_is_admin)
        await self.subscription_repo.delete(subscription)
        logger.info(
            "unsubscribed",
            module=subscription.module.name,
            event_type=subscription.event_type.name,
        )

    async def set_subscription_active(
        self,
        subscription_id: uuid.UUID,
        *,
        active: bool,
        actor_module: str | None = None,
        actor_is_admin: bool = False,
    ) -> Subscription:
        subscription = await self.subscription_repo.get_required(subscription_id)
        self._assert_can_act_on(subscription.module.name, actor_module, actor_is_admin)
        subscription.active = active
        await self.apply_topology(raise_on_error=False)
        return subscription

    # ------------------------------------------------------------------
    # Publicaciones (documentacion del mapa de eventos)
    # ------------------------------------------------------------------
    async def list_publications(self) -> list[Publication]:
        return await self.publication_repo.list_all()

    async def declare_publication(
        self,
        *,
        module_name: str,
        event_type_name: str,
        actor_module: str | None = None,
        actor_is_admin: bool = False,
    ) -> Publication:
        """Declara que un modulo publica un tipo. Es informativo: no es un permiso.

        Publicar un evento no declarado funciona igual. Esto existe para que el
        dashboard pueda mostrar el mapa de quien manda que.
        """
        self._assert_can_act_on(module_name, actor_module, actor_is_admin)

        module = await self.get_module_by_name(module_name)
        event_type = await self.event_type_repo.get_by_name(event_type_name)
        if event_type is None:
            event_type = await self.declare_event_type(
                name=event_type_name, owner_module=module_name
            )

        existing = await self.publication_repo.find_pair(module.id, event_type.id)
        if existing is not None:
            existing.active = True
            return existing

        publication = Publication(module_id=module.id, event_type_id=event_type.id, active=True)
        self.publication_repo.add(publication)
        await self.publication_repo.flush()
        return publication

    async def remove_publication(
        self,
        publication_id: uuid.UUID,
        *,
        actor_module: str | None = None,
        actor_is_admin: bool = False,
    ) -> None:
        publication = await self.publication_repo.get_required(publication_id)
        self._assert_can_act_on(publication.module.name, actor_module, actor_is_admin)
        await self.publication_repo.delete(publication)

    # ------------------------------------------------------------------
    # Topologia
    # ------------------------------------------------------------------
    async def planned_topology(self) -> Topology:
        queues = await self.subscription_repo.active_queue_names()
        return full_topology(queues)

    async def apply_topology(self, *, raise_on_error: bool = True) -> Topology:
        """Declara la topologia en el broker. Es idempotente.

        Si el broker no responde, la operacion de negocio (crear una suscripcion)
        **no se revierte**: queda en el registry y se aplica en el proximo
        arranque o al reintentar desde el panel.
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
        return topology

    @staticmethod
    def _assert_can_act_on(
        module_name: str, actor_module: str | None, actor_is_admin: bool
    ) -> None:
        if actor_is_admin or actor_module is None:
            return
        if module_name.strip().lower() != actor_module.strip().lower():
            raise ForbiddenError(
                f"Estas autenticado como '{actor_module}' y solo podes administrar "
                f"tus propias suscripciones, no las de '{module_name}'."
            )
