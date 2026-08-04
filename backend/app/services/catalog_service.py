"""Catalogos globales.

Estos datos los consumen los 9 modulos para hablar del mismo barrio y de la
misma area. Por eso las bajas son logicas (`active=False`) y no fisicas: si se
borrara un barrio, los modulos que lo referencian por id se quedarian con una
referencia colgada que el Core no puede reparar.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models.catalog import Barrio, CatalogItem, CatalogType, Dependencia, Zona
from app.repositories.base import Page
from app.repositories.catalog_repository import (
    BarrioRepository,
    CatalogItemRepository,
    CatalogTypeRepository,
    DependenciaRepository,
    ZonaRepository,
)
from app.services.audit_service import AuditService


class CatalogService:
    def __init__(
        self,
        *,
        dependencia_repo: DependenciaRepository,
        zona_repo: ZonaRepository,
        barrio_repo: BarrioRepository,
        catalog_type_repo: CatalogTypeRepository,
        catalog_item_repo: CatalogItemRepository,
        audit: AuditService,
    ) -> None:
        self.dependencia_repo = dependencia_repo
        self.zona_repo = zona_repo
        self.barrio_repo = barrio_repo
        self.catalog_type_repo = catalog_type_repo
        self.catalog_item_repo = catalog_item_repo
        self.audit = audit

    # ------------------------------------------------------------------
    # Dependencias
    # ------------------------------------------------------------------
    async def search_dependencias(self, **kwargs: Any) -> Page[Dependencia]:
        return await self.dependencia_repo.search(**kwargs)

    async def create_dependencia(
        self,
        *,
        code: str,
        name: str,
        description: str = "",
        parent_code: str | None = None,
        contact_email: str | None = None,
    ) -> Dependencia:
        normalized = _normalize_code(code)
        if await self.dependencia_repo.get_by_code(normalized) is not None:
            raise ConflictError(f"Ya existe la dependencia {normalized}.")

        parent = None
        if parent_code:
            parent = await self.dependencia_repo.get_by_code(_normalize_code(parent_code))
            if parent is None:
                raise ValidationError(f"La dependencia padre {parent_code} no existe.")

        dependencia = Dependencia(
            code=normalized,
            name=name.strip(),
            description=description,
            parent_id=parent.id if parent else None,
            contact_email=contact_email,
        )
        self.dependencia_repo.add(dependencia)
        await self.dependencia_repo.flush()

        self.audit.record(
            action="DEPENDENCIA_CREATED",
            entity_type="Dependencia",
            entity_id=str(dependencia.id),
            summary=f"Dependencia {normalized} creada.",
        )
        return dependencia

    async def update_dependencia(
        self,
        dependencia_id: uuid.UUID,
        *,
        name: str | None = None,
        description: str | None = None,
        contact_email: str | None = None,
        active: bool | None = None,
    ) -> Dependencia:
        dependencia = await self.dependencia_repo.get_required(dependencia_id)
        if name is not None:
            dependencia.name = name.strip()
        if description is not None:
            dependencia.description = description
        if contact_email is not None:
            dependencia.contact_email = contact_email
        if active is not None:
            dependencia.active = active

        self.audit.record(
            action="DEPENDENCIA_UPDATED",
            entity_type="Dependencia",
            entity_id=str(dependencia.id),
            summary=f"Dependencia {dependencia.code} actualizada.",
        )
        return dependencia

    # ------------------------------------------------------------------
    # Zonas
    # ------------------------------------------------------------------
    async def search_zonas(self, **kwargs: Any) -> Page[Zona]:
        return await self.zona_repo.search(**kwargs)

    async def create_zona(self, *, code: str, name: str, description: str = "") -> Zona:
        normalized = _normalize_code(code)
        if await self.zona_repo.get_by_code(normalized) is not None:
            raise ConflictError(f"Ya existe la zona {normalized}.")

        zona = Zona(code=normalized, name=name.strip(), description=description)
        self.zona_repo.add(zona)
        await self.zona_repo.flush()

        self.audit.record(
            action="ZONA_CREATED",
            entity_type="Zona",
            entity_id=str(zona.id),
            summary=f"Zona {normalized} creada.",
        )
        return zona

    async def update_zona(
        self,
        zona_id: uuid.UUID,
        *,
        name: str | None = None,
        description: str | None = None,
        active: bool | None = None,
    ) -> Zona:
        zona = await self.zona_repo.get_required(zona_id)
        if name is not None:
            zona.name = name.strip()
        if description is not None:
            zona.description = description
        if active is not None:
            zona.active = active

        self.audit.record(
            action="ZONA_UPDATED",
            entity_type="Zona",
            entity_id=str(zona.id),
            summary=f"Zona {zona.code} actualizada.",
        )
        return zona

    # ------------------------------------------------------------------
    # Barrios
    # ------------------------------------------------------------------
    async def search_barrios(self, **kwargs: Any) -> Page[Barrio]:
        return await self.barrio_repo.search(**kwargs)

    async def create_barrio(
        self,
        *,
        code: str,
        name: str,
        zona_code: str | None = None,
        postal_code: str | None = None,
    ) -> Barrio:
        normalized = _normalize_code(code)
        if await self.barrio_repo.get_by_code(normalized) is not None:
            raise ConflictError(f"Ya existe el barrio {normalized}.")

        zona = None
        if zona_code:
            zona = await self.zona_repo.get_by_code(_normalize_code(zona_code))
            if zona is None:
                raise ValidationError(f"La zona {zona_code} no existe.")

        barrio = Barrio(
            code=normalized,
            name=name.strip(),
            zona_id=zona.id if zona else None,
            postal_code=postal_code,
        )
        self.barrio_repo.add(barrio)
        await self.barrio_repo.flush()

        self.audit.record(
            action="BARRIO_CREATED",
            entity_type="Barrio",
            entity_id=str(barrio.id),
            summary=f"Barrio {normalized} creado.",
        )
        return barrio

    async def update_barrio(
        self,
        barrio_id: uuid.UUID,
        *,
        name: str | None = None,
        zona_code: str | None = None,
        postal_code: str | None = None,
        active: bool | None = None,
    ) -> Barrio:
        barrio = await self.barrio_repo.get_required(barrio_id)
        if name is not None:
            barrio.name = name.strip()
        if postal_code is not None:
            barrio.postal_code = postal_code
        if active is not None:
            barrio.active = active
        if zona_code is not None:
            zona = await self.zona_repo.get_by_code(_normalize_code(zona_code))
            if zona is None:
                raise ValidationError(f"La zona {zona_code} no existe.")
            barrio.zona_id = zona.id

        self.audit.record(
            action="BARRIO_UPDATED",
            entity_type="Barrio",
            entity_id=str(barrio.id),
            summary=f"Barrio {barrio.code} actualizado.",
        )
        return barrio

    # ------------------------------------------------------------------
    # Catalogos genericos
    # ------------------------------------------------------------------
    async def list_catalog_types(self) -> list[CatalogType]:
        return await self.catalog_type_repo.list_ordered()

    async def create_catalog_type(
        self, *, code: str, name: str, description: str = "", owner_module: str = "core"
    ) -> CatalogType:
        normalized = _normalize_code(code)
        if await self.catalog_type_repo.get_by_code(normalized) is not None:
            raise ConflictError(f"Ya existe el catalogo {normalized}.")

        catalog_type = CatalogType(
            code=normalized,
            name=name.strip(),
            description=description,
            owner_module=owner_module.strip().lower(),
        )
        self.catalog_type_repo.add(catalog_type)
        await self.catalog_type_repo.flush()

        self.audit.record(
            action="CATALOG_TYPE_CREATED",
            entity_type="CatalogType",
            entity_id=str(catalog_type.id),
            summary=f"Catalogo {normalized} creado.",
        )
        return catalog_type

    async def get_catalog_type_by_code(self, code: str) -> CatalogType:
        catalog_type = await self.catalog_type_repo.get_by_code(_normalize_code(code))
        if catalog_type is None:
            raise NotFoundError(f"No existe el catalogo {code}.")
        return catalog_type

    async def search_catalog_items(
        self, *, catalog_code: str, **kwargs: Any
    ) -> Page[CatalogItem]:
        catalog_type = await self.get_catalog_type_by_code(catalog_code)
        return await self.catalog_item_repo.search(catalog_type_id=catalog_type.id, **kwargs)

    async def create_catalog_item(
        self,
        *,
        catalog_code: str,
        code: str,
        label: str,
        parent_code: str | None = None,
        sort_order: int = 0,
        attributes: dict | None = None,
    ) -> CatalogItem:
        catalog_type = await self.get_catalog_type_by_code(catalog_code)
        normalized = _normalize_code(code)

        if await self.catalog_item_repo.get_by_code(catalog_type.id, normalized) is not None:
            raise ConflictError(
                f"El catalogo {catalog_type.code} ya tiene un item {normalized}."
            )

        parent = None
        if parent_code:
            parent = await self.catalog_item_repo.get_by_code(
                catalog_type.id, _normalize_code(parent_code)
            )
            if parent is None:
                raise ValidationError(
                    f"El item padre {parent_code} no existe en {catalog_type.code}."
                )

        item = CatalogItem(
            catalog_type_id=catalog_type.id,
            code=normalized,
            label=label.strip(),
            parent_id=parent.id if parent else None,
            sort_order=sort_order,
            attributes=attributes or {},
        )
        self.catalog_item_repo.add(item)
        await self.catalog_item_repo.flush()

        self.audit.record(
            action="CATALOG_ITEM_CREATED",
            entity_type="CatalogItem",
            entity_id=str(item.id),
            summary=f"Item {normalized} agregado a {catalog_type.code}.",
        )
        return item

    async def update_catalog_item(
        self,
        item_id: uuid.UUID,
        *,
        label: str | None = None,
        sort_order: int | None = None,
        attributes: dict | None = None,
        active: bool | None = None,
    ) -> CatalogItem:
        item = await self.catalog_item_repo.get_required(item_id)
        if label is not None:
            item.label = label.strip()
        if sort_order is not None:
            item.sort_order = sort_order
        if attributes is not None:
            item.attributes = attributes
        if active is not None:
            item.active = active

        self.audit.record(
            action="CATALOG_ITEM_UPDATED",
            entity_type="CatalogItem",
            entity_id=str(item.id),
            summary=f"Item {item.code} actualizado.",
        )
        return item


def _normalize_code(code: str) -> str:
    """Los codigos son identificadores estables: mayusculas, sin espacios."""
    normalized = code.strip().upper().replace(" ", "_")
    if not normalized:
        raise ValidationError("El codigo no puede estar vacio.")
    return normalized
