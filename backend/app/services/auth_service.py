"""Autenticacion. Dos caminos, a proposito separados.

* **Una persona** entra al dashboard con su email y contrasena. El token dice
  quien es, asi la auditoria puede registrar a la persona y no al equipo.

* **El backend de un modulo** obtiene un token con el secret del modulo, para
  publicar eventos. Ese secret vive en la config del equipo, no lo sabe nadie.

Estan separados porque hacen cosas distintas y se rotan distinto: cambiar la
contrasena de alguien no toca el backend desplegado, y rotar el secret de
maquina no le corta el acceso al dashboard a nadie.

El Core no es el proveedor de identidad de la plataforma: no sabe de ciudadanos
ni de usuarios finales del municipio. El unico privilegio que existe es el
`is_admin` del modulo (el equipo 9, que ve el trafico de todos).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import structlog

from app.core.database import utcnow
from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.metrics import AUTH_FAILURES
from app.core.security import (
    create_access_token,
    generate_opaque_token,
    hash_opaque_token,
    verify_password,
)
from app.models.registry import ModuleAccount
from app.models.users import User
from app.repositories.registry_repository import ModuleRepository, UserRepository

logger = structlog.get_logger(__name__)

MAX_FAILED_ATTEMPTS = 5
"""Intentos fallidos consecutivos antes de desactivar la cuenta."""

KIND_USER = "user"
KIND_MODULE = "module"


@dataclass
class Token:
    access_token: str
    expires_at: datetime
    module: str
    display_name: str
    is_admin: bool
    kind: str
    actor: str
    token_type: str = "Bearer"

    @property
    def expires_in(self) -> int:
        return max(int((self.expires_at - utcnow()).total_seconds()), 0)


class AuthService:
    def __init__(self, *, user_repo: UserRepository, module_repo: ModuleRepository) -> None:
        self.user_repo = user_repo
        self.module_repo = module_repo

    # ------------------------------------------------------------------
    # Personas: el dashboard
    # ------------------------------------------------------------------
    async def login(self, *, email: str, password: str) -> tuple[User, Token]:
        user = await self.user_repo.get_by_email(email)

        # Mismo mensaje para cuenta inexistente y contrasena incorrecta: no se
        # filtra si el email existe.
        if user is None:
            logger.info("login_failed", email=email, reason="not_found")
            AUTH_FAILURES.labels(
                auth_type="user",
                reason="invalid_credentials",
            ).inc()
            raise UnauthorizedError("Credenciales invalidas.", code="INVALID_CREDENTIALS")

        if not verify_password(password, user.password_hash):
            await self.user_repo.record_failed_login(user, max_attempts=MAX_FAILED_ATTEMPTS)
            if not user.active:
                logger.warning("user_deactivated_by_attempts", email=user.email)
            logger.info(
                "login_failed",
                email=email,
                reason="bad_password",
                attempts=user.failed_login_attempts,
            )
            AUTH_FAILURES.labels(
                auth_type="user",
                reason="invalid_credentials",
            ).inc()
            raise UnauthorizedError("Credenciales invalidas.", code="INVALID_CREDENTIALS")

        if not user.active:
            raise ForbiddenError(
                "La cuenta esta desactivada. Pedile a alguien de tu equipo que la reactive.",
                code="ACCOUNT_INACTIVE",
            )

        if not user.module.active:
            raise ForbiddenError(
                f"El modulo '{user.module.name}' esta dado de baja.",
                code="MODULE_INACTIVE",
            )

        user.failed_login_attempts = 0
        user.last_login_at = utcnow()
        user.module.last_login_at = utcnow()

        access_token, expires_at = create_access_token(
            subject=f"user:{user.id}",
            extra={
                "kind": KIND_USER,
                "module": user.module.name,
                "displayName": user.module.display_name,
                "isAdmin": user.module.is_admin,
                "email": user.email,
                "name": user.full_name,
            },
        )
        logger.info("login_ok", email=user.email, module=user.module.name)
        return user, Token(
            access_token=access_token,
            expires_at=expires_at,
            module=user.module.name,
            display_name=user.module.display_name,
            is_admin=user.module.is_admin,
            kind=KIND_USER,
            actor=user.email,
        )

    # ------------------------------------------------------------------
    # Modulos: publicar eventos
    # ------------------------------------------------------------------
    async def issue_module_token(self, *, module_name: str, secret: str) -> Token:
        module = await self.module_repo.get_by_name(module_name)

        if module is None or not module.secret_hash:
            logger.info("module_auth_failed", module=module_name, reason="not_found")
            AUTH_FAILURES.labels(
                auth_type="service",
                reason="invalid_client",
            ).inc()
            raise UnauthorizedError("Credenciales de modulo invalidas.", code="INVALID_CREDENTIALS")

        if hash_opaque_token(secret) != module.secret_hash:
            logger.info("module_auth_failed", module=module_name, reason="bad_secret")
            AUTH_FAILURES.labels(
                auth_type="service",
                reason="invalid_client",
            ).inc()
            raise UnauthorizedError("Credenciales de modulo invalidas.", code="INVALID_CREDENTIALS")

        if not module.active:
            raise ForbiddenError(
                f"El modulo '{module.name}' esta dado de baja.", code="MODULE_INACTIVE"
            )

        access_token, expires_at = create_access_token(
            subject=f"module:{module.name}",
            extra={
                "kind": KIND_MODULE,
                "module": module.name,
                "displayName": module.display_name,
                "isAdmin": module.is_admin,
            },
        )
        logger.info("module_token_issued", module=module.name)
        return Token(
            access_token=access_token,
            expires_at=expires_at,
            module=module.name,
            display_name=module.display_name,
            is_admin=module.is_admin,
            kind=KIND_MODULE,
            actor=f"module:{module.name}",
        )

    def rotate_module_secret(self, module: ModuleAccount) -> str:
        """Genera un secret de maquina nuevo.

        Solo afecta a la publicacion de eventos: el acceso de las personas al
        dashboard no se toca.
        """
        secret = generate_opaque_token()
        module.secret_hash = hash_opaque_token(secret)
        logger.info("module_secret_rotated", module=module.name)
        return secret
