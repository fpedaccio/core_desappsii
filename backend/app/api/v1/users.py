"""Endpoints de usuarios, roles, permisos y cuentas de servicio."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import ApiClientServiceDep, UserServiceDep, require_permissions
from app.api.v1.schemas.common import MessageResponse, PageResponse, SecretResponse
from app.api.v1.schemas.identity import (
    ApiClientCreate,
    ApiClientResponse,
    PasswordUpdate,
    PermissionResponse,
    RoleCreate,
    RoleResponse,
    RoleUpdate,
    UserCreate,
    UserResponse,
    UserUpdate,
)
from app.core import permissions as perms
from app.models.identity import UserStatus

router = APIRouter(prefix="/users", tags=["Usuarios y accesos"])


@router.get(
    "",
    response_model=PageResponse[UserResponse],
    dependencies=[Depends(require_permissions(perms.USERS_READ))],
    summary="Listar usuarios",
)
async def list_users(
    service: UserServiceDep,
    query: str | None = Query(default=None, description="Busca por email, nombre o documento"),
    status_filter: UserStatus | None = Query(default=None, alias="status"),
    role: str | None = Query(default=None, description="Filtra por codigo de rol"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> PageResponse[UserResponse]:
    result = await service.search(
        query=query, status=status_filter, role_code=role, page=page, size=size
    )
    return PageResponse.build(result, UserResponse.of)


@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(perms.USERS_WRITE))],
    summary="Crear usuario",
)
async def create_user(payload: UserCreate, service: UserServiceDep) -> UserResponse:
    user = await service.create(
        email=payload.email,
        full_name=payload.full_name,
        password=payload.password,
        document_number=payload.document_number,
        role_codes=payload.role_codes,
        status=payload.status,
    )
    return UserResponse.of(user)


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    dependencies=[Depends(require_permissions(perms.USERS_READ))],
    summary="Ver un usuario",
)
async def get_user(user_id: uuid.UUID, service: UserServiceDep) -> UserResponse:
    return UserResponse.of(await service.get(user_id))


@router.patch(
    "/{user_id}",
    response_model=UserResponse,
    dependencies=[Depends(require_permissions(perms.USERS_WRITE))],
    summary="Editar usuario",
    description=(
        "Al pasar el estado a INACTIVE o BLOCKED se revocan las sesiones abiertas: "
        "de lo contrario el refresh token seguiria emitiendo access tokens validos."
    ),
)
async def update_user(
    user_id: uuid.UUID, payload: UserUpdate, service: UserServiceDep
) -> UserResponse:
    user = await service.update(
        user_id,
        full_name=payload.full_name,
        document_number=payload.document_number,
        status=payload.status,
        role_codes=payload.role_codes,
    )
    return UserResponse.of(user)


@router.put(
    "/{user_id}/password",
    response_model=MessageResponse,
    dependencies=[Depends(require_permissions(perms.USERS_WRITE))],
    summary="Definir la contrasena de un usuario",
)
async def set_password(
    user_id: uuid.UUID, payload: PasswordUpdate, service: UserServiceDep
) -> MessageResponse:
    await service.set_password(user_id, password=payload.password)
    return MessageResponse(message="Contrasena actualizada y sesiones cerradas.")


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permissions(perms.USERS_WRITE))],
    summary="Eliminar usuario",
)
async def delete_user(user_id: uuid.UUID, service: UserServiceDep) -> None:
    await service.delete(user_id)


# ----------------------------------------------------------------------
# Roles y permisos
# ----------------------------------------------------------------------
roles_router = APIRouter(prefix="/roles", tags=["Usuarios y accesos"])


@roles_router.get(
    "",
    response_model=list[RoleResponse],
    dependencies=[Depends(require_permissions(perms.ROLES_READ))],
    summary="Listar roles",
)
async def list_roles(service: UserServiceDep) -> list[RoleResponse]:
    return [RoleResponse.of(role) for role in await service.list_roles()]


@roles_router.post(
    "",
    response_model=RoleResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(perms.ROLES_WRITE))],
    summary="Crear rol",
)
async def create_role(payload: RoleCreate, service: UserServiceDep) -> RoleResponse:
    role = await service.create_role(
        code=payload.code,
        name=payload.name,
        description=payload.description,
        permission_codes=payload.permission_codes,
    )
    return RoleResponse.of(role)


@roles_router.patch(
    "/{role_id}",
    response_model=RoleResponse,
    dependencies=[Depends(require_permissions(perms.ROLES_WRITE))],
    summary="Editar rol",
)
async def update_role(
    role_id: uuid.UUID, payload: RoleUpdate, service: UserServiceDep
) -> RoleResponse:
    role = await service.update_role(
        role_id,
        name=payload.name,
        description=payload.description,
        permission_codes=payload.permission_codes,
    )
    return RoleResponse.of(role)


@roles_router.delete(
    "/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permissions(perms.ROLES_WRITE))],
    summary="Eliminar rol",
    description="Los roles de sistema no se pueden eliminar.",
)
async def delete_role(role_id: uuid.UUID, service: UserServiceDep) -> None:
    await service.delete_role(role_id)


permissions_router = APIRouter(prefix="/permissions", tags=["Usuarios y accesos"])


@permissions_router.get(
    "",
    response_model=list[PermissionResponse],
    dependencies=[Depends(require_permissions(perms.ROLES_READ))],
    summary="Listar permisos disponibles",
)
async def list_permissions(service: UserServiceDep) -> list[PermissionResponse]:
    return [PermissionResponse.of(perm) for perm in await service.list_permissions()]


# ----------------------------------------------------------------------
# Cuentas de servicio
# ----------------------------------------------------------------------
clients_router = APIRouter(prefix="/api-clients", tags=["Usuarios y accesos"])


@clients_router.get(
    "",
    response_model=list[ApiClientResponse],
    dependencies=[Depends(require_permissions(perms.CLIENTS_READ))],
    summary="Listar cuentas de servicio de los modulos",
)
async def list_clients(service: ApiClientServiceDep) -> list[ApiClientResponse]:
    return [ApiClientResponse.of(client) for client in await service.list_clients()]


@clients_router.post(
    "",
    response_model=SecretResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(perms.CLIENTS_WRITE))],
    summary="Crear cuenta de servicio",
    description=(
        "Da de alta las credenciales con las que un modulo publica eventos. "
        "**El secret se devuelve una sola vez**: el Core solo guarda su hash."
    ),
)
async def create_client(
    payload: ApiClientCreate, service: ApiClientServiceDep
) -> SecretResponse:
    client, secret = await service.create(
        client_id=payload.client_id,
        module_name=payload.module_name,
        description=payload.description,
        scopes=payload.scopes,
    )
    return SecretResponse(client_id=client.client_id, client_secret=secret)


@clients_router.post(
    "/{client_id}/rotate-secret",
    response_model=SecretResponse,
    dependencies=[Depends(require_permissions(perms.CLIENTS_WRITE))],
    summary="Rotar el secret de una cuenta de servicio",
)
async def rotate_secret(client_id: uuid.UUID, service: ApiClientServiceDep) -> SecretResponse:
    client, secret = await service.rotate_secret(client_id)
    return SecretResponse(client_id=client.client_id, client_secret=secret)


@clients_router.post(
    "/{client_id}/toggle",
    response_model=ApiClientResponse,
    dependencies=[Depends(require_permissions(perms.CLIENTS_WRITE))],
    summary="Activar o desactivar una cuenta de servicio",
)
async def toggle_client(
    client_id: uuid.UUID,
    service: ApiClientServiceDep,
    active: bool = Query(description="true activa la cuenta, false la desactiva"),
) -> ApiClientResponse:
    return ApiClientResponse.of(await service.set_active(client_id, active=active))
