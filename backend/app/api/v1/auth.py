"""Autenticacion: dos caminos separados.

Las **personas** entran al dashboard con su email y contrasena. Los **backends
de los modulos** obtienen un token con el secret de maquina del modulo, para
publicar eventos.

Estan separados porque se rotan distinto: cambiar la contrasena de alguien no
toca el backend desplegado del equipo, y rotar el secret de maquina no le corta
el acceso al dashboard a nadie.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import AuthDep, CallerDep
from app.api.v1.schemas.dto import (
    LoginRequest,
    MeResponse,
    ModuleTokenRequest,
    TokenResponse,
)

router = APIRouter(tags=["Autenticacion"])


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
    response_model=TokenResponse,
    summary="Entrar al dashboard (persona)",
    description=(
        "Login de un integrante de un equipo. El token queda atado al modulo de "
        "la persona, y la auditoria registra su email.\n\n"
        "Tras 5 intentos fallidos consecutivos la cuenta se desactiva; la puede "
        "reactivar cualquier integrante del mismo equipo."
    ),
)
async def login(payload: LoginRequest, auth: AuthDep) -> TokenResponse:
    _, token = await auth.login(email=payload.email, password=payload.password)
    return _as_response(token)


@router.post(
    "/auth/module-token",
    response_model=TokenResponse,
    summary="Token de maquina (backend de un modulo)",
    description=(
        "Es lo que usa el backend de un equipo para publicar eventos. El secret "
        "vive en su configuracion, no lo usa ninguna persona.\n\n"
        "No hay refresh: cuando el token expira se pide otro."
    ),
)
async def module_token(payload: ModuleTokenRequest, auth: AuthDep) -> TokenResponse:
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
