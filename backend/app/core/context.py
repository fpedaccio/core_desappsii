"""Contexto de la request/mensaje en curso.

El `traceId` viaja por HTTP (header `X-Trace-Id`), por los logs y por el
`event_log`, de modo que una journey completa del ciudadano se puede seguir
de punta a punta entre modulos.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar

_trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)
_actor: ContextVar[str | None] = ContextVar("actor", default=None)

TRACE_HEADER = "X-Trace-Id"


def new_trace_id() -> str:
    return str(uuid.uuid4())


def set_trace_id(value: str | None) -> str:
    trace_id = value or new_trace_id()
    _trace_id.set(trace_id)
    return trace_id


def get_trace_id() -> str:
    """Devuelve el trace en curso, creando uno si el codigo corre fuera de una request."""
    current = _trace_id.get()
    if current is None:
        current = new_trace_id()
        _trace_id.set(current)
    return current


def set_actor(value: str | None) -> None:
    _actor.set(value)


def get_actor() -> str | None:
    return _actor.get()
