"""Endpoints de los catalogos globales.

Los consumen los 9 modulos, asi que la lectura solo pide `catalogs:read`, que
tienen todos los roles del panel.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import CatalogDep, require_permissions
from app.api.v1.schemas.catalog import (
    BarrioCreate,
    BarrioResponse,
    BarrioUpdate,
    CatalogItemCreate,
    CatalogItemResponse,
    CatalogItemUpdate,
    CatalogTypeCreate,
    CatalogTypeResponse,
    DependenciaCreate,
    DependenciaResponse,
    DependenciaUpdate,
    ZonaCreate,
    ZonaResponse,
    ZonaUpdate,
)
from app.api.v1.schemas.common import PageResponse
from app.core import permissions as perms

router = APIRouter(prefix="/catalogs", tags=["Catalogos globales"])

_read = Depends(require_permissions(perms.CATALOGS_READ))
_write = Depends(require_permissions(perms.CATALOGS_WRITE))


# ----------------------------------------------------------------------
# Dependencias municipales
# ----------------------------------------------------------------------
@router.get(
    "/dependencias",
    response_model=PageResponse[DependenciaResponse],
    dependencies=[_read],
    summary="Listar dependencias municipales",
)
async def list_dependencias(
    service: CatalogDep,
    query: str | None = Query(default=None),
    active: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> PageResponse[DependenciaResponse]:
    result = await service.search_dependencias(
        query=query, active=active, page=page, size=size
    )
    return PageResponse.build(result, DependenciaResponse.of)


@router.post(
    "/dependencias",
    response_model=DependenciaResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_write],
    summary="Crear dependencia",
)
async def create_dependencia(
    payload: DependenciaCreate, service: CatalogDep
) -> DependenciaResponse:
    dependencia = await service.create_dependencia(
        code=payload.code,
        name=payload.name,
        description=payload.description,
        parent_code=payload.parent_code,
        contact_email=payload.contact_email,
    )
    return DependenciaResponse.of(dependencia)


@router.patch(
    "/dependencias/{dependencia_id}",
    response_model=DependenciaResponse,
    dependencies=[_write],
    summary="Editar dependencia",
)
async def update_dependencia(
    dependencia_id: uuid.UUID, payload: DependenciaUpdate, service: CatalogDep
) -> DependenciaResponse:
    dependencia = await service.update_dependencia(
        dependencia_id,
        name=payload.name,
        description=payload.description,
        contact_email=payload.contact_email,
        active=payload.active,
    )
    return DependenciaResponse.of(dependencia)


# ----------------------------------------------------------------------
# Zonas
# ----------------------------------------------------------------------
@router.get(
    "/zonas",
    response_model=PageResponse[ZonaResponse],
    dependencies=[_read],
    summary="Listar zonas",
)
async def list_zonas(
    service: CatalogDep,
    query: str | None = Query(default=None),
    active: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> PageResponse[ZonaResponse]:
    result = await service.search_zonas(query=query, active=active, page=page, size=size)
    return PageResponse.build(result, ZonaResponse.of)


@router.post(
    "/zonas",
    response_model=ZonaResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_write],
    summary="Crear zona",
)
async def create_zona(payload: ZonaCreate, service: CatalogDep) -> ZonaResponse:
    zona = await service.create_zona(
        code=payload.code, name=payload.name, description=payload.description
    )
    return ZonaResponse.of(zona)


@router.patch(
    "/zonas/{zona_id}",
    response_model=ZonaResponse,
    dependencies=[_write],
    summary="Editar zona",
)
async def update_zona(
    zona_id: uuid.UUID, payload: ZonaUpdate, service: CatalogDep
) -> ZonaResponse:
    zona = await service.update_zona(
        zona_id, name=payload.name, description=payload.description, active=payload.active
    )
    return ZonaResponse.of(zona)


# ----------------------------------------------------------------------
# Barrios
# ----------------------------------------------------------------------
@router.get(
    "/barrios",
    response_model=PageResponse[BarrioResponse],
    dependencies=[_read],
    summary="Listar barrios",
)
async def list_barrios(
    service: CatalogDep,
    query: str | None = Query(default=None, description="Busca por nombre, codigo o CP"),
    zona_id: uuid.UUID | None = Query(default=None, alias="zonaId"),
    active: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
) -> PageResponse[BarrioResponse]:
    result = await service.search_barrios(
        query=query, zona_id=zona_id, active=active, page=page, size=size
    )
    return PageResponse.build(result, BarrioResponse.of)


@router.post(
    "/barrios",
    response_model=BarrioResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_write],
    summary="Crear barrio",
)
async def create_barrio(payload: BarrioCreate, service: CatalogDep) -> BarrioResponse:
    barrio = await service.create_barrio(
        code=payload.code,
        name=payload.name,
        zona_code=payload.zona_code,
        postal_code=payload.postal_code,
    )
    return BarrioResponse.of(barrio)


@router.patch(
    "/barrios/{barrio_id}",
    response_model=BarrioResponse,
    dependencies=[_write],
    summary="Editar barrio",
)
async def update_barrio(
    barrio_id: uuid.UUID, payload: BarrioUpdate, service: CatalogDep
) -> BarrioResponse:
    barrio = await service.update_barrio(
        barrio_id,
        name=payload.name,
        zona_code=payload.zona_code,
        postal_code=payload.postal_code,
        active=payload.active,
    )
    return BarrioResponse.of(barrio)


# ----------------------------------------------------------------------
# Catalogos genericos
# ----------------------------------------------------------------------
@router.get(
    "/types",
    response_model=list[CatalogTypeResponse],
    dependencies=[_read],
    summary="Listar catalogos genericos",
    description=(
        "Catalogos de referencia reutilizables (categorias de reclamo, rubros "
        "comerciales, tipos de tributo...). Evitan crear una tabla nueva por cada "
        "lista que necesita un modulo."
    ),
)
async def list_catalog_types(service: CatalogDep) -> list[CatalogTypeResponse]:
    return [CatalogTypeResponse.of(item) for item in await service.list_catalog_types()]


@router.post(
    "/types",
    response_model=CatalogTypeResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_write],
    summary="Crear un catalogo generico",
)
async def create_catalog_type(
    payload: CatalogTypeCreate, service: CatalogDep
) -> CatalogTypeResponse:
    catalog_type = await service.create_catalog_type(
        code=payload.code,
        name=payload.name,
        description=payload.description,
        owner_module=payload.owner_module,
    )
    return CatalogTypeResponse.of(catalog_type)


@router.get(
    "/types/{catalog_code}/items",
    response_model=PageResponse[CatalogItemResponse],
    dependencies=[_read],
    summary="Listar items de un catalogo",
)
async def list_catalog_items(
    catalog_code: str,
    service: CatalogDep,
    query: str | None = Query(default=None),
    active: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
) -> PageResponse[CatalogItemResponse]:
    result = await service.search_catalog_items(
        catalog_code=catalog_code, query=query, active=active, page=page, size=size
    )
    return PageResponse.build(result, CatalogItemResponse.of)


@router.post(
    "/types/{catalog_code}/items",
    response_model=CatalogItemResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_write],
    summary="Agregar un item a un catalogo",
)
async def create_catalog_item(
    catalog_code: str, payload: CatalogItemCreate, service: CatalogDep
) -> CatalogItemResponse:
    item = await service.create_catalog_item(
        catalog_code=catalog_code,
        code=payload.code,
        label=payload.label,
        parent_code=payload.parent_code,
        sort_order=payload.sort_order,
        attributes=payload.attributes,
    )
    return CatalogItemResponse.of(item)


@router.patch(
    "/items/{item_id}",
    response_model=CatalogItemResponse,
    dependencies=[_write],
    summary="Editar un item de catalogo",
)
async def update_catalog_item(
    item_id: uuid.UUID, payload: CatalogItemUpdate, service: CatalogDep
) -> CatalogItemResponse:
    item = await service.update_catalog_item(
        item_id,
        label=payload.label,
        sort_order=payload.sort_order,
        attributes=payload.attributes,
        active=payload.active,
    )
    return CatalogItemResponse.of(item)
