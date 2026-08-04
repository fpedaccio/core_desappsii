"""Manejo centralizado de errores.

Toda la API responde errores con la misma forma, sin filtrar detalles internos:

    {"code": "...", "message": "...", "details": [...], "traceId": "..."}

Los servicios (capa de negocio) levantan estas excepciones sin conocer HTTP;
la traduccion a codigos de estado ocurre una sola vez, en los handlers de abajo.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.core.context import get_trace_id

logger = structlog.get_logger(__name__)


class AppError(Exception):
    """Raiz de los errores de dominio del Core."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "APP_ERROR"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or []
        if code:
            self.code = code

    def to_payload(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
            "traceId": get_trace_id(),
        }


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "NOT_FOUND"


class ConflictError(AppError):
    """Choque con el estado actual: unicidad, transicion de estado invalida."""

    status_code = status.HTTP_409_CONFLICT
    code = "CONFLICT"


class ValidationError(AppError):
    status_code = 422
    code = "VALIDATION_ERROR"


class ContractViolationError(ValidationError):
    """El payload del evento no cumple el JSON Schema de su version."""

    code = "SCHEMA_VIOLATION"


class UnauthorizedError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "UNAUTHORIZED"


class ForbiddenError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "FORBIDDEN"


class ExternalUnavailableError(AppError):
    """Dependencia externa caida (broker, SMTP, otro modulo).

    Se responde 503 y no 500: el pedido puede reintentarse. Es la traduccion
    de "los modulos deberan soportar la indisponibilidad temporal de otros
    componentes" a la capa HTTP.
    """

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "SERVICE_UNAVAILABLE"


def register_exception_handlers(app: FastAPI) -> None:
    """Instala los handlers globales. Se llama una sola vez, en el app factory."""

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        logger.info("app_error", code=exc.code, message=exc.message, details=exc.details)
        return JSONResponse(status_code=exc.status_code, content=exc.to_payload())

    @app.exception_handler(RequestValidationError)
    async def _request_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {
                "field": ".".join(str(part) for part in err["loc"][1:]) or ".".join(
                    str(part) for part in err["loc"]
                ),
                "message": err["msg"],
                "type": err["type"],
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "code": "VALIDATION_ERROR",
                "message": "La solicitud tiene campos invalidos.",
                "details": details,
                "traceId": get_trace_id(),
            },
        )

    @app.exception_handler(IntegrityError)
    async def _integrity(_: Request, exc: IntegrityError) -> JSONResponse:
        # Una violacion de unicidad es un conflicto de negocio, no un 500.
        logger.warning("integrity_error", error=str(exc.orig))
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "code": "CONFLICT",
                "message": "La operacion viola una restriccion de integridad.",
                "details": [],
                "traceId": get_trace_id(),
            },
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        # Ultimo cerco: se loguea completo del lado del servidor y se responde
        # una forma generica, para no exponer internals al cliente.
        logger.exception("unhandled_error", error=str(exc))
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "code": "INTERNAL_ERROR",
                "message": "Ocurrio un error inesperado.",
                "details": [],
                "traceId": get_trace_id(),
            },
        )
