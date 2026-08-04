"""Logging estructurado con structlog, con el traceId inyectado automaticamente."""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from app.core.config import settings
from app.core.context import get_actor, get_trace_id


def _add_context(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    event_dict["trace_id"] = get_trace_id()
    event_dict["module"] = settings.module_name
    actor = get_actor()
    if actor:
        event_dict["actor"] = actor
    return event_dict


# Librerias que en DEBUG emiten una linea por operacion de I/O y tapan por
# completo los logs de la aplicacion.
NOISY_LOGGERS = (
    "aiosqlite",
    "asyncio",
    "aiormq",
    "aio_pika",
    "sqlalchemy.engine",
    "sqlalchemy.pool",
    "httpx",
    "httpcore",
)


def configure_logging() -> None:
    level = logging.DEBUG if settings.debug else logging.INFO
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)

    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    # Consola legible en desarrollo, JSON en produccion (para agregadores de logs).
    renderer = (
        structlog.processors.JSONRenderer()
        if settings.is_production
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _add_context,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
