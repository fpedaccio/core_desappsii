"""Administracion de usuarios, roles, permisos y cuentas de servicio."""

from __future__ import annotations

import uuid
from typing import Any

import structlog

from app.core.database import utcnow
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.security import hash_password
from app.models.identity import ApiClient, Permission, Role, User, UserStatus
from app.repositories.base import Page
from app.repositories.identity_repository import (
    ApiClientRepository,
    PermissionRepository,
    RefreshTokenRepository,
    RoleRepository,
    UserRepository,
)
from app.services.audit_service import AuditService

logger = structlog.get_logger(__name__)

MIN_PASSWORD_LENGTH = 8


class UserService:
    def __init__(
        self,
        *,
        user_repo: UserRepository,
        role_repo: RoleRepository,
        permission_repo: PermissionRepository,
        refresh_repo: RefreshTokenRepository,
        audit: AuditService,
    ) -> None:
        self.user_repo = user_repo
        self.role_repo = role_repo
        self.permission_repo = permission_repo
        self.refresh_repo = refresh_repo
        self.audit = audit

    # ------------------------------------------------------------------
    # Usuarios
    # ------------------------------------------------------------------
    async def search(
        self,
        *,
        query: str | None = None,
        status: UserStatus | None = None,
        role_code: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> Page[User]:
        return await self.user_repo.search(
            query=query, status=status, role_code=role_code, page=page, size=size
        )

    async def get(self, user_id: uuid.UUID) -> User:
        user = await self.user_repo.get_with_roles(user_id)
        if user is None:
            raise NotFoundError(f"No existe el usuario {user_id}.")
        return user

    async def create(
        self,
        *,
        email: str,
        full_name: str,
        password: str | None = None,
        document_number: str | None = None,
        role_codes: list[str] | None = None,
        status: UserStatus = UserStatus.ACTIVE,
    ) -> User:
        normalized_email = _normalize_email(email)
        if await self.user_repo.get_by_email(normalized_email) is not None:
            raise ConflictError(f"Ya existe un usuario con el email {normalized_email}.")

        if password is not None:
            _assert_password_strength(password)

        user = User(
            email=normalized_email,
            full_name=full_name.strip(),
            password_hash=hash_password(password) if password else None,
            document_number=document_number,
            status=status,
            source_module="core",
        )
        user.roles = await self._resolve_roles(role_codes or [])
        self.user_repo.add(user)
        await self.user_repo.flush()

        self.audit.record(
            action="USER_CREATED",
            entity_type="User",
            entity_id=str(user.id),
            summary=f"Usuario {user.email} creado con roles {user.role_codes}.",
        )
        return user

    async def update(
        self,
        user_id: uuid.UUID,
        *,
        full_name: str | None = None,
        document_number: str | None = None,
        status: UserStatus | None = None,
        role_codes: list[str] | None = None,
    ) -> User:
        user = await self.get(user_id)
        changes: dict[str, Any] = {}

        if full_name is not None and full_name.strip() != user.full_name:
            changes["fullName"] = {"before": user.full_name, "after": full_name.strip()}
            user.full_name = full_name.strip()

        if document_number is not None and document_number != user.document_number:
            changes["documentNumber"] = {
                "before": user.document_number,
                "after": document_number,
            }
            user.document_number = document_number

        if status is not None and status != user.status:
            changes["status"] = {"before": str(user.status), "after": str(status)}
            user.status = status
            if status != UserStatus.ACTIVE:
                # Al desactivar o bloquear se cierran las sesiones abiertas: si no,
                # el refresh token seguiria emitiendo access tokens validos.
                revoked = await self.refresh_repo.revoke_all_for_user(user.id, at=utcnow())
                changes["sessionsRevoked"] = revoked
            else:
                user.failed_login_attempts = 0

        if role_codes is not None:
            new_roles = await self._resolve_roles(role_codes)
            if sorted(role.code for role in new_roles) != user.role_codes:
                changes["roles"] = {
                    "before": user.role_codes,
                    "after": sorted(role.code for role in new_roles),
                }
                user.roles = new_roles

        if changes:
            self.audit.record(
                action="USER_UPDATED",
                entity_type="User",
                entity_id=str(user.id),
                summary=f"Usuario {user.email} actualizado.",
                changes=changes,
            )
        return user

    async def set_password(self, user_id: uuid.UUID, *, password: str) -> User:
        _assert_password_strength(password)
        user = await self.get(user_id)
        user.password_hash = hash_password(password)
        user.failed_login_attempts = 0
        revoked = await self.refresh_repo.revoke_all_for_user(user.id, at=utcnow())

        self.audit.record(
            action="USER_PASSWORD_CHANGED",
            entity_type="User",
            entity_id=str(user.id),
            summary=f"Contrasena de {user.email} actualizada; {revoked} sesion(es) cerradas.",
        )
        return user

    async def delete(self, user_id: uuid.UUID) -> None:
        user = await self.get(user_id)
        await self.user_repo.delete(user)
        self.audit.record(
            action="USER_DELETED",
            entity_type="User",
            entity_id=str(user_id),
            summary=f"Usuario {user.email} eliminado.",
        )

    async def _resolve_roles(self, role_codes: list[str]) -> list[Role]:
        if not role_codes:
            return []
        roles = await self.role_repo.list_by_codes(role_codes)
        missing = set(role_codes) - {role.code for role in roles}
        if missing:
            raise ValidationError(f"Roles inexistentes: {sorted(missing)}.")
        return roles

    # ------------------------------------------------------------------
    # Provision por evento (integracion con el modulo Ciudadanos)
    # ------------------------------------------------------------------
    async def provision_from_citizen_event(
        self,
        *,
        external_id: str,
        email: str | None,
        full_name: str,
        document_number: str | None = None,
        source_module: str = "ciudadanos",
        role_code: str = "CIUDADANO",
    ) -> tuple[User, bool]:
        """Crea o actualiza la cuenta de acceso de un ciudadano.

        El enunciado pide que el ciudadano se registre siempre en el modulo
        Ciudadanos para despues poder entrar a los demas modulos, pero los
        usuarios y permisos los administra el Core. Se resuelve asi: Ciudadanos
        publica `CiudadanoRegistrado` y el Core provisiona la credencial.

        El Core guarda **solo** lo necesario para autenticar y el identificador
        externo con el que correlacionar. El dato personal sigue siendo de
        Ciudadanos: nunca lo modificamos ahi (reglas 5 y 8).

        Devuelve el usuario y si fue creado en esta llamada.
        """
        existing = await self.user_repo.get_by_external(source_module, external_id)

        if existing is None and email:
            # Segunda oportunidad: puede haber sido creado a mano antes de que
            # llegara el evento. Se vincula en vez de duplicar la cuenta.
            existing = await self.user_repo.get_by_email(_normalize_email(email))
            if existing is not None and existing.external_id is None:
                existing.source_module = source_module
                existing.external_id = external_id

        if existing is not None:
            existing.full_name = full_name.strip() or existing.full_name
            if document_number:
                existing.document_number = document_number
            if email:
                existing.email = _normalize_email(email)
            logger.info(
                "citizen_account_updated", external_id=external_id, email=existing.email
            )
            return existing, False

        user = User(
            # Sin email en el evento se arma un identificador local: la cuenta
            # existe y puede recibir permisos, aunque todavia no pueda loguearse.
            email=_normalize_email(email) if email else f"{external_id}@sin-email.local",
            full_name=full_name.strip() or f"Ciudadano {external_id}",
            document_number=document_number,
            # Sin contrasena hasta que el ciudadano la defina.
            password_hash=None,
            status=UserStatus.ACTIVE,
            source_module=source_module,
            external_id=external_id,
        )
        role = await self.role_repo.get_by_code(role_code)
        if role is not None:
            user.roles = [role]
        self.user_repo.add(user)
        await self.user_repo.flush()

        self.audit.record(
            action="USER_PROVISIONED_BY_EVENT",
            entity_type="User",
            entity_id=str(user.id),
            actor=f"module:{source_module}",
            summary=(
                f"Cuenta provisionada para el ciudadano externo {external_id} "
                f"({user.email})."
            ),
        )
        logger.info("citizen_account_provisioned", external_id=external_id, email=user.email)
        return user, True

    # ------------------------------------------------------------------
    # Roles y permisos
    # ------------------------------------------------------------------
    async def list_roles(self) -> list[Role]:
        return await self.role_repo.list_ordered()

    async def list_permissions(self) -> list[Permission]:
        return await self.permission_repo.list_ordered()

    async def create_role(
        self, *, code: str, name: str, description: str = "", permission_codes: list[str]
    ) -> Role:
        normalized = code.strip().upper()
        if await self.role_repo.get_by_code(normalized) is not None:
            raise ConflictError(f"Ya existe el rol {normalized}.")

        role = Role(code=normalized, name=name.strip(), description=description)
        role.permissions = await self._resolve_permissions(permission_codes)
        self.role_repo.add(role)
        await self.role_repo.flush()

        self.audit.record(
            action="ROLE_CREATED",
            entity_type="Role",
            entity_id=str(role.id),
            summary=f"Rol {role.code} creado con {len(role.permissions)} permiso(s).",
        )
        return role

    async def update_role(
        self,
        role_id: uuid.UUID,
        *,
        name: str | None = None,
        description: str | None = None,
        permission_codes: list[str] | None = None,
    ) -> Role:
        role = await self.role_repo.get_with_permissions(role_id)
        if role is None:
            raise NotFoundError(f"No existe el rol {role_id}.")

        changes: dict[str, Any] = {}
        if name is not None:
            role.name = name.strip()
        if description is not None:
            role.description = description
        if permission_codes is not None:
            before = sorted(perm.code for perm in role.permissions)
            role.permissions = await self._resolve_permissions(permission_codes)
            after = sorted(perm.code for perm in role.permissions)
            if before != after:
                changes["permissions"] = {"before": before, "after": after}

        self.audit.record(
            action="ROLE_UPDATED",
            entity_type="Role",
            entity_id=str(role.id),
            summary=f"Rol {role.code} actualizado.",
            changes=changes or None,
        )
        return role

    async def delete_role(self, role_id: uuid.UUID) -> None:
        role = await self.role_repo.get_with_permissions(role_id)
        if role is None:
            raise NotFoundError(f"No existe el rol {role_id}.")
        if role.is_system:
            raise ConflictError(
                f"El rol {role.code} es de sistema y no se puede eliminar: sin el, "
                "la plataforma quedaria sin forma de administrarse."
            )
        await self.role_repo.delete(role)
        self.audit.record(
            action="ROLE_DELETED",
            entity_type="Role",
            entity_id=str(role_id),
            summary=f"Rol {role.code} eliminado.",
        )

    async def _resolve_permissions(self, permission_codes: list[str]) -> list[Permission]:
        if not permission_codes:
            return []
        permissions = await self.permission_repo.list_by_codes(permission_codes)
        missing = set(permission_codes) - {perm.code for perm in permissions}
        if missing:
            raise ValidationError(f"Permisos inexistentes: {sorted(missing)}.")
        return permissions


class ApiClientService:
    """Cuentas de servicio con las que los otros modulos se autentican."""

    def __init__(self, *, client_repo: ApiClientRepository, audit: AuditService) -> None:
        self.client_repo = client_repo
        self.audit = audit

    async def list_clients(self) -> list[ApiClient]:
        return await self.client_repo.list_ordered()

    async def create(
        self,
        *,
        client_id: str,
        module_name: str,
        description: str = "",
        scopes: list[str] | None = None,
    ) -> tuple[ApiClient, str]:
        """Crea la cuenta y devuelve el secret en claro **una unica vez**."""
        from app.core.security import generate_opaque_token, hash_opaque_token

        normalized = client_id.strip().lower()
        if await self.client_repo.get_by_client_id(normalized) is not None:
            raise ConflictError(f"Ya existe el cliente {normalized}.")

        secret = generate_opaque_token()
        client = ApiClient(
            client_id=normalized,
            client_secret_hash=hash_opaque_token(secret),
            module_name=module_name.strip().lower(),
            description=description,
            scopes=scopes or [f"events:publish", f"module:{module_name.strip().lower()}"],
        )
        self.client_repo.add(client)
        await self.client_repo.flush()

        self.audit.record(
            action="API_CLIENT_CREATED",
            entity_type="ApiClient",
            entity_id=str(client.id),
            summary=f"Cuenta de servicio {client.client_id} creada para {client.module_name}.",
        )
        return client, secret

    async def rotate_secret(self, client_id_pk: uuid.UUID) -> tuple[ApiClient, str]:
        from app.core.security import generate_opaque_token, hash_opaque_token

        client = await self.client_repo.get_required(client_id_pk)
        secret = generate_opaque_token()
        client.client_secret_hash = hash_opaque_token(secret)

        self.audit.record(
            action="API_CLIENT_SECRET_ROTATED",
            entity_type="ApiClient",
            entity_id=str(client.id),
            summary=f"Secret rotado para {client.client_id}.",
        )
        return client, secret

    async def set_active(self, client_id_pk: uuid.UUID, *, active: bool) -> ApiClient:
        client = await self.client_repo.get_required(client_id_pk)
        client.active = active
        self.audit.record(
            action="API_CLIENT_TOGGLED",
            entity_type="ApiClient",
            entity_id=str(client.id),
            summary=f"Cuenta {client.client_id} {'activada' if active else 'desactivada'}.",
        )
        return client


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _assert_password_strength(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationError(
            f"La contrasena debe tener al menos {MIN_PASSWORD_LENGTH} caracteres."
        )
    if password.isdigit() or password.isalpha():
        raise ValidationError("La contrasena debe combinar letras y numeros.")
