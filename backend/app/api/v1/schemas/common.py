"""Base de los DTOs y envoltorio de paginacion.

La API expone **camelCase** hacia afuera y trabaja en snake_case adentro. La
conversion se hace una sola vez, aca, con un alias generator.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.repositories.base import Page

T = TypeVar("T")


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class PageResponse(CamelModel, Generic[T]):
    """Respuesta paginada. El FE usa `total` y `pages` para armar el paginador."""

    items: list[T]
    total: int
    page: int
    size: int
    pages: int

    @classmethod
    def build(cls, page: Page, mapper: Callable[[Any], T]) -> PageResponse[T]:
        return cls(
            items=[mapper(item) for item in page.items],
            total=page.total,
            page=page.page,
            size=page.size,
            pages=page.pages,
        )


class ErrorResponse(CamelModel):
    """Forma unica de todos los errores de la API."""

    code: str = Field(examples=["SCHEMA_VIOLATION"])
    message: str
    details: list[Any] = Field(default_factory=list)
    trace_id: str | None = None


class MessageResponse(CamelModel):
    message: str
