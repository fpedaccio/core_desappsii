"""Autenticacion de modulos.

El Core no administra usuarios ni ciudadanos. Cada uno de los 9 modulos tiene una
credencial que sirve para entrar al dashboard y para publicar eventos.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import AuthDep, CallerDep
from app.api.v1.schemas.dto import LoginRequest, MeResponse, TokenResponse

router = APIRouter(tags=["Autenticacion"])


@router.post(
    "/auth/login",
    response_model=TokenResponse,
    summary="Obtener token",
    description=(
        "Autentica un modulo con su nombre y secret. El token sirve tanto para el "
        "dashboard como para publicar eventos por HTTP."
    ),
)
async def login(payload: LoginRequest, auth: AuthDep) -> TokenResponse:
    module, tokens = await auth.login(module_name=payload.module, secret=payload.secret)
    return TokenResponse(
        access_token=tokens.access_token,
        expires_in=tokens.expires_in,
        module=module.name,
        display_name=module.display_name,
        is_admin=module.is_admin,
    )


@router.get(
    "/auth/me",
    response_model=MeResponse,
    summary="Quien soy",
    description=(
        "El frontend lo usa para saber si mostrar la vista de un modulo o la global "
        "del administrador."
    ),
)
async def me(caller: CallerDep) -> MeResponse:
    return MeResponse(
        module=caller.module, display_name=caller.display_name, is_admin=caller.is_admin
    )
