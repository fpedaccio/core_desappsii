"""Catalogos globales: barrios, zonas y listas de referencia.

El enunciado le asigna al Core "barrios, zonas y catalogos globales" (seccion
10, modulo 9). Es el unico dato de negocio que el Core administra.

**Lectura abierta a cualquier modulo autenticado, escritura solo del admin.**
Un catalogo compartido deja de servir en el momento en que cada equipo puede
cambiarlo: lo que uno corrige, otro lo pisa.

**Se consulta por REST a proposito.** Un catalogo es configuracion, no un hecho
de negocio, y el enunciado habilita la integracion sincronica justamente para
"consultar una configuracion" (seccion 7). Por eso el Core sigue sin publicar
eventos de negocio.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, status

from app.api.deps import AdminDep, CallerDep, CatalogServiceDep
from app.api.v1.schemas.dto import (
    BarrioCreate,
    BarrioResponse,
    BarrioUpdate,
    ItemDeCatalogoCreate,
    ItemDeCatalogoResponse,
    ItemDeCatalogoUpdate,
    ZonaCreate,
    ZonaResponse,
    ZonaUpdate,
)

router = APIRouter(tags=["Catalogos globales"])


# ----------------------------------------------------------------------
# Zonas
# ----------------------------------------------------------------------
@router.get(
    "/catalogos/zonas",
    response_model=list[ZonaResponse],
    summary="Listar las zonas administrativas",
    description=(
        "Las zonas **administrativas** del municipio, que agrupan barrios.\n\n"
        "No confundir con las zonas *operativas* de cada area (los recorridos de "
        "recoleccion de Ambiente, por ejemplo): esas son de ese modulo y se arman "
        "agrupando estos barrios."
    ),
)
async def listar_zonas(
    caller: CallerDep,
    service: CatalogServiceDep,
    solo_activas: bool = Query(default=False, alias="soloActivas"),
) -> list[ZonaResponse]:
    zonas = await service.listar_zonas(solo_activas=solo_activas)
    return [ZonaResponse.of(z) for z in zonas]


@router.post(
    "/catalogos/zonas",
    response_model=ZonaResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear una zona",
)
async def crear_zona(
    payload: ZonaCreate, admin: AdminDep, service: CatalogServiceDep
) -> ZonaResponse:
    zona = await service.crear_zona(
        codigo=payload.codigo, nombre=payload.nombre, descripcion=payload.descripcion
    )
    return ZonaResponse.of(zona)


@router.patch(
    "/catalogos/zonas/{codigo}",
    response_model=ZonaResponse,
    summary="Modificar una zona",
    description="Para dar de baja una zona se usa `activo: false`. **Nada se borra**.",
)
async def actualizar_zona(
    codigo: str, payload: ZonaUpdate, admin: AdminDep, service: CatalogServiceDep
) -> ZonaResponse:
    zona = await service.actualizar_zona(
        codigo, nombre=payload.nombre, descripcion=payload.descripcion, activo=payload.activo
    )
    return ZonaResponse.of(zona)


# ----------------------------------------------------------------------
# Barrios
# ----------------------------------------------------------------------
@router.get(
    "/catalogos/barrios",
    response_model=list[BarrioResponse],
    summary="Listar los barrios del municipio",
    description=(
        "El catalogo territorial que comparten todos los modulos.\n\n"
        "`codigo` e `id` son los dos identificadores estables y **ninguno se "
        "reusa nunca**: un barrio que deja de existir queda con `activo: false`, "
        "porque hay eventos historicos que lo referencian.\n\n"
        "Para cachearlo del lado del consumidor: es una lista chica y cambia muy "
        "poco. Conviene leerla al arrancar y refrescarla cada tanto."
    ),
)
async def listar_barrios(
    caller: CallerDep,
    service: CatalogServiceDep,
    zona: str | None = Query(default=None, description="Filtrar por codigo de zona"),
    q: str | None = Query(default=None, description="Buscar por nombre"),
    solo_activos: bool = Query(default=False, alias="soloActivos"),
) -> list[BarrioResponse]:
    barrios = await service.listar_barrios(zona=zona, texto=q, solo_activos=solo_activos)
    return [BarrioResponse.of(b) for b in barrios]


@router.get(
    "/catalogos/barrios/{codigo}",
    response_model=BarrioResponse,
    summary="Obtener un barrio por su codigo",
)
async def obtener_barrio(
    codigo: str, caller: CallerDep, service: CatalogServiceDep
) -> BarrioResponse:
    return BarrioResponse.of(await service.obtener_barrio(codigo))


@router.post(
    "/catalogos/barrios",
    response_model=BarrioResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un barrio",
)
async def crear_barrio(
    payload: BarrioCreate, admin: AdminDep, service: CatalogServiceDep
) -> BarrioResponse:
    barrio = await service.crear_barrio(
        codigo=payload.codigo,
        nombre=payload.nombre,
        zona=payload.zona,
        metadatos=payload.metadatos,
    )
    return BarrioResponse.of(barrio)


@router.patch(
    "/catalogos/barrios/{codigo}",
    response_model=BarrioResponse,
    summary="Modificar un barrio",
    description="Para dar de baja un barrio se usa `activo: false`. **Nada se borra**.",
)
async def actualizar_barrio(
    codigo: str, payload: BarrioUpdate, admin: AdminDep, service: CatalogServiceDep
) -> BarrioResponse:
    barrio = await service.actualizar_barrio(
        codigo,
        nombre=payload.nombre,
        zona=payload.zona,
        metadatos=payload.metadatos,
        activo=payload.activo,
    )
    return BarrioResponse.of(barrio)


# ----------------------------------------------------------------------
# Catalogos genericos
# ----------------------------------------------------------------------
@router.get(
    "/catalogos",
    response_model=list[str],
    summary="Listar los catalogos disponibles",
    description="Los nombres de catalogo que existen hoy, para descubrirlos sin adivinar.",
)
async def listar_catalogos(caller: CallerDep, service: CatalogServiceDep) -> list[str]:
    return await service.listar_catalogos()


@router.get(
    "/catalogos/{catalogo}/items",
    response_model=list[ItemDeCatalogoResponse],
    summary="Listar los items de un catalogo",
    description=(
        "Las listas de referencia que mas de un modulo necesita escribir igual: "
        "categorias de reclamo, tipos de documento, prioridades.\n\n"
        "`orden` existe para que todos los modulos las muestren en el mismo orden."
    ),
)
async def listar_items(
    catalogo: str,
    caller: CallerDep,
    service: CatalogServiceDep,
    solo_activos: bool = Query(default=False, alias="soloActivos"),
) -> list[ItemDeCatalogoResponse]:
    items = await service.listar_items(catalogo, solo_activos=solo_activos)
    return [ItemDeCatalogoResponse.of(i) for i in items]


@router.post(
    "/catalogos/{catalogo}/items",
    response_model=ItemDeCatalogoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Agregar un item a un catalogo",
    description="Si el catalogo no existia, se crea con este primer item.",
)
async def crear_item(
    catalogo: str, payload: ItemDeCatalogoCreate, admin: AdminDep, service: CatalogServiceDep
) -> ItemDeCatalogoResponse:
    item = await service.crear_item(
        catalogo=catalogo,
        codigo=payload.codigo,
        nombre=payload.nombre,
        descripcion=payload.descripcion,
        orden=payload.orden,
        metadatos=payload.metadatos,
    )
    return ItemDeCatalogoResponse.of(item)


@router.patch(
    "/catalogos/{catalogo}/items/{codigo}",
    response_model=ItemDeCatalogoResponse,
    summary="Modificar un item de catalogo",
)
async def actualizar_item(
    catalogo: str,
    codigo: str,
    payload: ItemDeCatalogoUpdate,
    admin: AdminDep,
    service: CatalogServiceDep,
) -> ItemDeCatalogoResponse:
    item = await service.actualizar_item(
        catalogo,
        codigo,
        nombre=payload.nombre,
        descripcion=payload.descripcion,
        orden=payload.orden,
        metadatos=payload.metadatos,
        activo=payload.activo,
    )
    return ItemDeCatalogoResponse.of(item)
