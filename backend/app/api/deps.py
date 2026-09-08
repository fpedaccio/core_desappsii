"""Inyeccion de dependencias de la capa de presentacion.

Aca se arma el grafo sesion -> repositorios -> servicios. Los routers reciben
servicios ya construidos: no ven una sesion de SQLAlchemy ni pueden escribir una
query, y los servicios no ven un `Request`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import set_actor
from app.core.database import get_session
from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.security import decode_token
from app.messaging.broker import Broker
from app.messaging.provider import get_broker
from app.repositories.event_repository import (
    DeadLetterRepository,
    DeliveryRepository,
    EventLogRepository,
    RetryAuditRepository,
)
from app.repositories.registry_repository import (
    EventTypeRepository,
    ModuleRepository,
    PublicationRepository,
    SubscriptionRepository,
    UserRepository,
)
from app.services.auth_service import AuthService
from app.services.delivery_service import DeliveryService
from app.services.event_hub_service import EventHubService
from app.services.registry_service import RegistryService
from app.services.stats_service import StatsService
from app.services.user_service import UserService

SessionDep = Annotated[AsyncSession, Depends(get_session)]

# auto_error=False para devolver el error con la forma unificada del Core en
# lugar del 403 crudo de Starlette.
_bearer = HTTPBearer(auto_error=False, description="Token emitido por POST /auth/login")


def get_message_broker() -> Broker:
    return get_broker()


BrokerDep = Annotated[Broker, Depends(get_message_broker)]


# ----------------------------------------------------------------------
# Quien esta llamando
# ----------------------------------------------------------------------
@dataclass
class Caller:
    """Quien esta llamando: una persona del dashboard o el backend de un modulo.

    Los dos vienen atados a un modulo, y de ahi sale que datos pueden ver. No hay
    roles: el unico privilegio es el `is_admin` del modulo (el equipo 9).

    `actor` es lo que se registra en la auditoria: el email de la persona, o
    `module:<nombre>` si el que llama es un backend.
    """

    module: str
    display_name: str
    is_admin: bool
    kind: str  # "user" | "module"
    actor: str
    email: str | None = None
    name: str | None = None

    @property
    def is_person(self) -> bool:
        return self.kind == "user"

    @property
    def scope(self) -> str | None:
        """El filtro de datos. `None` = sin filtro, ve todo.

        Es lo que se le pasa a los repositorios. Un modulo comun siempre queda
        limitado a lo suyo, sin importar que query params mande.
        """
        return None if self.is_admin else self.module


async def get_caller(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Caller:
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError("Falta el header Authorization: Bearer <token>.")

    claims = decode_token(credentials.credentials)
    module = claims.get("module")
    if not module:
        raise UnauthorizedError("El token no identifica un modulo.", code="TOKEN_INVALID")

    kind = str(claims.get("kind") or "module")
    email = claims.get("email")

    caller = Caller(
        module=str(module),
        display_name=str(claims.get("displayName") or module),
        is_admin=bool(claims.get("isAdmin")),
        kind=kind,
        # La auditoria registra a la persona cuando hay una. Que un reintento
        # diga "lo hizo tal" y no "lo hizo el equipo 9" es justamente el punto
        # de tener cuentas por persona.
        actor=str(email) if email else f"module:{module}",
        email=email,
        name=claims.get("name"),
    )
    set_actor(caller.actor)
    return caller


CallerDep = Annotated[Caller, Depends(get_caller)]


async def require_admin(caller: CallerDep) -> Caller:
    """Solo el equipo 9. Para administrar modulos y ver el hub completo."""
    if not caller.is_admin:
        raise ForbiddenError(
            "Esta operacion es del administrador del Core. Estas autenticado como "
            f"'{caller.module}'."
        )
    return caller


AdminDep = Annotated[Caller, Depends(require_admin)]


# ----------------------------------------------------------------------
# Repositorios
# ----------------------------------------------------------------------
def _repo(cls):
    def provider(session: SessionDep):
        return cls(session)

    return provider


ModuleRepoDep = Annotated[ModuleRepository, Depends(_repo(ModuleRepository))]
EventTypeRepoDep = Annotated[EventTypeRepository, Depends(_repo(EventTypeRepository))]
SubscriptionRepoDep = Annotated[SubscriptionRepository, Depends(_repo(SubscriptionRepository))]
PublicationRepoDep = Annotated[PublicationRepository, Depends(_repo(PublicationRepository))]
EventLogRepoDep = Annotated[EventLogRepository, Depends(_repo(EventLogRepository))]
DeliveryRepoDep = Annotated[DeliveryRepository, Depends(_repo(DeliveryRepository))]
DeadLetterRepoDep = Annotated[DeadLetterRepository, Depends(_repo(DeadLetterRepository))]
RetryAuditRepoDep = Annotated[RetryAuditRepository, Depends(_repo(RetryAuditRepository))]
UserRepoDep = Annotated[UserRepository, Depends(_repo(UserRepository))]


# ----------------------------------------------------------------------
# Servicios
# ----------------------------------------------------------------------
def get_auth_service(user_repo: UserRepoDep, module_repo: ModuleRepoDep) -> AuthService:
    return AuthService(user_repo=user_repo, module_repo=module_repo)


def get_user_service(user_repo: UserRepoDep, module_repo: ModuleRepoDep) -> UserService:
    return UserService(user_repo=user_repo, module_repo=module_repo)


def get_registry_service(
    module_repo: ModuleRepoDep,
    event_type_repo: EventTypeRepoDep,
    subscription_repo: SubscriptionRepoDep,
    publication_repo: PublicationRepoDep,
    broker: BrokerDep,
) -> RegistryService:
    return RegistryService(
        module_repo=module_repo,
        event_type_repo=event_type_repo,
        subscription_repo=subscription_repo,
        publication_repo=publication_repo,
        broker=broker,
    )


def get_hub_service(
    event_log_repo: EventLogRepoDep,
    delivery_repo: DeliveryRepoDep,
    dead_letter_repo: DeadLetterRepoDep,
    event_type_repo: EventTypeRepoDep,
    subscription_repo: SubscriptionRepoDep,
    broker: BrokerDep,
) -> EventHubService:
    return EventHubService(
        event_log_repo=event_log_repo,
        delivery_repo=delivery_repo,
        dead_letter_repo=dead_letter_repo,
        event_type_repo=event_type_repo,
        subscription_repo=subscription_repo,
        broker=broker,
    )


HubDep = Annotated[EventHubService, Depends(get_hub_service)]


def get_delivery_service(
    delivery_repo: DeliveryRepoDep,
    dead_letter_repo: DeadLetterRepoDep,
    retry_audit_repo: RetryAuditRepoDep,
    event_log_repo: EventLogRepoDep,
    hub: HubDep,
    broker: BrokerDep,
) -> DeliveryService:
    return DeliveryService(
        delivery_repo=delivery_repo,
        dead_letter_repo=dead_letter_repo,
        retry_audit_repo=retry_audit_repo,
        event_log_repo=event_log_repo,
        hub=hub,
        broker=broker,
    )


def get_stats_service(
    event_log_repo: EventLogRepoDep,
    delivery_repo: DeliveryRepoDep,
    dead_letter_repo: DeadLetterRepoDep,
    module_repo: ModuleRepoDep,
    event_type_repo: EventTypeRepoDep,
    subscription_repo: SubscriptionRepoDep,
    publication_repo: PublicationRepoDep,
    broker: BrokerDep,
) -> StatsService:
    return StatsService(
        event_log_repo=event_log_repo,
        delivery_repo=delivery_repo,
        dead_letter_repo=dead_letter_repo,
        module_repo=module_repo,
        event_type_repo=event_type_repo,
        subscription_repo=subscription_repo,
        publication_repo=publication_repo,
        broker=broker,
    )


AuthDep = Annotated[AuthService, Depends(get_auth_service)]
UserServiceDep = Annotated[UserService, Depends(get_user_service)]
RegistryDep = Annotated[RegistryService, Depends(get_registry_service)]
DeliveryDep = Annotated[DeliveryService, Depends(get_delivery_service)]
StatsDep = Annotated[StatsService, Depends(get_stats_service)]


def client_user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent")
