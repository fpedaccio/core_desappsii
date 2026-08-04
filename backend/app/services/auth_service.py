"""Autenticacion: login de personas, tokens de servicio y rotacion de refresh.

El Core es el proveedor de identidad de la plataforma. Los otros 8 modulos no
implementan login: reciben un token firmado por el Core y lo validan con la clave
publica de `/.well-known/jwks.json`, sin llamarnos.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import structlog

from app.core.config import settings
from app.core.database import utcnow
from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.security import (
    TOKEN_TYPE_ACCESS,
    TOKEN_TYPE_SERVICE,
    create_access_token,
    generate_opaque_token,
    hash_opaque_token,
    verify_password,
)
from app.models.identity import ApiClient, RefreshToken, User, UserStatus
from app.repositories.identity_repository import (
    ApiClientRepository,
    RefreshTokenRepository,
    UserRepository,
)

logger = structlog.get_logger(__name__)

MAX_FAILED_ATTEMPTS = 5
"""Intentos fallidos consecutivos antes de bloquear la cuenta."""


@dataclass
class TokenPair:
    access_token: str
    expires_at: datetime
    refresh_token: str | None = None
    token_type: str = "Bearer"

    @property
    def expires_in(self) -> int:
        return max(int((self.expires_at - utcnow()).total_seconds()), 0)


class AuthService:
    def __init__(
        self,
        *,
        user_repo: UserRepository,
        refresh_repo: RefreshTokenRepository,
        client_repo: ApiClientRepository,
    ) -> None:
        self.user_repo = user_repo
        self.refresh_repo = refresh_repo
        self.client_repo = client_repo

    # ------------------------------------------------------------------
    # Personas
    # ------------------------------------------------------------------
    async def login(
        self, *, email: str, password: str, user_agent: str | None = None
    ) -> tuple[User, TokenPair]:
        user = await self.user_repo.get_by_email(email)

        # Mismo mensaje para usuario inexistente y password incorrecta: no se
        # filtra si el email existe.
        if user is None or not user.password_hash:
            logger.info("login_failed", email=email, reason="not_found")
            raise UnauthorizedError("Credenciales invalidas.", code="INVALID_CREDENTIALS")

        if not verify_password(password, user.password_hash):
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
                user.status = UserStatus.BLOCKED
                logger.warning("user_blocked_by_attempts", email=email)
            logger.info(
                "login_failed",
                email=email,
                reason="bad_password",
                attempts=user.failed_login_attempts,
            )
            raise UnauthorizedError("Credenciales invalidas.", code="INVALID_CREDENTIALS")

        if not user.is_active:
            raise ForbiddenError(
                f"La cuenta esta en estado {user.status}. Contactate con un administrador.",
                code="ACCOUNT_NOT_ACTIVE",
            )

        user.failed_login_attempts = 0
        user.last_login_at = utcnow()

        tokens = await self._issue_for_user(user, user_agent=user_agent)
        logger.info("login_ok", email=user.email, roles=user.role_codes)
        return user, tokens

    async def _issue_for_user(self, user: User, *, user_agent: str | None = None) -> TokenPair:
        access_token, expires_at = create_access_token(
            subject=str(user.id),
            token_type=TOKEN_TYPE_ACCESS,
            roles=user.role_codes,
            permissions=user.permission_codes,
            extra={"email": user.email, "name": user.full_name},
        )
        refresh_token = generate_opaque_token()
        self.refresh_repo.add(
            RefreshToken(
                user_id=user.id,
                token_hash=hash_opaque_token(refresh_token),
                expires_at=utcnow() + timedelta(days=settings.refresh_token_ttl_days),
                user_agent=(user_agent or "")[:255] or None,
            )
        )
        return TokenPair(
            access_token=access_token, expires_at=expires_at, refresh_token=refresh_token
        )

    async def refresh(self, *, refresh_token: str, user_agent: str | None = None) -> TokenPair:
        """Rota el refresh token: el viejo se revoca y apunta al nuevo.

        Si llega un token ya revocado se cierran *todas* las sesiones del
        usuario: o se filtro el token, o hay un cliente reusandolo. En cualquier
        caso conviene forzar un login nuevo.
        """
        stored = await self.refresh_repo.get_by_hash(hash_opaque_token(refresh_token))
        if stored is None:
            raise UnauthorizedError("El refresh token es invalido.", code="INVALID_REFRESH_TOKEN")

        if stored.revoked_at is not None:
            revoked = await self.refresh_repo.revoke_all_for_user(stored.user_id, at=utcnow())
            logger.warning(
                "refresh_token_reuse_detected",
                user_id=str(stored.user_id),
                sessions_revoked=revoked,
            )
            raise UnauthorizedError(
                "El refresh token ya fue usado. Por seguridad se cerraron todas las "
                "sesiones: volve a iniciar sesion.",
                code="REFRESH_TOKEN_REUSED",
            )

        if stored.expires_at <= utcnow():
            raise UnauthorizedError("El refresh token expiro.", code="REFRESH_TOKEN_EXPIRED")

        user = await self.user_repo.get_with_roles(stored.user_id)
        if user is None or not user.is_active:
            raise ForbiddenError("La cuenta ya no esta activa.", code="ACCOUNT_NOT_ACTIVE")

        tokens = await self._issue_for_user(user, user_agent=user_agent)
        stored.revoked_at = utcnow()
        await self.refresh_repo.flush()

        replacement = await self.refresh_repo.get_by_hash(
            hash_opaque_token(tokens.refresh_token or "")
        )
        if replacement is not None:
            stored.replaced_by_id = replacement.id
        return tokens

    async def logout(self, *, refresh_token: str) -> bool:
        stored = await self.refresh_repo.get_by_hash(hash_opaque_token(refresh_token))
        if stored is None or stored.revoked_at is not None:
            return False
        stored.revoked_at = utcnow()
        return True

    async def logout_everywhere(self, user: User) -> int:
        return await self.refresh_repo.revoke_all_for_user(user.id, at=utcnow())

    # ------------------------------------------------------------------
    # Modulos (client_credentials)
    # ------------------------------------------------------------------
    async def issue_service_token(self, *, client_id: str, client_secret: str) -> TokenPair:
        """Token para un modulo. Sin refresh: el modulo pide otro cuando expira."""
        client = await self.client_repo.get_by_client_id(client_id)
        if client is None or not client.active:
            logger.info("service_auth_failed", client_id=client_id, reason="unknown_or_inactive")
            raise UnauthorizedError("Credenciales de cliente invalidas.", code="INVALID_CLIENT")

        if hash_opaque_token(client_secret) != client.client_secret_hash:
            logger.info("service_auth_failed", client_id=client_id, reason="bad_secret")
            raise UnauthorizedError("Credenciales de cliente invalidas.", code="INVALID_CLIENT")

        client.last_used_at = utcnow()
        access_token, expires_at = create_access_token(
            subject=f"module:{client.module_name}",
            token_type=TOKEN_TYPE_SERVICE,
            scopes=list(client.scopes or []),
            extra={"module": client.module_name, "clientId": client.client_id},
        )
        logger.info("service_token_issued", module=client.module_name)
        return TokenPair(access_token=access_token, expires_at=expires_at)

    def register_client_secret(self, client: ApiClient) -> str:
        """Genera y asigna un secret nuevo. Devuelve el valor en claro **una sola vez**."""
        secret = generate_opaque_token()
        client.client_secret_hash = hash_opaque_token(secret)
        return secret
