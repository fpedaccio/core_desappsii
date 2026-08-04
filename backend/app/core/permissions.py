"""Catalogo de permisos y roles del Core.

Los permisos son finos y con forma `recurso:accion`. Los roles del enunciado
(administradores, responsables de seguridad, operadores tecnicos, auditores,
responsables de integracion) se arman agrupandolos, asi que se puede crear un rol
nuevo desde el panel sin tocar el codigo.

Este modulo es la unica fuente: lo usan los guards de los endpoints y el seed.
"""

from __future__ import annotations

from typing import NamedTuple


class PermissionDef(NamedTuple):
    code: str
    description: str

    @property
    def resource(self) -> str:
        return self.code.split(":", 1)[0]

    @property
    def action(self) -> str:
        return self.code.split(":", 1)[1]


# --- Identidad ---------------------------------------------------------
USERS_READ = "users:read"
USERS_WRITE = "users:write"
ROLES_READ = "roles:read"
ROLES_WRITE = "roles:write"
CLIENTS_READ = "clients:read"
CLIENTS_WRITE = "clients:write"

# --- Catalogos --------------------------------------------------------
CATALOGS_READ = "catalogs:read"
CATALOGS_WRITE = "catalogs:write"

# --- Contratos --------------------------------------------------------
CONTRACTS_READ = "contracts:read"
CONTRACTS_WRITE = "contracts:write"
CONTRACTS_PUBLISH = "contracts:publish"

# --- Registry ---------------------------------------------------------
REGISTRY_READ = "registry:read"
REGISTRY_WRITE = "registry:write"
TOPOLOGY_APPLY = "topology:apply"

# --- Hub de eventos ---------------------------------------------------
EVENTS_PUBLISH = "events:publish"
EVENTS_READ = "events:read"

# --- DLQ --------------------------------------------------------------
DLQ_READ = "dlq:read"
DLQ_RETRY = "dlq:retry"
DLQ_DISCARD = "dlq:discard"

# --- Notificaciones ---------------------------------------------------
NOTIFICATIONS_READ = "notifications:read"
NOTIFICATIONS_WRITE = "notifications:write"
NOTIFICATIONS_SEND = "notifications:send"

# --- Monitoreo y auditoria -------------------------------------------
MONITORING_READ = "monitoring:read"
AUDIT_READ = "audit:read"


ALL_PERMISSIONS: tuple[PermissionDef, ...] = (
    PermissionDef(USERS_READ, "Ver usuarios y sus roles"),
    PermissionDef(USERS_WRITE, "Crear, editar y bloquear usuarios"),
    PermissionDef(ROLES_READ, "Ver roles y permisos"),
    PermissionDef(ROLES_WRITE, "Crear y editar roles"),
    PermissionDef(CLIENTS_READ, "Ver las cuentas de servicio de los modulos"),
    PermissionDef(CLIENTS_WRITE, "Crear cuentas de servicio y rotar sus secrets"),
    PermissionDef(CATALOGS_READ, "Consultar catalogos globales"),
    PermissionDef(CATALOGS_WRITE, "Administrar catalogos globales"),
    PermissionDef(CONTRACTS_READ, "Consultar el catalogo de eventos y sus contratos"),
    PermissionDef(CONTRACTS_WRITE, "Registrar tipos de evento y versiones de contrato"),
    PermissionDef(CONTRACTS_PUBLISH, "Publicar y deprecar versiones de contrato"),
    PermissionDef(REGISTRY_READ, "Ver modulos, productores y suscripciones"),
    PermissionDef(REGISTRY_WRITE, "Registrar modulos y administrar suscripciones"),
    PermissionDef(TOPOLOGY_APPLY, "Aplicar la topologia de mensajeria en el broker"),
    PermissionDef(EVENTS_PUBLISH, "Publicar eventos en el hub"),
    PermissionDef(EVENTS_READ, "Consultar la bitacora de eventos y sus entregas"),
    PermissionDef(DLQ_READ, "Consultar la Dead Letter Queue"),
    PermissionDef(DLQ_RETRY, "Reintentar mensajes de la DLQ"),
    PermissionDef(DLQ_DISCARD, "Descartar mensajes de la DLQ con motivo"),
    PermissionDef(NOTIFICATIONS_READ, "Ver plantillas, reglas e historial de notificaciones"),
    PermissionDef(NOTIFICATIONS_WRITE, "Administrar plantillas, reglas y preferencias"),
    PermissionDef(NOTIFICATIONS_SEND, "Reintentar envios de notificacion"),
    PermissionDef(MONITORING_READ, "Ver tableros, metricas y salud de los modulos"),
    PermissionDef(AUDIT_READ, "Consultar la auditoria"),
)

READ_ONLY_PERMISSIONS = tuple(
    perm.code for perm in ALL_PERMISSIONS if perm.action in {"read"}
)


class RoleDef(NamedTuple):
    code: str
    name: str
    description: str
    permissions: tuple[str, ...]


ROLE_ADMIN = "ADMIN_SISTEMA"
ROLE_SECURITY = "RESPONSABLE_SEGURIDAD"
ROLE_OPERATOR = "OPERADOR_TECNICO"
ROLE_INTEGRATION = "RESPONSABLE_INTEGRACION"
ROLE_AUDITOR = "AUDITOR"
ROLE_CITIZEN = "CIUDADANO"


SYSTEM_ROLES: tuple[RoleDef, ...] = (
    RoleDef(
        ROLE_ADMIN,
        "Administrador del sistema",
        "Acceso total al modulo Core.",
        tuple(perm.code for perm in ALL_PERMISSIONS),
    ),
    RoleDef(
        ROLE_SECURITY,
        "Responsable de seguridad",
        "Administra identidades, roles, permisos y cuentas de servicio.",
        (
            USERS_READ,
            USERS_WRITE,
            ROLES_READ,
            ROLES_WRITE,
            CLIENTS_READ,
            CLIENTS_WRITE,
            AUDIT_READ,
            MONITORING_READ,
        ),
    ),
    RoleDef(
        ROLE_OPERATOR,
        "Operador tecnico",
        "Opera el hub en el dia a dia: mira eventos, reintenta y descarta DLQ.",
        (
            EVENTS_READ,
            DLQ_READ,
            DLQ_RETRY,
            DLQ_DISCARD,
            MONITORING_READ,
            REGISTRY_READ,
            CONTRACTS_READ,
            CATALOGS_READ,
            NOTIFICATIONS_READ,
            NOTIFICATIONS_SEND,
        ),
    ),
    RoleDef(
        ROLE_INTEGRATION,
        "Responsable de integracion y comunicaciones",
        "Registra modulos, contratos y suscripciones, y configura notificaciones.",
        (
            REGISTRY_READ,
            REGISTRY_WRITE,
            TOPOLOGY_APPLY,
            CONTRACTS_READ,
            CONTRACTS_WRITE,
            CONTRACTS_PUBLISH,
            CATALOGS_READ,
            CATALOGS_WRITE,
            EVENTS_READ,
            DLQ_READ,
            NOTIFICATIONS_READ,
            NOTIFICATIONS_WRITE,
            MONITORING_READ,
        ),
    ),
    RoleDef(
        ROLE_AUDITOR,
        "Auditor",
        "Solo lectura sobre todo el modulo, incluida la auditoria.",
        READ_ONLY_PERMISSIONS,
    ),
    RoleDef(
        ROLE_CITIZEN,
        "Ciudadano",
        "Cuenta provisionada al recibir CiudadanoRegistrado. Sin acceso al panel.",
        (),
    ),
)
