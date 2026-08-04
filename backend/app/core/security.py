"""Primitivas de seguridad: hashing de credenciales y emision/validacion de JWT.

El Core es el proveedor de identidad de la plataforma. Los tokens se firman con
**RS256** y la clave publica se expone en `/.well-known/jwks.json`, de modo que
los otros 8 modulos validen tokens *localmente*, sin llamar al Core en cada
request. Esa es la pieza que evita que una caida del Core bloquee el acceso a
toda la plataforma (regla 7 del enunciado).
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt
import structlog
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.config import settings
from app.core.errors import UnauthorizedError

logger = structlog.get_logger(__name__)

ALGORITHM = "RS256"
TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_SERVICE = "service"

_BCRYPT_MAX_BYTES = 72  # limite del algoritmo; arriba de eso bcrypt truncaria en silencio


# --------------------------------------------------------------------------
# Credenciales
# --------------------------------------------------------------------------
def hash_password(password: str) -> str:
    payload = _prepare_password(password)
    return bcrypt.hashpw(payload, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_prepare_password(password), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        # Hash con formato invalido: se trata como credencial incorrecta.
        return False


def _prepare_password(password: str) -> bytes:
    """Pre-hashea si excede el limite de bcrypt, para no truncar la contrasena."""
    raw = password.encode("utf-8")
    if len(raw) > _BCRYPT_MAX_BYTES:
        return base64.b64encode(hashlib.sha256(raw).digest())
    return raw


def generate_opaque_token() -> str:
    """Refresh tokens y client secrets: opacos, no JWT."""
    return secrets.token_urlsafe(48)


def hash_opaque_token(token: str) -> str:
    """En la base solo se guarda el hash, nunca el token en claro."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Claves RSA
# --------------------------------------------------------------------------
_private_key: rsa.RSAPrivateKey | None = None


def _load_or_create_private_key() -> rsa.RSAPrivateKey:
    global _private_key
    if _private_key is not None:
        return _private_key

    if settings.jwt_private_key:
        _private_key = serialization.load_pem_private_key(
            settings.jwt_private_key.replace("\\n", "\n").encode("utf-8"), password=None
        )  # type: ignore[assignment]
    else:
        if settings.is_production:
            raise RuntimeError(
                "JWT_PRIVATE_KEY es obligatoria en produccion: sin clave fija, cada "
                "reinicio invalidaria todos los tokens emitidos."
            )
        logger.warning(
            "jwt_ephemeral_key_generated",
            hint="Configura JWT_PRIVATE_KEY/JWT_PUBLIC_KEY para que los tokens "
            "sobrevivan a un reinicio.",
        )
        _private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return _private_key  # type: ignore[return-value]


def private_key_pem() -> str:
    return (
        _load_or_create_private_key()
        .private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        .decode("utf-8")
    )


def public_key_pem() -> str:
    if settings.jwt_public_key:
        return settings.jwt_public_key.replace("\\n", "\n")
    return (
        _load_or_create_private_key()
        .public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )


def _b64url_uint(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def jwks() -> dict[str, Any]:
    """JWK Set publico. Lo consumen los otros modulos para validar offline."""
    numbers = _load_or_create_private_key().public_key().public_numbers()
    return {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": ALGORITHM,
                "kid": settings.jwt_kid,
                "n": _b64url_uint(numbers.n),
                "e": _b64url_uint(numbers.e),
            }
        ]
    }


# --------------------------------------------------------------------------
# JWT
# --------------------------------------------------------------------------
def create_access_token(
    *,
    subject: str,
    token_type: str = TOKEN_TYPE_ACCESS,
    roles: list[str] | None = None,
    permissions: list[str] | None = None,
    scopes: list[str] | None = None,
    extra: dict[str, Any] | None = None,
    ttl_minutes: int | None = None,
) -> tuple[str, datetime]:
    """Firma un access token. Devuelve el token y su instante de expiracion."""
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=ttl_minutes or settings.access_token_ttl_minutes)
    payload: dict[str, Any] = {
        "sub": subject,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": secrets.token_urlsafe(16),
        "typ": token_type,
        "roles": roles or [],
        "permissions": permissions or [],
        "scopes": scopes or [],
    }
    if extra:
        payload.update(extra)

    token = jwt.encode(
        payload,
        private_key_pem(),
        algorithm=ALGORITHM,
        headers={"kid": settings.jwt_kid},
    )
    return token, expires_at


def decode_token(token: str) -> dict[str, Any]:
    """Valida firma, emisor, audiencia y expiracion."""
    try:
        return jwt.decode(
            token,
            public_key_pem(),
            algorithms=[ALGORITHM],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
        )
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("El token expiro.", code="TOKEN_EXPIRED") from exc
    except jwt.InvalidTokenError as exc:
        raise UnauthorizedError("El token es invalido.", code="TOKEN_INVALID") from exc
