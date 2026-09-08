"""Personas del dashboard.

Cada equipo administra las cuentas de sus propios integrantes; el equipo 9 puede
administrar las de cualquiera. No hay roles: lo que una persona ve sale de su
modulo.
"""

from __future__ import annotations

import uuid

import structlog

from app.core.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.core.security import hash_password
from app.models.users import User
from app.repositories.registry_repository import ModuleRepository, UserRepository

logger = structlog.get_logger(__name__)

MIN_PASSWORD_LENGTH = 8


class UserService:
    def __init__(self, *, user_repo: UserRepository, module_repo: ModuleRepository) -> None:
        self.user_repo = user_repo
        self.module_repo = module_repo

    async def list_users(self, *, actor_module: str, actor_is_admin: bool) -> list[User]:
        if actor_is_admin:
            return await self.user_repo.list_all()
        module = await self._module(actor_module)
        return await self.user_repo.list_for_module(module.id)

    async def create(
        self,
        *,
        email: str,
        password: str,
        full_name: str,
        module_name: str | None,
        actor_module: str,
        actor_is_admin: bool,
    ) -> User:
        target_module = (module_name or actor_module).strip().lower()
        self._assert_can_act_on(target_module, actor_module, actor_is_admin)
        _assert_password_strength(password)

        normalized_email = email.strip().lower()
        if await self.user_repo.get_by_email(normalized_email) is not None:
            raise ConflictError(f"Ya existe una cuenta con el email {normalized_email}.")

        module = await self._module(target_module)
        user = User(
            email=normalized_email,
            password_hash=hash_password(password),
            full_name=full_name.strip(),
            module_id=module.id,
            active=True,
            failed_login_attempts=0,
        )
        # Se asigna la relacion para no depender de un lazy load al serializar.
        user.module = module
        self.user_repo.add(user)
        await self.user_repo.flush()

        logger.info("user_created", email=normalized_email, module=module.name)
        return user

    async def update(
        self,
        user_id: uuid.UUID,
        *,
        full_name: str | None = None,
        active: bool | None = None,
        actor_module: str,
        actor_is_admin: bool,
    ) -> User:
        user = await self._user(user_id)
        self._assert_can_act_on(user.module.name, actor_module, actor_is_admin)

        if full_name is not None:
            user.full_name = full_name.strip()

        if active is not None and active != user.active:
            if not active:
                await self._assert_not_last_active(user)
            user.active = active
            if active:
                # Reactivar limpia el bloqueo por intentos fallidos.
                user.failed_login_attempts = 0

        return user

    async def set_password(
        self,
        user_id: uuid.UUID,
        *,
        password: str,
        actor_module: str,
        actor_is_admin: bool,
    ) -> User:
        _assert_password_strength(password)
        user = await self._user(user_id)
        self._assert_can_act_on(user.module.name, actor_module, actor_is_admin)

        user.password_hash = hash_password(password)
        user.failed_login_attempts = 0
        logger.info("user_password_changed", email=user.email)
        return user

    async def delete(self, user_id: uuid.UUID, *, actor_module: str, actor_is_admin: bool) -> None:
        user = await self._user(user_id)
        self._assert_can_act_on(user.module.name, actor_module, actor_is_admin)
        await self._assert_not_last_active(user)
        await self.user_repo.delete(user)
        logger.info("user_deleted", email=user.email)

    # ------------------------------------------------------------------
    async def _user(self, user_id: uuid.UUID) -> User:
        user = await self.user_repo.get_loaded(user_id)
        if user is None:
            raise NotFoundError(f"No existe la cuenta {user_id}.")
        return user

    async def _module(self, name: str):
        module = await self.module_repo.get_by_name(name)
        if module is None:
            raise NotFoundError(f"No existe el modulo '{name}'.")
        return module

    async def _assert_not_last_active(self, user: User) -> None:
        """Evita que un equipo se quede sin ninguna cuenta con la que entrar."""
        if not user.active:
            return
        if await self.user_repo.count_active_in_module(user.module_id) <= 1:
            raise ConflictError(
                f"Es la unica cuenta activa de '{user.module.name}'. Si se da de "
                "baja, el equipo no puede volver a entrar al dashboard. Crea otra "
                "cuenta primero."
            )

    @staticmethod
    def _assert_can_act_on(module_name: str, actor_module: str, actor_is_admin: bool) -> None:
        if actor_is_admin:
            return
        if module_name.strip().lower() != actor_module.strip().lower():
            raise ForbiddenError(
                f"Estas autenticado en '{actor_module}' y solo podes administrar las "
                f"cuentas de tu propio equipo, no las de '{module_name}'."
            )


def _assert_password_strength(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationError(
            f"La contrasena debe tener al menos {MIN_PASSWORD_LENGTH} caracteres."
        )
    if password.isdigit() or password.isalpha():
        raise ValidationError("La contrasena debe combinar letras y numeros.")
