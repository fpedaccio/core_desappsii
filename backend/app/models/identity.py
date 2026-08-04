"""Identidad y acceso: usuarios, roles, permisos y cuentas de servicio.

El Core es dueno de la *credencial* y del *permiso*. No es dueno del dato
personal del ciudadano: eso vive en el modulo Ciudadanos. Cuando llega un
`CiudadanoRegistrado`, el Core provisiona la cuenta y guarda solo el
identificador externo para poder correlacionar (reglas 5 y 8 del enunciado).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String, Table, UniqueConstraint
from sqlalchemy import Column as SAColumn
from sqlalchemy import Uuid as SAUuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, JSONType, TimestampMixin, TimestampTZ


class UserStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    BLOCKED = "BLOCKED"


user_roles = Table(
    "user_roles",
    Base.metadata,
    SAColumn("user_id", SAUuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    SAColumn("role_id", SAUuid, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)

role_permissions = Table(
    "role_permissions",
    Base.metadata,
    SAColumn("role_id", SAUuid, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    SAColumn(
        "permission_id",
        SAUuid,
        ForeignKey("permissions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Permission(Base, TimestampMixin):
    """Permiso fino, con forma `recurso:accion` (ej. `dlq:retry`)."""

    __tablename__ = "permissions"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    resource: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(String(255), default="")

    roles: Mapped[list[Role]] = relationship(
        secondary=role_permissions, back_populates="permissions"
    )


class Role(Base, TimestampMixin):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(255), default="")
    # Los roles de sistema no se pueden borrar desde el panel: si se borrara
    # ADMIN_SISTEMA nadie podria volver a administrar la plataforma.
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)

    permissions: Mapped[list[Permission]] = relationship(
        secondary=role_permissions, back_populates="roles", lazy="selectin"
    )
    users: Mapped[list[User]] = relationship(secondary=user_roles, back_populates="roles")


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    # Nulo mientras la cuenta fue provisionada por evento y el ciudadano todavia
    # no definio su contrasena.
    password_hash: Mapped[str | None] = mapped_column(String(255), default=None)
    full_name: Mapped[str] = mapped_column(String(180))
    document_number: Mapped[str | None] = mapped_column(String(20), index=True, default=None)
    status: Mapped[UserStatus] = mapped_column(String(20), default=UserStatus.ACTIVE)

    # Trazabilidad del origen: que modulo provisiono la cuenta y con que id.
    source_module: Mapped[str] = mapped_column(String(60), default="core")
    external_id: Mapped[str | None] = mapped_column(String(80), index=True, default=None)

    last_login_at: Mapped[datetime | None] = mapped_column(TimestampTZ, default=None)
    failed_login_attempts: Mapped[int] = mapped_column(default=0)

    roles: Mapped[list[Role]] = relationship(
        secondary=user_roles, back_populates="users", lazy="selectin"
    )
    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("source_module", "external_id", name="uq_users_external"),)

    @property
    def role_codes(self) -> list[str]:
        return sorted(role.code for role in self.roles)

    @property
    def permission_codes(self) -> list[str]:
        return sorted({perm.code for role in self.roles for perm in role.permissions})

    @property
    def is_active(self) -> bool:
        return self.status == UserStatus.ACTIVE


class RefreshToken(Base, TimestampMixin):
    """Refresh token rotativo. En la base solo vive el hash."""

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        SAUuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(TimestampTZ)
    revoked_at: Mapped[datetime | None] = mapped_column(TimestampTZ, default=None)
    # Al rotar se apunta al reemplazo: permite detectar reuso de un token viejo.
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(SAUuid, default=None)
    user_agent: Mapped[str | None] = mapped_column(String(255), default=None)

    user: Mapped[User] = relationship(back_populates="refresh_tokens")


class ApiClient(Base, TimestampMixin):
    """Cuenta de servicio de un modulo (flujo client_credentials).

    Es como los otros 8 modulos se autentican contra el Core para publicar
    eventos, sin usar credenciales de una persona.
    """

    __tablename__ = "api_clients"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    client_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    client_secret_hash: Mapped[str] = mapped_column(String(64))
    module_name: Mapped[str] = mapped_column(String(60), index=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    scopes: Mapped[list[str]] = mapped_column(JSONType, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used_at: Mapped[datetime | None] = mapped_column(TimestampTZ, default=None)
