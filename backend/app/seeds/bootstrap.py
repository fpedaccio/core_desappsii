"""Carga de datos iniciales.

Idempotente de punta a punta: se puede correr sobre una base vacia o sobre una ya
poblada sin duplicar nada. Eso permite volver a ejecutarlo despues de agregar un
tipo de evento o un rol al catalogo del codigo.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import utcnow
from app.core.permissions import (
    ALL_PERMISSIONS,
    ROLE_ADMIN,
    ROLE_AUDITOR,
    ROLE_INTEGRATION,
    ROLE_OPERATOR,
    ROLE_SECURITY,
    SYSTEM_ROLES,
)
from app.core.security import generate_opaque_token, hash_opaque_token, hash_password
from app.models.catalog import Barrio, CatalogItem, CatalogType, Dependencia, Zona
from app.models.contracts import (
    EventContractVersion,
    EventType,
    Producer,
    RegisteredModule,
    Subscription,
)
from app.models.identity import ApiClient, Permission, Role, User, UserStatus
from app.models.notifications import (
    Channel,
    NotificationRule,
    NotificationTemplate,
    RecipientSource,
)
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
from app.repositories.identity_repository import (
    ApiClientRepository,
    PermissionRepository,
    RoleRepository,
    UserRepository,
)
from app.repositories.notification_repository import (
    NotificationRuleRepository,
    NotificationTemplateRepository,
)
from app.seeds import data as seed_data
from app.services.registry_service import CORE_MODULE_NAME, IDENTITY_EVENT_TYPES

logger = structlog.get_logger(__name__)


@dataclass
class SeedReport:
    permissions: int = 0
    roles: int = 0
    users: int = 0
    modules: int = 0
    event_types: int = 0
    contract_versions: int = 0
    producers: int = 0
    subscriptions: int = 0
    dependencias: int = 0
    zonas: int = 0
    barrios: int = 0
    catalog_types: int = 0
    catalog_items: int = 0
    templates: int = 0
    rules: int = 0
    api_clients: dict[str, str] = field(default_factory=dict)
    """client_id -> secret en claro. Se imprime una sola vez, al sembrar."""

    def summary(self) -> str:
        rows = [
            f"{name}={value}"
            for name, value in vars(self).items()
            if name != "api_clients" and value
        ]
        return ", ".join(rows) or "nada nuevo (la base ya estaba sembrada)"


async def seed_all(session: AsyncSession, *, create_api_clients: bool = True) -> SeedReport:
    report = SeedReport()

    await _seed_permissions(session, report)
    await _seed_roles(session, report)
    await _seed_admin(session, report)
    await _seed_demo_users(session, report)
    await _seed_catalogs(session, report)
    await _seed_modules(session, report)
    await _seed_event_types(session, report)
    await _seed_producers_and_subscriptions(session, report)
    await _seed_notifications(session, report)
    if create_api_clients:
        await _seed_api_clients(session, report)

    await session.commit()
    logger.info("seed_completed", summary=report.summary())
    return report


# ----------------------------------------------------------------------
# Identidad
# ----------------------------------------------------------------------
async def _seed_permissions(session: AsyncSession, report: SeedReport) -> None:
    repo = PermissionRepository(session)
    for spec in ALL_PERMISSIONS:
        if await repo.get_by_code(spec.code) is None:
            repo.add(
                Permission(
                    code=spec.code,
                    resource=spec.resource,
                    action=spec.action,
                    description=spec.description,
                )
            )
            report.permissions += 1
    await session.flush()


async def _seed_roles(session: AsyncSession, report: SeedReport) -> None:
    role_repo = RoleRepository(session)
    permission_repo = PermissionRepository(session)

    for spec in SYSTEM_ROLES:
        role = await role_repo.get_by_code(spec.code)
        permissions = await permission_repo.list_by_codes(list(spec.permissions))

        if role is None:
            role = Role(
                code=spec.code,
                name=spec.name,
                description=spec.description,
                is_system=True,
            )
            role.permissions = permissions
            role_repo.add(role)
            report.roles += 1
        else:
            # Reconcilia: si se agregaron permisos nuevos al codigo, los roles de
            # sistema se actualizan al volver a correr el seed.
            existing = {perm.code for perm in role.permissions}
            if existing != set(spec.permissions):
                role.permissions = permissions
    await session.flush()


async def _seed_admin(session: AsyncSession, report: SeedReport) -> None:
    user_repo = UserRepository(session)
    role_repo = RoleRepository(session)

    email = settings.seed_admin_email.lower()
    if await user_repo.get_by_email(email) is not None:
        return

    admin_role = await role_repo.get_by_code(ROLE_ADMIN)
    user = User(
        email=email,
        full_name="Administrador del Core",
        password_hash=hash_password(settings.seed_admin_password),
        status=UserStatus.ACTIVE,
        source_module="core",
    )
    if admin_role is not None:
        user.roles = [admin_role]
    user_repo.add(user)
    report.users += 1
    await session.flush()
    logger.warning(
        "seed_admin_created",
        email=email,
        hint="Cambia la contrasena antes de desplegar en un entorno accesible.",
    )


DEMO_USERS: tuple[tuple[str, str, str], ...] = (
    ("seguridad@muni.uade.edu.ar", "Sofia Registro", ROLE_SECURITY),
    ("operador@muni.uade.edu.ar", "Bruno Cortes", ROLE_OPERATOR),
    ("integracion@muni.uade.edu.ar", "Carla Enlace", ROLE_INTEGRATION),
    ("auditor@muni.uade.edu.ar", "Diego Control", ROLE_AUDITOR),
)
"""Un usuario por rol, con la misma contrasena que el admin.

