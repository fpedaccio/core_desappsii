"""Endpoints de autenticacion.

El Core es el proveedor de identidad de la plataforma:

* Las personas hacen `POST /auth/login` y reciben access + refresh token.
* Los modulos hacen `POST /auth/token` (client_credentials) y reciben un token
  de servicio con el scope de su modulo.
* Todos validan con `GET /.well-known/jwks.json`, **sin llamar al Core**.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, status

from app.api.deps import AuthDep, PrincipalDep, UserAgentDep
from app.api.v1.schemas.common import MessageResponse
from app.api.v1.schemas.identity import (
    ClientCredentialsRequest,
    IntrospectRequest,
    IntrospectResponse,
    LoginRequest,
    MeResponse,
    RefreshRequest,
    TokenResponse,
)
from app.core.errors import UnauthorizedError
from app.core.security import TOKEN_TYPE_SERVICE, decode_token, jwks

router = APIRouter(tags=["Autenticacion"])


@router.post(
    "/auth/login",
    response_model=TokenResponse,
    summary="Iniciar sesion",
    description=(
        "Autentica a una persona y devuelve access token (JWT RS256) y refresh "
        "token rotativo. Tras 5 intentos fallidos consecutivos la cuenta se bloquea."
    ),
)
async def login(
    payload: LoginRequest, auth: AuthDep, user_agent: UserAgentDep
) -> TokenResponse:
    _, tokens = await auth.login(
        email=payload.email, password=payload.password, user_agent=user_agent
    )
    return TokenResponse(
        access_token=tokens.access_token,
        expires_in=tokens.expires_in,
        refresh_token=tokens.refresh_token,
    )


@router.post(
    "/auth/refresh",
    response_model=TokenResponse,
    summary="Renovar el access token",
    description=(
        "Rota el refresh token. Si se presenta uno ya usado se revocan todas las "
        "sesiones del usuario, porque indica que el token se filtro."
    ),
)
async def refresh(
    payload: RefreshRequest, auth: AuthDep, user_agent: UserAgentDep
) -> TokenResponse:
    tokens = await auth.refresh(refresh_token=payload.refresh_token, user_agent=user_agent)
    return TokenResponse(
        access_token=tokens.access_token,
        expires_in=tokens.expires_in,
        refresh_token=tokens.refresh_token,
    )


@router.post(
    "/auth/logout",
    response_model=MessageResponse,
    summary="Cerrar la sesion actual",
)
async def logout(payload: RefreshRequest, auth: AuthDep) -> MessageResponse:
    revoked = await auth.logout(refresh_token=payload.refresh_token)
    return MessageResponse(
        message="Sesion cerrada." if revoked else "El token ya no estaba activo."
    )


@router.post(
    "/auth/token",
    response_model=TokenResponse,
    summary="Token de servicio para un modulo (client_credentials)",
    description=(
        "Autenticacion modulo-a-modulo. Es lo que usan los otros 8 modulos para "
        "publicar eventos en el hub. No devuelve refresh token: cuando expira, se "
        "pide otro."
    ),
)
async def service_token(payload: ClientCredentialsRequest, auth: AuthDep) -> TokenResponse:
    tokens = await auth.issue_service_token(
        client_id=payload.client_id, client_secret=payload.client_secret
    )
    return TokenResponse(access_token=tokens.access_token, expires_in=tokens.expires_in)


@router.post(
    "/auth/introspect",
    response_model=IntrospectResponse,
    summary="Validar un token de forma sincronica",
    description=(
        "Validacion en linea de un token. Los modulos deberian preferir el JWKS "
        "(validacion offline, sin dependencia del Core); este endpoint cubre el "
        "caso que el enunciado habilita: cuando hace falta validar una identidad "
        "para poder continuar la operacion."
    ),
)
async def introspect(payload: IntrospectRequest) -> IntrospectResponse:
    try:
        claims: dict[str, Any] = decode_token(payload.token)
    except UnauthorizedError as exc:
        return IntrospectResponse(active=False, reason=exc.message)

    is_module = claims.get("typ") == TOKEN_TYPE_SERVICE
    return IntrospectResponse(
        active=True,
        subject=str(claims.get("sub", "")),
        kind="module" if is_module else "user",
        email=claims.get("email"),
        module=claims.get("module"),
        roles=list(claims.get("roles", [])),
        permissions=list(claims.get("permissions", [])),
        scopes=list(claims.get("scopes", [])),
        expires_at=(
            datetime.fromtimestamp(claims["exp"], tz=timezone.utc) if claims.get("exp") else None
        ),
    )


@router.get(
    "/auth/me",
    response_model=MeResponse,
    summary="Identidad del llamador",
    description=(
        "Devuelve roles y permisos del token. El frontend lo usa para mostrar solo "
        "las operaciones disponibles segun el rol autenticado."
    ),
)
async def me(principal: PrincipalDep) -> MeResponse:
    return MeResponse(
        subject=principal.subject,
        kind=principal.kind,
        email=principal.email,
        name=principal.name,
        module=principal.module,
        roles=principal.roles,
        permissions=principal.permissions,
        scopes=principal.scopes,
    )


jwks_router = APIRouter(tags=["Autenticacion"])


@jwks_router.get(
    "/.well-known/jwks.json",
    status_code=status.HTTP_200_OK,
    summary="Clave publica para validar tokens (JWKS)",
    description=(
        "JWK Set del Core. Los otros modulos lo cachean y validan los tokens "
        "localmente: si el Core se cae, los logins ya emitidos siguen siendo "
        "validos y ningun modulo queda bloqueado."
    ),
)
async def jwks_endpoint() -> dict[str, Any]:
    return jwks()
