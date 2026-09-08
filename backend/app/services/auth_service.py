"""Autenticacion de modulos.

El Core **no** es el proveedor de identidad de la plataforma: no administra
ciudadanos, ni usuarios finales, ni roles de negocio. Solo sabe de los 9 modulos.

Cada modulo tiene una credencial (`name` + `secret`) que sirve para dos cosas:
entrar al dashboard y publicar eventos. El unico privilegio que existe es
`is_admin`, que tiene el equipo 9: ve el trafico de todos los modulos en vez de
solo el propio.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import structlog

from app.core.database import utcnow
from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.security import (
    create_access_token,
    generate_opaque_token,
    hash_opaque_token,
)
from app.models.registry import ModuleAccount
from app.repositories.registry_repository import ModuleRepository

logger = structlog.get_logger(__name__)


@dataclass
class TokenPair:
    access_token: str
    expires_at: datetime
    module_name: str
    is_admin: bool
    token_type: str = "Bearer"

    @property
    def expires_in(self) -> int:
        return max(int((self.expires_at - utcnow()).total_seconds()), 0)


class AuthService:
    def __init__(self, *, module_repo: ModuleRepository) -> None:
        self.module_repo = module_repo

    async def login(self, *, module_name: str, secret: str) -> tuple[ModuleAccount, TokenPair]:
        module = await self.module_repo.get_by_name(module_name)

        # Mismo mensaje para modulo inexistente y secret incorrecto: no se
        # filtra cual de los dos falló.
        if module is None or not module.secret_hash:
            logger.info("login_failed", module=module_name, reason="not_found")
            raise UnauthorizedError("Credenciales invalidas.", code="INVALID_CREDENTIALS")

        if hash_opaque_token(secret) != module.secret_hash:
            logger.info("login_failed", module=module_name, reason="bad_secret")
            raise UnauthorizedError("Credenciales invalidas.", code="INVALID_CREDENTIALS")

        if not module.active:
            raise ForbiddenError(
                f"El modulo '{module.name}' esta dado de baja.", code="MODULE_INACTIVE"
            )

        module.last_login_at = utcnow()
        tokens = self._issue(module)
        logger.info("login_ok", module=module.name, is_admin=module.is_admin)
        return module, tokens

    def _issue(self, module: ModuleAccount) -> TokenPair:
        access_token, expires_at = create_access_token(
            subject=f"module:{module.name}",
            extra={
                "module": module.name,
                "displayName": module.display_name,
                "isAdmin": module.is_admin,
            },
        )
        return TokenPair(
            access_token=access_token,
            expires_at=expires_at,
            module_name=module.name,
            is_admin=module.is_admin,
        )

    def rotate_secret(self, module: ModuleAccount) -> str:
        """Genera un secret nuevo. Devuelve el valor en claro **una sola vez**."""
        secret = generate_opaque_token()
        module.secret_hash = hash_opaque_token(secret)
        logger.info("secret_rotated", module=module.name)
        return secret
