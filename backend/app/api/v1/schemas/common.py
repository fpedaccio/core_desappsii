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


class ProblemDetails(CamelModel):
    """Forma unica de todos los errores de la API (RFC 9457 + extensiones del Core)."""

    type: str = Field(examples=["about:blank"])
    title: str = Field(examples=["Unprocessable Entity"])
    status: int = Field(examples=[422])
    detail: str = Field(examples=["La solicitud tiene campos invalidos."])
    instance: str | None = Field(default=None, examples=["/api/v1/events"])
    code: str = Field(examples=["VALIDATION_ERROR"])
    message: str = Field(examples=["La solicitud tiene campos invalidos."])
    details: list[Any]
    trace_id: str | None


ErrorResponse = ProblemDetails

PROBLEM_DESCRIPTIONS: dict[int, str] = {
    401: "No autenticado o token invalido/expirado.",
    403: "Sin permisos para esta operacion, cuenta/modulo inactivo o recurso de otro modulo.",
    404: "Recurso no encontrado o fuera del alcance del modulo autenticado.",
    409: "Conflicto con el estado actual o restriccion de unicidad.",
    412: "Precondicion fallida: el encabezado If-Match no coincide con el ETag actual.",
    422: "Error de validacion en la solicitud (Problem Details RFC 9457).",
}


def problem_responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    """Declara respuestas de error Problem Details (application/problem+json) para OpenAPI."""
    return {
        code: {
            "description": PROBLEM_DESCRIPTIONS.get(code, "Error de la API."),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ProblemDetails"}
                }
            },
        }
        for code in codes
    }


class MessageResponse(CamelModel):
    message: str