Sirven para dos cosas concretas: probar a mano que el panel muestra solo las
operaciones del rol autenticado (requisito 6.1), y darle destinatario a los
avisos internos, que se dirigen a un rol y no a un email del payload.
"""


async def _seed_demo_users(session: AsyncSession, report: SeedReport) -> None:
    user_repo = UserRepository(session)
    role_repo = RoleRepository(session)

    for email, full_name, role_code in DEMO_USERS:
        if await user_repo.get_by_email(email) is not None:
            continue
        role = await role_repo.get_by_code(role_code)
        user = User(
            email=email,
            full_name=full_name,
            password_hash=hash_password(settings.seed_admin_password),
            status=UserStatus.ACTIVE,
            source_module="core",
        )
        if role is not None:
            user.roles = [role]
        user_repo.add(user)
        report.users += 1
    await session.flush()


async def _seed_api_clients(session: AsyncSession, report: SeedReport) -> None:
    """Crea una cuenta de servicio por modulo, para que puedan publicar eventos."""
    repo = ApiClientRepository(session)
    for spec in seed_data.MODULES:
        if await repo.get_by_client_id(spec.name) is not None:
            continue
        secret = generate_opaque_token()
        repo.add(
            ApiClient(
                client_id=spec.name,
                client_secret_hash=hash_opaque_token(secret),
                module_name=spec.name,
                description=f"Cuenta de servicio de {spec.display_name} ({spec.team}).",
                scopes=["events:publish", f"module:{spec.name}", "contracts:read"],
            )
        )
        report.api_clients[spec.name] = secret
    await session.flush()


# ----------------------------------------------------------------------
# Catalogos globales
# ----------------------------------------------------------------------
async def _seed_catalogs(session: AsyncSession, report: SeedReport) -> None:
    dependencia_repo = DependenciaRepository(session)
    for code, name in seed_data.DEPENDENCIAS:
        if await dependencia_repo.get_by_code(code) is None:
            dependencia_repo.add(Dependencia(code=code, name=name))
            report.dependencias += 1

    zona_repo = ZonaRepository(session)
    zonas: dict[str, Zona] = {}
    for code, name in seed_data.ZONAS:
        zona = await zona_repo.get_by_code(code)
        if zona is None:
            zona = Zona(code=code, name=name)
            zona_repo.add(zona)
            report.zonas += 1
        zonas[code] = zona
    await session.flush()

    barrio_repo = BarrioRepository(session)
    for code, name, zona_code, postal in seed_data.BARRIOS:
        if await barrio_repo.get_by_code(code) is None:
            zona = zonas.get(zona_code)
            barrio_repo.add(
                Barrio(
                    code=code,
                    name=name,
                    zona_id=zona.id if zona else None,
                    postal_code=postal,
                )
            )
            report.barrios += 1
    await session.flush()

    type_repo = CatalogTypeRepository(session)
    item_repo = CatalogItemRepository(session)
    for code, name, owner, items in seed_data.CATALOGS:
        catalog_type = await type_repo.get_by_code(code)
        if catalog_type is None:
            catalog_type = CatalogType(code=code, name=name, owner_module=owner)
            type_repo.add(catalog_type)
            report.catalog_types += 1
            await session.flush()

        for order, (item_code, label, attributes) in enumerate(items):
            if await item_repo.get_by_code(catalog_type.id, item_code) is None:
                item_repo.add(
                    CatalogItem(
                        catalog_type_id=catalog_type.id,
                        code=item_code,
                        label=label,
                        sort_order=order,
                        attributes=attributes,
                    )
                )
                report.catalog_items += 1
    await session.flush()


# ----------------------------------------------------------------------
# Registry y contratos
# ----------------------------------------------------------------------
async def _seed_modules(session: AsyncSession, report: SeedReport) -> None:
    repo = ModuleRepository(session)

    if await repo.get_by_name(CORE_MODULE_NAME) is None:
        repo.add(
            RegisteredModule(
                name=CORE_MODULE_NAME,
                display_name="Core - Identidad, Integracion, Notificaciones y Monitoreo",
                description=(
                    "Modulo 9. Hub de eventos, proveedor de identidad, catalogos "
                    "globales, DLQ, notificaciones y monitoreo."
                ),
                team="Equipo 9",
                queue_name="q.core.internal",
                health_url="http://localhost:8000/health/live",
            )
        )
        report.modules += 1

    for spec in seed_data.MODULES:
        if await repo.get_by_name(spec.name) is None:
            repo.add(
                RegisteredModule(
                    name=spec.name,
                    display_name=spec.display_name,
                    description=spec.description,
                    team=spec.team,
                    queue_name=f"q.{spec.name}",
                )
            )
            report.modules += 1
    await session.flush()


async def _seed_event_types(session: AsyncSession, report: SeedReport) -> None:
    type_repo = EventTypeRepository(session)
    version_repo = ContractVersionRepository(session)

    for spec in seed_data.EVENT_TYPES:
        event_type = await type_repo.get_by_name(spec.name)
        if event_type is None:
            event_type = EventType(
                name=spec.name, owner_module=spec.owner, description=spec.description
            )
            type_repo.add(event_type)
            report.event_types += 1
            await session.flush()

        if await version_repo.get_version(event_type.id, "1.0") is None:
            version_repo.add(
                EventContractVersion(
                    event_type_id=event_type.id,
                    version="1.0",
                    json_schema=seed_data.build_json_schema(spec.fields),
                    example=seed_data.build_example(spec.fields),
                    published_at=utcnow(),
                )
            )
            report.contract_versions += 1
    await session.flush()


async def _seed_producers_and_subscriptions(session: AsyncSession, report: SeedReport) -> None:
    module_repo = ModuleRepository(session)
    type_repo = EventTypeRepository(session)
    producer_repo = ProducerRepository(session)
    subscription_repo = SubscriptionRepository(session)

    modules = {module.name: module for module in await module_repo.list_ordered()}
    event_types = {
        event_type.name: event_type for event_type in await type_repo.list_all_with_versions()
    }

    # Productor = modulo propietario del tipo de evento.
    for spec in seed_data.EVENT_TYPES:
        module = modules.get(spec.owner)
        event_type = event_types.get(spec.name)
        if module is None or event_type is None:
            continue
        if await producer_repo.find_pair(module.id, event_type.id) is None:
            producer_repo.add(Producer(module_id=module.id, event_type_id=event_type.id))
            report.producers += 1

    # Suscripciones propias del Core: los eventos de identidad (para provisionar
    # cuentas) y los tipos que tienen una regla de notificacion configurada. Se
    # siembran aca para que la base quede consistente sin depender del arranque
    # de la aplicacion.
    core_consumes = tuple(IDENTITY_EVENT_TYPES) + tuple(
        rule.event_type for rule in seed_data.NOTIFICATION_RULES
    )
    all_subscriptions = {
        **seed_data.SUBSCRIPTIONS,
        CORE_MODULE_NAME: tuple(dict.fromkeys(core_consumes)),
    }

    for module_name, consumed in all_subscriptions.items():
        module = modules.get(module_name)
        if module is None:
            continue
        for event_type_name in consumed:
            event_type = event_types.get(event_type_name)
            if event_type is None:
                logger.warning(
                    "seed_subscription_skipped",
                    module=module_name,
                    event_type=event_type_name,
                    reason="el tipo de evento no esta en el catalogo",
                )
                continue
            if await subscription_repo.find_pair(module.id, event_type.id) is None:
                subscription_repo.add(
                    Subscription(
                        module_id=module.id,
                        event_type_id=event_type.id,
                        queue_name=module.queue_name,
                    )
                )
                report.subscriptions += 1
    await session.flush()


# ----------------------------------------------------------------------
# Notificaciones
# ----------------------------------------------------------------------
async def _seed_notifications(session: AsyncSession, report: SeedReport) -> None:
    template_repo = NotificationTemplateRepository(session)
    rule_repo = NotificationRuleRepository(session)

    templates: dict[str, NotificationTemplate] = {}
    for spec in seed_data.TEMPLATES:
        template = await template_repo.get_by_code(spec.code)
        if template is None:
            template = NotificationTemplate(
                code=spec.code,
                name=spec.name,
                channel=Channel(spec.channel),
                subject_template=spec.subject,
                body_template=spec.body,
            )
            template_repo.add(template)
            report.templates += 1
        templates[spec.code] = template
    await session.flush()

    for spec in seed_data.NOTIFICATION_RULES:
        template = templates.get(spec.template_code)
        if template is None:
            continue
        if await rule_repo.find_pair(spec.event_type, template.id) is None:
            rule_repo.add(
                NotificationRule(
                    event_type=spec.event_type,
                    template_id=template.id,
                    recipient_source=RecipientSource(spec.recipient_source),
                    recipient_expression=spec.recipient_expression,
                )
            )
            report.rules += 1
    await session.flush()
