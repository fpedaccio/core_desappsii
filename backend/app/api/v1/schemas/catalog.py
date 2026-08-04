"""DTOs de los catalogos globales."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import EmailStr, Field

from app.api.v1.schemas.common import CamelModel
from app.models.catalog import Barrio, CatalogItem, CatalogType, Dependencia, Zona


class DependenciaResponse(CamelModel):
    id: uuid.UUID
    code: str
    name: str
    description: str
    parent_id: uuid.UUID | None
    contact_email: str | None
    active: bool

    @classmethod
    def of(cls, dependencia: Dependencia) -> DependenciaResponse:
        return cls.model_validate(dependencia)


class DependenciaCreate(CamelModel):
    code: str = Field(min_length=2, max_length=60, examples=["OBRAS_PUBLICAS"])
    name: str = Field(min_length=2, max_length=160, examples=["Obras Publicas"])
    description: str = ""
    parent_code: str | None = None
    contact_email: EmailStr | None = None


class DependenciaUpdate(CamelModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = None
    contact_email: EmailStr | None = None
    active: bool | None = None


class ZonaResponse(CamelModel):
    id: uuid.UUID
    code: str
    name: str
    description: str
    active: bool

    @classmethod
    def of(cls, zona: Zona) -> ZonaResponse:
        return cls.model_validate(zona)


class ZonaCreate(CamelModel):
    code: str = Field(min_length=2, max_length=60, examples=["ZONA_NORTE"])
    name: str = Field(min_length=2, max_length=160)
    description: str = ""


class ZonaUpdate(CamelModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = None
    active: bool | None = None


class BarrioResponse(CamelModel):
    id: uuid.UUID
    code: str
    name: str
    zona_id: uuid.UUID | None
    zona_code: str | None
    postal_code: str | None
    active: bool

    @classmethod
    def of(cls, barrio: Barrio) -> BarrioResponse:
        return cls(
            id=barrio.id,
            code=barrio.code,
            name=barrio.name,
            zona_id=barrio.zona_id,
            zona_code=barrio.zona.code if barrio.zona else None,
            postal_code=barrio.postal_code,
            active=barrio.active,
        )


class BarrioCreate(CamelModel):
    code: str = Field(min_length=2, max_length=60, examples=["PALERMO"])
    name: str = Field(min_length=2, max_length=160)
    zona_code: str | None = None
    postal_code: str | None = Field(default=None, max_length=20)


class BarrioUpdate(CamelModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    zona_code: str | None = None
    postal_code: str | None = Field(default=None, max_length=20)
    active: bool | None = None


class CatalogTypeResponse(CamelModel):
    id: uuid.UUID
    code: str
    name: str
    description: str
    owner_module: str

    @classmethod
    def of(cls, catalog_type: CatalogType) -> CatalogTypeResponse:
        return cls.model_validate(catalog_type)


class CatalogTypeCreate(CamelModel):
    code: str = Field(min_length=2, max_length=60, examples=["CATEGORIA_RECLAMO"])
    name: str = Field(min_length=2, max_length=160)
    description: str = ""
    owner_module: str = "core"


class CatalogItemResponse(CamelModel):
    id: uuid.UUID
    catalog_type_id: uuid.UUID
    code: str
    label: str
    parent_id: uuid.UUID | None
    sort_order: int
    attributes: dict[str, Any]
    active: bool

    @classmethod
    def of(cls, item: CatalogItem) -> CatalogItemResponse:
        return cls.model_validate(item)


class CatalogItemCreate(CamelModel):
    code: str = Field(min_length=1, max_length=80, examples=["BACHE"])
    label: str = Field(min_length=1, max_length=200, examples=["Bache en la calzada"])
    parent_code: str | None = None
    sort_order: int = 0
    attributes: dict[str, Any] = Field(
        default_factory=dict,
        description="Atributos libres del item, por ejemplo {\"slaHoras\": 72}.",
    )


class CatalogItemUpdate(CamelModel):
    label: str | None = Field(default=None, min_length=1, max_length=200)
    sort_order: int | None = None
    attributes: dict[str, Any] | None = None
    active: bool | None = None
