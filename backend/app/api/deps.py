"""Inyeccion de dependencias de la capa de presentacion.

Aca se arma el grafo: sesion -> repositorios -> servicios. Los routers reciben
servicios ya construidos, con lo cual nunca ven una sesion de SQLAlchemy ni
pueden escribir una query, y los servicios nunca ven un `Request`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import set_actor
from app.core.database import get_session
from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.security import TOKEN_TYPE_SERVICE, decode_token
from app.messaging.broker import Broker
from app.messaging.provider import get_broker
from app.notifications.channels import ChannelRegistry
from app.repositories.catalog_repository import (
    BarrioRepository,
    CatalogItemRepository,
    CatalogTypeRepository,
    DependenciaRepository,
    ZonaRepository,
)
from app.repositories.contract_repository import (
    ContractVersionRepository,
    EventTypeRepository,
    ModuleRepository,
    ProducerRepository,
    SubscriptionRepository,
)
from app.repositories.event_repository import (
    DeadLetterRepository,
    DeliveryRepository,
    EventLogRepository,
    ProcessedEventRepository,
    RetryAuditRepository,
)
from app.repositories.identity_repository import (
    ApiClientRepository,
    PermissionRepository,
    RefreshTokenRepository,
    RoleRepository,
    UserRepository,
)
from app.repositories.monitoring_repository import AuditLogRepository, HealthCheckRepository
from app.repositories.notification_repository import (
    NotificationPreferenceRepository,
    NotificationRepository,
    NotificationRuleRepository,
    NotificationTemplateRepository,
)
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService
from app.services.catalog_service import CatalogService
from app.services.contract_service import ContractService
from app.services.delivery_service import DeliveryService
from app.services.event_hub_service import EventHubService
from app.services.internal_consumer_service import InternalConsumerService
from app.services.monitoring_service import MonitoringService
from app.services.notification_service import NotificationService
from app.services.registry_service import RegistryService
from app.services.user_service import ApiClientService, UserService

SessionDep = Annotated[AsyncSession, Depends(get_session)]

# auto_error=False para poder devolver el error con la forma unificada del Core
# en lugar del 403 crudo de Starlette.
_bearer = HTTPBearer(auto_error=False, description="Access token emitido por el Core")

_channels = ChannelRegistry()


def get_channel_registry() -> ChannelRegistry:
    return _channels


def get_message_broker() -> Broker:
    return get_broker()


BrokerDep = Annotated[Broker, Depends(get_message_broker)]


# ----------------------------------------------------------------------
# Principal autenticado
# ----------------------------------------------------------------------
@dataclass
class Principal:
    """Quien esta llamando: una persona o un modulo.

    Para autorizar da lo mismo el origen: se unifican `permissions` (personas) y
    `scopes` (modulos) en un solo conjunto de capacidades.
    """

    subject: str
    kind: str  # "user" | "module"
    roles: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    scopes: list[str] = field(default_factory=list)
    email: str | None = None
    name: str | None = None
    module: str | None = None
    user_id: uuid.UUID | None = None

    @property
    def capabilities(self) -> set[str]:
        return set(self.permissions) | set(self.scopes)

    @property
    def label(self) -> str:
        if self.kind == "module":
            return f"module:{self.module}"
        return self.email or self.subject

    def has(self, code: str) -> bool:
        return code in self.capabilities


async def get_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError("Falta el header Authorization: Bearer <token>.")

    claims = decode_token(credentials.credentials)
    is_module = claims.get("typ") == TOKEN_TYPE_SERVICE

    principal = Principal(
        subject=str(claims.get("sub", "")),
        kind="module" if is_module else "user",
        roles=list(claims.get("roles", [])),
        permissions=list(claims.get("permissions", [])),
        scopes=list(claims.get("scopes", [])),
        email=claims.get("email"),
        name=claims.get("name"),
        module=claims.get("module"),
        user_id=_maybe_uuid(claims.get("sub")) if not is_module else None,
    )
    # El actor viaja por contexto: el servicio de auditoria lo lee de ahi y no
    # depende de que cada llamador se acuerde de pasarlo.
    set_actor(principal.label)
    return principal


PrincipalDep = Annotated[Principal, Depends(get_principal)]


def require_permissions(*codes: str, require_all: bool = True):
    """Dependencia de autorizacion.

    Uso: `dependencies=[Depends(require_permissions("dlq:retry"))]`.
    """

    async def _guard(principal: PrincipalDep) -> Principal:
        held = principal.capabilities
        needed = set(codes)
        ok = needed <= held if require_all else bool(needed & held)
        if not ok:
            raise ForbiddenError(
                "No tenes permisos suficientes para esta operacion. "
                f"Requiere: {sorted(needed)}.",
                details=[{"required": sorted(needed), "granted": sorted(held)}],
            )
        return principal

    return _guard


def require_roles(*codes: str):
    async def _guard(principal: PrincipalDep) -> Principal:
        if not set(codes) & set(principal.roles):
            raise ForbiddenError(
                f"Esta operacion requiere alguno de estos roles: {sorted(codes)}."
            )
        return principal

    return _guard


# ----------------------------------------------------------------------
# Repositorios
# ----------------------------------------------------------------------
def _repo(cls):
    def provider(session: SessionDep):
        return cls(session)

    return provider


UserRepoDep = Annotated[UserRepository, Depends(_repo(UserRepository))]
RoleRepoDep = Annotated[RoleRepository, Depends(_repo(RoleRepository))]
PermissionRepoDep = Annotated[PermissionRepository, Depends(_repo(PermissionRepository))]
RefreshRepoDep = Annotated[RefreshTokenRepository, Depends(_repo(RefreshTokenRepository))]
ApiClientRepoDep = Annotated[ApiClientRepository, Depends(_repo(ApiClientRepository))]
AuditRepoDep = Annotated[AuditLogRepository, Depends(_repo(AuditLogRepository))]
HealthRepoDep = Annotated[HealthCheckRepository, Depends(_repo(HealthCheckRepository))]
EventTypeRepoDep = Annotated[EventTypeRepository, Depends(_repo(EventTypeRepository))]
VersionRepoDep = Annotated[ContractVersionRepository, Depends(_repo(ContractVersionRepository))]
ModuleRepoDep = Annotated[ModuleRepository, Depends(_repo(ModuleRepository))]
ProducerRepoDep = Annotated[ProducerRepository, Depends(_repo(ProducerRepository))]
SubscriptionRepoDep = Annotated[SubscriptionRepository, Depends(_repo(SubscriptionRepository))]
EventLogRepoDep = Annotated[EventLogRepository, Depends(_repo(EventLogRepository))]
DeliveryRepoDep = Annotated[DeliveryRepository, Depends(_repo(DeliveryRepository))]
DeadLetterRepoDep = Annotated[DeadLetterRepository, Depends(_repo(DeadLetterRepository))]
RetryAuditRepoDep = Annotated[RetryAuditRepository, Depends(_repo(RetryAuditRepository))]
ProcessedRepoDep = Annotated[ProcessedEventRepository, Depends(_repo(ProcessedEventRepository))]
TemplateRepoDep = Annotated[
    NotificationTemplateRepository, Depends(_repo(NotificationTemplateRepository))
]
RuleRepoDep = Annotated[NotificationRuleRepository, Depends(_repo(NotificationRuleRepository))]
PreferenceRepoDep = Annotated[
    NotificationPreferenceRepository, Depends(_repo(NotificationPreferenceRepository))
]
NotificationRepoDep = Annotated[NotificationRepository, Depends(_repo(NotificationRepository))]
DependenciaRepoDep = Annotated[DependenciaRepository, Depends(_repo(DependenciaRepository))]
ZonaRepoDep = Annotated[ZonaRepository, Depends(_repo(ZonaRepository))]
BarrioRepoDep = Annotated[BarrioRepository, Depends(_repo(BarrioRepository))]
CatalogTypeRepoDep = Annotated[CatalogTypeRepository, Depends(_repo(CatalogTypeRepository))]
CatalogItemRepoDep = Annotated[CatalogItemRepository, Depends(_repo(CatalogItemRepository))]


# ----------------------------------------------------------------------
# Servicios
# ----------------------------------------------------------------------
def get_audit_service(audit_repo: AuditRepoDep) -> AuditService:
    return AuditService(audit_repo)


AuditDep = Annotated[AuditService, Depends(get_audit_service)]


def get_auth_service(
    user_repo: UserRepoDep, refresh_repo: RefreshRepoDep, client_repo: ApiClientRepoDep
) -> AuthService:
    return AuthService(user_repo=user_repo, refresh_repo=refresh_repo, client_repo=client_repo)


def get_user_service(
    user_repo: UserRepoDep,
    role_repo: RoleRepoDep,
    permission_repo: PermissionRepoDep,
    refresh_repo: RefreshRepoDep,
    audit: AuditDep,
) -> UserService:
    return UserService(
        user_repo=user_repo,
        role_repo=role_repo,
        permission_repo=permission_repo,
        refresh_repo=refresh_repo,
        audit=audit,
    )


def get_api_client_service(client_repo: ApiClientRepoDep, audit: AuditDep) -> ApiClientService:
    return ApiClientService(client_repo=client_repo, audit=audit)


def get_catalog_service(
    dependencia_repo: DependenciaRepoDep,
    zona_repo: ZonaRepoDep,
    barrio_repo: BarrioRepoDep,
    catalog_type_repo: CatalogTypeRepoDep,
    catalog_item_repo: CatalogItemRepoDep,
    audit: AuditDep,
) -> CatalogService:
    return CatalogService(
        dependencia_repo=dependencia_repo,
        zona_repo=zona_repo,
        barrio_repo=barrio_repo,
        catalog_type_repo=catalog_type_repo,
        catalog_item_repo=catalog_item_repo,
        audit=audit,
    )


def get_contract_service(
    event_type_repo: EventTypeRepoDep, version_repo: VersionRepoDep, audit: AuditDep
) -> ContractService:
    return ContractService(
        event_type_repo=event_type_repo, version_repo=version_repo, audit=audit
    )


def get_registry_service(
    module_repo: ModuleRepoDep,
    producer_repo: ProducerRepoDep,
    subscription_repo: SubscriptionRepoDep,
    event_type_repo: EventTypeRepoDep,
    rule_repo: RuleRepoDep,
    broker: BrokerDep,
    audit: AuditDep,
) -> RegistryService:
    return RegistryService(
        module_repo=module_repo,
        producer_repo=producer_repo,
        subscription_repo=subscription_repo,
        event_type_repo=event_type_repo,
        rule_repo=rule_repo,
        broker=broker,
        audit=audit,
    )


def get_hub_service(
    event_log_repo: EventLogRepoDep,
    delivery_repo: DeliveryRepoDep,
    dead_letter_repo: DeadLetterRepoDep,
    event_type_repo: EventTypeRepoDep,
    version_repo: VersionRepoDep,
    subscription_repo: SubscriptionRepoDep,
    broker: BrokerDep,
) -> EventHubService:
    return EventHubService(
        event_log_repo=event_log_repo,
        delivery_repo=delivery_repo,
        dead_letter_repo=dead_letter_repo,
        event_type_repo=event_type_repo,
        version_repo=version_repo,
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


def get_notification_service(
    template_repo: TemplateRepoDep,
    rule_repo: RuleRepoDep,
    preference_repo: PreferenceRepoDep,
    notification_repo: NotificationRepoDep,
    user_repo: UserRepoDep,
    channels: Annotated[ChannelRegistry, Depends(get_channel_registry)],
    audit: AuditDep,
) -> NotificationService:
    return NotificationService(
        template_repo=template_repo,
        rule_repo=rule_repo,
        preference_repo=preference_repo,
        notification_repo=notification_repo,
        user_repo=user_repo,
        channels=channels,
        audit=audit,
    )


def get_monitoring_service(
    module_repo: ModuleRepoDep,
    health_repo: HealthRepoDep,
    event_log_repo: EventLogRepoDep,
    delivery_repo: DeliveryRepoDep,
    dead_letter_repo: DeadLetterRepoDep,
    notification_repo: NotificationRepoDep,
    broker: BrokerDep,
) -> MonitoringService:
    return MonitoringService(
        module_repo=module_repo,
        health_repo=health_repo,
        event_log_repo=event_log_repo,
        delivery_repo=delivery_repo,
        dead_letter_repo=dead_letter_repo,
        notification_repo=notification_repo,
        broker=broker,
    )


def get_internal_consumer(
    hub: HubDep,
    user_service: Annotated[UserService, Depends(get_user_service)],
    notification_service: Annotated[NotificationService, Depends(get_notification_service)],
    processed_repo: ProcessedRepoDep,
) -> InternalConsumerService:
    return InternalConsumerService(
        hub=hub,
        user_service=user_service,
        notification_service=notification_service,
        processed_repo=processed_repo,
    )


AuthDep = Annotated[AuthService, Depends(get_auth_service)]
UserServiceDep = Annotated[UserService, Depends(get_user_service)]
ApiClientServiceDep = Annotated[ApiClientService, Depends(get_api_client_service)]
CatalogDep = Annotated[CatalogService, Depends(get_catalog_service)]
ContractDep = Annotated[ContractService, Depends(get_contract_service)]
RegistryDep = Annotated[RegistryService, Depends(get_registry_service)]
DeliveryDep = Annotated[DeliveryService, Depends(get_delivery_service)]
NotificationDep = Annotated[NotificationService, Depends(get_notification_service)]
MonitoringDep = Annotated[MonitoringService, Depends(get_monitoring_service)]
InternalConsumerDep = Annotated[InternalConsumerService, Depends(get_internal_consumer)]


def client_user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent")


UserAgentDep = Annotated[str | None, Depends(client_user_agent)]


def _maybe_uuid(value: object) -> uuid.UUID | None:
    if isinstance(value, str):
        try:
            return uuid.UUID(value)
        except ValueError:
            return None
    return None
