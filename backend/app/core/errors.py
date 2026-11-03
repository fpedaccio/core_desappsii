"""Manejo centralizado de errores.

Toda la API responde errores como Problem Details (RFC 9457), con
`Content-Type: application/problem+json`, sin filtrar detalles internos:

    {"type": "about:blank", "title": "Not Found", "status": 404,
     "detail": "...", "instance": "/api/v1/...",
     "code": "...", "message": "...", "details": [...], "traceId": "..."}

`type`, `title`, `status`, `detail` e `instance` son los miembros del estandar.
`code`, `message`, `details` y `traceId` son miembros de extension (RFC 9457,
seccion 3.2): es la forma que tenia la API antes y se conserva para no romper a
los clientes (el frontend y los modulos leen `code`, `message` y `details`).
`type` es `about:blank`: el problema no tiene mas semantica que su codigo HTTP,
y el caso puntual lo dice `code`.

Los servicios (capa de negocio) levantan estas excepciones sin conocer HTTP;
la traduccion a codigos de estado ocurre una sola vez, en los handlers de abajo.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.context import get_trace_id

logger = structlog.get_logger(__name__)

PROBLEM_MEDIA_TYPE = "application/problem+json"


def problem_body(
    *,
    status_code: int,
    code: str,
    message: str,
    details: list[Any] | None = None,
    instance: str | None = None,
) -> dict[str, Any]:
    """El cuerpo de un error segun RFC 9457, con las extensiones del Core."""
    try:
        title = HTTPStatus(status_code).phrase
    except ValueError:
        title = "Error"
    body: dict[str, Any] = {
        "type": "about:blank",
        "title": title,
        "status": status_code,
        "detail": message,
    }
    if instance:
        body["instance"] = instance
    body.update(
        {
            "code": code,
            "message": message,
            "details": details or [],
            "traceId": get_trace_id(),
        }
    )
    return body


def problem_response(
    request: Request | None,
    *,
    status_code: int,
    code: str,
    message: str,
    details: list[Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Respuesta de error unica para toda la API (RFC 9457)."""
    return JSONResponse(
        status_code=status_code,
        media_type=PROBLEM_MEDIA_TYPE,
        headers=headers,
        content=problem_body(
            status_code=status_code,
            code=code,
            message=message,
            details=details,
            instance=request.url.path if request is not None else None,
        ),
    )


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

    def to_payload(self, instance: str | None = None) -> dict[str, Any]:
        return problem_body(
            status_code=self.status_code,
            code=self.code,
            message=self.message,
            details=self.details,
            instance=instance,
        )


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "NOT_FOUND"


class ConflictError(AppError):
    """Choque con el estado actual: unicidad, transicion de estado invalida."""

    status_code = status.HTTP_409_CONFLICT
    code = "CONFLICT"


class PreconditionFailedError(AppError):
    """If-Match desactualizado: otro cliente cambio el recurso despues de leerlo."""

    status_code = status.HTTP_412_PRECONDITION_FAILED
    code = "PRECONDITION_FAILED"


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
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        logger.info("app_error", code=exc.code, message=exc.message, details=exc.details)
        return problem_response(
            request,
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=exc.details,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Errores del framework: ruta inexistente (404), metodo no permitido (405).
        # Antes salian como {"detail": "Not Found"}, fuera de la forma comun.
        codes = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}
        message = exc.detail if isinstance(exc.detail, str) else HTTPStatus(exc.status_code).phrase
        return problem_response(
            request,
            status_code=exc.status_code,
            code=codes.get(exc.status_code, "HTTP_ERROR"),
            message=message,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _request_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {
                "field": ".".join(str(part) for part in err["loc"][1:])
                or ".".join(str(part) for part in err["loc"]),
                "message": err["msg"],
                "type": err["type"],
            }
            for err in exc.errors()
        ]
        return problem_response(
            request,
            status_code=422,
            code="VALIDATION_ERROR",
            message="La solicitud tiene campos invalidos.",
            details=details,
        )

    @app.exception_handler(IntegrityError)
    async def _integrity(request: Request, exc: IntegrityError) -> JSONResponse:
        # Una violacion de unicidad es un conflicto de negocio, no un 500.
        logger.warning("integrity_error", error=str(exc.orig))
        return problem_response(
            request,
            status_code=status.HTTP_409_CONFLICT,
            code="CONFLICT",
            message="La operacion viola una restriccion de integridad.",
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Ultimo cerco: se loguea completo del lado del servidor y se responde
        # una forma generica, para no exponer internals al cliente.
        logger.exception("unhandled_error", error=str(exc))
        return problem_response(
            request,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="INTERNAL_ERROR",
            message="Ocurrio un error inesperado.",
        )
