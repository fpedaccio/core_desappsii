"""Acceso a datos de identidad y acceso."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app.models.identity import (
    ApiClient,
    Permission,
    RefreshToken,
    Role,
    User,
    UserStatus,
)
from app.repositories.base import BaseRepository, Page


class UserRepository(BaseRepository[User]):
    model = User

    def _with_roles(self):
        return select(User).options(selectinload(User.roles).selectinload(Role.permissions))

    async def get_with_roles(self, user_id: uuid.UUID) -> User | None:
        stmt = self._with_roles().where(User.id == user_id)
        return (await self.session.execute(stmt)).scalars().first()

    async def get_by_email(self, email: str) -> User | None:
        stmt = self._with_roles().where(User.email == email.lower().strip())
        return (await self.session.execute(stmt)).scalars().first()

    async def get_by_external(self, source_module: str, external_id: str) -> User | None:
        stmt = self._with_roles().where(
            User.source_module == source_module, User.external_id == external_id
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def get_by_document(self, document_number: str) -> User | None:
        stmt = self._with_roles().where(User.document_number == document_number)
        return (await self.session.execute(stmt)).scalars().first()

    async def search(
        self,
        *,
        query: str | None = None,
        status: UserStatus | None = None,
        role_code: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> Page[User]:
        stmt = self._with_roles()
        if query:
            pattern = f"%{query.lower().strip()}%"
            stmt = stmt.where(
                or_(
                    User.email.ilike(pattern),
                    User.full_name.ilike(pattern),
                    User.document_number.ilike(pattern),
                )
            )
        if status:
            stmt = stmt.where(User.status == status)
        if role_code:
            stmt = stmt.join(User.roles).where(Role.code == role_code)
        return await self.paginate(stmt.order_by(User.created_at.desc()), page=page, size=size)

    async def emails_for_role(self, role_code: str) -> list[str]:
        """Destinatarios de un aviso interno dirigido a un rol."""
        stmt = (
            select(User.email)
            .join(User.roles)
            .where(Role.code == role_code, User.status == UserStatus.ACTIVE)
        )
        return list((await self.session.execute(stmt)).scalars().all())


class RoleRepository(BaseRepository[Role]):
    model = Role

    def _with_permissions(self):
        return select(Role).options(selectinload(Role.permissions))

    async def get_with_permissions(self, role_id: uuid.UUID) -> Role | None:
        stmt = self._with_permissions().where(Role.id == role_id)
        return (await self.session.execute(stmt)).scalars().first()

    async def get_by_code(self, code: str) -> Role | None:
        stmt = self._with_permissions().where(Role.code == code)
        return (await self.session.execute(stmt)).scalars().first()

    async def list_by_codes(self, codes: list[str]) -> list[Role]:
        if not codes:
            return []
        stmt = self._with_permissions().where(Role.code.in_(codes))
        return list((await self.session.execute(stmt)).scalars().unique().all())

    async def list_ordered(self) -> list[Role]:
        stmt = self._with_permissions().order_by(Role.code)
        return list((await self.session.execute(stmt)).scalars().unique().all())


class PermissionRepository(BaseRepository[Permission]):
    model = Permission

    async def get_by_code(self, code: str) -> Permission | None:
        return await self.find_one(code=code)

    async def list_by_codes(self, codes: list[str]) -> list[Permission]:
        if not codes:
            return []
        stmt = select(Permission).where(Permission.code.in_(codes))
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_ordered(self) -> list[Permission]:
        stmt = select(Permission).order_by(Permission.resource, Permission.action)
        return list((await self.session.execute(stmt)).scalars().all())


class RefreshTokenRepository(BaseRepository[RefreshToken]):
    model = RefreshToken

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        return await self.find_one(token_hash=token_hash)

    async def revoke_all_for_user(self, user_id: uuid.UUID, *, at: datetime) -> int:
        """Cierra todas las sesiones del usuario (cambio de password, bloqueo)."""
        stmt = select(RefreshToken).where(
            RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
        )
        tokens = list((await self.session.execute(stmt)).scalars().all())
        for token in tokens:
            token.revoked_at = at
        return len(tokens)


class ApiClientRepository(BaseRepository[ApiClient]):
    model = ApiClient

    async def get_by_client_id(self, client_id: str) -> ApiClient | None:
        return await self.find_one(client_id=client_id)

    async def list_ordered(self) -> list[ApiClient]:
        stmt = select(ApiClient).order_by(ApiClient.module_name)
        return list((await self.session.execute(stmt)).scalars().all())
