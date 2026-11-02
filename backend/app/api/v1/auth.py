"""Autenticacion: dos caminos separados.

Las **personas** entran al dashboard con su email y contrasena. Los **backends
de los modulos** obtienen un token con el secret de maquina del modulo, para
publicar eventos.

Estan separados porque se rotan distinto: cambiar la contrasena de alguien no
toca el backend desplegado del equipo, y rotar el secret de maquina no le corta
el acceso al dashboard a nadie.
"""

from __future__ import annotations

import hashlib
import inspect

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import AuthDep, CallerDep
from app.api.v1.schemas.dto import (
    LoginRequest,
    MeResponse,
    ModuleTokenRequest,
    TokenResponse,
)
from app.core.auth_rate_limit import AuthRateLimiter
from app.core.config import settings
from app.core.context import get_trace_id
from app.core.database import SessionFactory, engine
from app.core.shared_auth_rate_limit import SharedAuthRateLimiter

router = APIRouter(tags=["Autenticacion"])


async def _check_auth_limit(request: Request, identity: str) -> JSONResponse | None:
    try:
        limiter = getattr(request.app.state, "auth_rate_limiter", None)
        if limiter is None:
            if engine.dialect.name == "postgresql":
                limiter = SharedAuthRateLimiter(SessionFactory)
            elif settings.is_production:
                raise RuntimeError("Shared authentication limiter requires PostgreSQL")
            else:
                limiter = AuthRateLimiter()
            request.app.state.auth_rate_limiter = limiter

        # No passwords, secrets or raw account identifiers in stored keys.
        digest = hashlib.sha256(identity.strip().casefold().encode("utf-8")).hexdigest()
        result = limiter.check(request.url.path + ":" + digest)
        retry_after = await result if inspect.isawaitable(result) else result
    except (SQLAlchemyError, TimeoutError, OSError, RuntimeError):
        return JSONResponse(
            status_code=503,
            headers={"Retry-After": "5", "Cache-Control": "no-store"},
            content={
                "code": "AUTH_RATE_LIMIT_UNAVAILABLE",
                "message": "Autenticacion temporalmente no disponible. Reintenta mas tarde.",
                "details": [],
                "traceId": get_trace_id(),
            },
        )
    if not retry_after:
        return None
    return JSONResponse(
        status_code=429,
        headers={"Retry-After": str(retry_after), "Cache-Control": "no-store"},
        content={
            "code": "RATE_LIMITED",
            "message": "Demasiados intentos. Reintenta mas tarde.",
            "details": [],
            "traceId": get_trace_id(),
        },
    )


def _as_response(token) -> TokenResponse:
    return TokenResponse(
        access_token=token.access_token,
        expires_in=token.expires_in,
        module=token.module,
        display_name=token.display_name,
        is_admin=token.is_admin,
        kind=token.kind,
        actor=token.actor,
    )


@router.post(
    "/auth/login",
    responses={
        503: {"description": "Almacenamiento del limitador no disponible."},
        429: {
            "description": (
                "10 solicitudes por identidad cada 60 segundos; compartido en PostgreSQL."
            )
        }
    },
    response_model=TokenResponse,
    summary="Entrar al dashboard (persona)",
    description=(
        "Login de un integrante de un equipo. El token queda atado al modulo de "
        "la persona, y la auditoria registra su email.\n\n"
        "Tras 5 intentos fallidos consecutivos la cuenta se desactiva; la puede "
        "reactivar cualquier integrante del mismo equipo."
    ),
)
async def login(
    payload: LoginRequest, auth: AuthDep, request: Request
) -> TokenResponse | JSONResponse:
    blocked = await _check_auth_limit(request, payload.email)
    if blocked is not None:
        return blocked
    _, token = await auth.login(email=payload.email, password=payload.password)
    return _as_response(token)


@router.post(
    "/auth/module-token",
    responses={
        503: {"description": "Almacenamiento del limitador no disponible."},
        429: {
            "description": (
                "10 solicitudes por identidad cada 60 segundos; compartido en PostgreSQL."
            )
        }
    },
    response_model=TokenResponse,
    summary="Token de maquina (backend de un modulo)",
    description=(
        "Es lo que usa el backend de un equipo para publicar eventos. El secret "
        "vive en su configuracion, no lo usa ninguna persona.\n\n"
        "No hay refresh: cuando el token expira se pide otro."
    ),
)
async def module_token(
    payload: ModuleTokenRequest, auth: AuthDep, request: Request
) -> TokenResponse | JSONResponse:
    blocked = await _check_auth_limit(request, payload.module)
    if blocked is not None:
        return blocked
    token = await auth.issue_module_token(module_name=payload.module, secret=payload.secret)
    return _as_response(token)


@router.get(
    "/auth/me",
    response_model=MeResponse,
    summary="Quien soy",
    description=(
        "El frontend lo usa para saber si mostrar la vista de un modulo o la "
        "global del administrador, y para restaurar la sesion al refrescar."
    ),
)
async def me(caller: CallerDep) -> MeResponse:
    return MeResponse(
        module=caller.module,
        display_name=caller.display_name,
        is_admin=caller.is_admin,
        kind=caller.kind,
        email=caller.email,
        name=caller.name,
    )
