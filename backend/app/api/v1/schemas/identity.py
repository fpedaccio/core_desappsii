"""DTOs de identidad y acceso."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import EmailStr, Field

from app.api.v1.schemas.common import CamelModel
from app.models.identity import ApiClient, Permission, Role, User, UserStatus


# ----------------------------------------------------------------------
# Autenticacion
# ----------------------------------------------------------------------
class LoginRequest(CamelModel):
    email: EmailStr = Field(examples=["admin@muni.uade.edu.ar"])
    password: str = Field(min_length=1, examples=["Admin123!"])


class RefreshRequest(CamelModel):
    refresh_token: str


class ClientCredentialsRequest(CamelModel):
    """Autenticacion modulo-a-modulo, para publicar eventos en el hub."""

    client_id: str = Field(examples=["atencion-ciudadana"])
    client_secret: str


class TokenResponse(CamelModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int = Field(description="Segundos hasta que el access token expire")
    refresh_token: str | None = None


class IntrospectRequest(CamelModel):
    token: str


class IntrospectResponse(CamelModel):
    """Validacion sincronica de un token.

    Los modulos deberian validar con el JWKS (offline). Este endpoint existe para
    el caso que el enunciado habilita explicitamente: "validar una identidad"
    cuando se necesita la respuesta para continuar la operacion.
    """

    active: bool
    subject: str | None = None
    kind: str | None = None
    email: str | None = None
    module: str | None = None
    roles: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    scopes: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None
    reason: str | None = None


# ----------------------------------------------------------------------
# Usuarios, roles y permisos
# ----------------------------------------------------------------------
class PermissionResponse(CamelModel):
    id: uuid.UUID
    code: str
    resource: str
    action: str
    description: str

    @classmethod
    def of(cls, permission: Permission) -> PermissionResponse:
        return cls.model_validate(permission)


class RoleResponse(CamelModel):
    id: uuid.UUID
    code: str
    name: str
    description: str
    is_system: bool
    permissions: list[str]

    @classmethod
    def of(cls, role: Role) -> RoleResponse:
        return cls(
            id=role.id,
            code=role.code,
            name=role.name,
            description=role.description,
            is_system=role.is_system,
            permissions=sorted(perm.code for perm in role.permissions),
        )


class RoleCreate(CamelModel):
    code: str = Field(min_length=2, max_length=60, examples=["OPERADOR_TECNICO"])
    name: str = Field(min_length=2, max_length=120)
    description: str = ""
    permission_codes: list[str] = Field(default_factory=list)


class RoleUpdate(CamelModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = None
    permission_codes: list[str] | None = None


class UserResponse(CamelModel):
    id: uuid.UUID
    email: str
    full_name: str
    document_number: str | None
    status: UserStatus
    source_module: str
    external_id: str | None
    has_password: bool
    last_login_at: datetime | None
    roles: list[str]
    permissions: list[str]
    created_at: datetime

    @classmethod
    def of(cls, user: User) -> UserResponse:
        return cls(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            document_number=user.document_number,
            status=user.status,
            source_module=user.source_module,
            external_id=user.external_id,
            has_password=user.password_hash is not None,
            last_login_at=user.last_login_at,
            roles=user.role_codes,
            permissions=user.permission_codes,
            created_at=user.created_at,
        )


class UserCreate(CamelModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=180)
    password: str | None = Field(
        default=None,
        min_length=8,
        description="Opcional: sin contrasena la cuenta existe pero no puede iniciar sesion.",
    )
    document_number: str | None = Field(default=None, max_length=20)
    role_codes: list[str] = Field(default_factory=list)
    status: UserStatus = UserStatus.ACTIVE


class UserUpdate(CamelModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=180)
    document_number: str | None = Field(default=None, max_length=20)
    status: UserStatus | None = None
    role_codes: list[str] | None = None


class PasswordUpdate(CamelModel):
    password: str = Field(min_length=8)


class ApiClientResponse(CamelModel):
    id: uuid.UUID
    client_id: str
    module_name: str
    description: str
    scopes: list[str]
    active: bool
    last_used_at: datetime | None
    created_at: datetime

    @classmethod
    def of(cls, client: ApiClient) -> ApiClientResponse:
        return cls.model_validate(client)


class ApiClientCreate(CamelModel):
    client_id: str = Field(min_length=2, max_length=80, examples=["obras"])
    module_name: str = Field(min_length=2, max_length=60, examples=["obras"])
    description: str = ""
    scopes: list[str] | None = Field(
        default=None,
        description="Por defecto: events:publish y module:<nombre>.",
    )


class MeResponse(CamelModel):
    """Identidad del llamador. El FE la usa para armar el menu segun permisos."""

    subject: str
    kind: str
    email: str | None
    name: str | None
    module: str | None
    roles: list[str]
    permissions: list[str]
    scopes: list[str]
