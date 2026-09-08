"""Cuentas del dashboard.

Cada equipo administra las de sus propios integrantes; el equipo 9 las de
cualquiera. No hay roles: lo que una persona ve sale de su modulo.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.api.deps import CallerDep, UserServiceDep
from app.api.v1.schemas.common import MessageResponse
from app.api.v1.schemas.dto import PasswordUpdate, UserCreate, UserResponse, UserUpdate

router = APIRouter(prefix="/users", tags=["Cuentas del dashboard"])


@router.get(
    "",
    response_model=list[UserResponse],
    summary="Listar cuentas",
    description="Las de tu equipo. El equipo 9 ve las de todos los modulos.",
)
async def list_users(caller: CallerDep, service: UserServiceDep) -> list[UserResponse]:
    users = await service.list_users(actor_module=caller.module, actor_is_admin=caller.is_admin)
    return [UserResponse.of(user) for user in users]


@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear una cuenta",
    description=(
        "Da de alta a un integrante en tu equipo. Cualquier integrante puede "
        "hacerlo, para que el equipo se autoadministre sin depender del equipo 9."
    ),
)
async def create_user(
    payload: UserCreate, caller: CallerDep, service: UserServiceDep
) -> UserResponse:
    user = await service.create(
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        module_name=payload.module,
        actor_module=caller.module,
        actor_is_admin=caller.is_admin,
    )
    return UserResponse.of(user)


@router.patch(
    "/{user_id}",
    response_model=UserResponse,
    summary="Editar o desactivar una cuenta",
    description=(
        "No se puede desactivar la unica cuenta activa de un equipo: quedaria sin "
        "forma de volver a entrar."
    ),
)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    caller: CallerDep,
    service: UserServiceDep,
) -> UserResponse:
    user = await service.update(
        user_id,
        full_name=payload.full_name,
        active=payload.active,
        actor_module=caller.module,
        actor_is_admin=caller.is_admin,
    )
    return UserResponse.of(user)


@router.put(
    "/{user_id}/password",
    response_model=MessageResponse,
    summary="Cambiar la contrasena",
    description="Al menos 8 caracteres, combinando letras y numeros.",
)
async def set_password(
    user_id: uuid.UUID,
    payload: PasswordUpdate,
    caller: CallerDep,
    service: UserServiceDep,
) -> MessageResponse:
    await service.set_password(
        user_id,
        password=payload.password,
        actor_module=caller.module,
        actor_is_admin=caller.is_admin,
    )
    return MessageResponse(message="Contrasena actualizada.")


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar una cuenta",
    description="No se puede eliminar la unica cuenta activa de un equipo.",
)
async def delete_user(user_id: uuid.UUID, caller: CallerDep, service: UserServiceDep) -> None:
    await service.delete(user_id, actor_module=caller.module, actor_is_admin=caller.is_admin)
