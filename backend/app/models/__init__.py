"""Entidades ORM del Core.

Se reexportan todas desde aca para que Alembic las descubra con un solo import
y para tener un unico lugar donde ver el modelo completo del modulo.
"""

from app.core.database import Base
from app.models.catalog import Barrio, CatalogItem, CatalogType, Dependencia, Zona
from app.models.contracts import (
    Compatibility,
    EventContractVersion,
    EventType,
    EventTypeStatus,
    Producer,
    RegisteredModule,
    Subscription,
)
from app.models.events import (
    DeadLetter,
    DeadLetterStatus,
    Delivery,
    DeliveryStatus,
    EventLog,
    EventStatus,
    IngestionChannel,
    ProcessedEvent,
    RetryAudit,
    RetryMode,
    RetryResult,
)
from app.models.identity import (
    ApiClient,
    Permission,
    RefreshToken,
    Role,
    User,
    UserStatus,
    role_permissions,
    user_roles,
)
from app.models.monitoring import AuditLog, HealthCheck, HealthStatus
from app.models.notifications import (
    Channel,
    Notification,
    NotificationPreference,
    NotificationRule,
    NotificationStatus,
    NotificationTemplate,
    RecipientSource,
)

__all__ = [
    "ApiClient",
    "AuditLog",
    "Barrio",
    "Base",
    "CatalogItem",
    "CatalogType",
    "Channel",
    "Compatibility",
    "DeadLetter",
    "DeadLetterStatus",
    "Delivery",
    "DeliveryStatus",
    "Dependencia",
    "EventContractVersion",
    "EventLog",
    "EventStatus",
    "EventType",
    "EventTypeStatus",
    "HealthCheck",
    "HealthStatus",
    "IngestionChannel",
    "Notification",
    "NotificationPreference",
    "NotificationRule",
    "NotificationStatus",
    "NotificationTemplate",
    "Permission",
    "ProcessedEvent",
    "Producer",
    "RecipientSource",
    "RefreshToken",
    "RegisteredModule",
    "RetryAudit",
    "RetryMode",
    "RetryResult",
    "Role",
    "Subscription",
    "User",
    "UserStatus",
    "Zona",
    "role_permissions",
    "user_roles",
]
