"""Interfaz del broker.

Los servicios de negocio dependen de esta abstraccion, nunca de aio-pika. Eso
permite (a) testear el hub completo sin un RabbitMQ levantado y (b) cambiar de
plataforma de mensajeria sin tocar la capa de negocio.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

HEADER_ATTEMPT = "x-core-attempt"
HEADER_TARGET = "x-core-target-module"
HEADER_EVENT_ID = "x-core-event-id"
HEADER_TRACE_ID = "x-core-trace-id"
HEADER_ERROR = "x-core-last-error"


@dataclass(frozen=True)
class OutboundMessage:
    """Mensaje que el Core publica."""

    exchange: str
    routing_key: str
    body: dict[str, Any]
    headers: dict[str, Any] = field(default_factory=dict)
    message_id: str | None = None
    expiration_ms: int | None = None

    def encoded(self) -> bytes:
        return json.dumps(self.body, ensure_ascii=False, default=str).encode("utf-8")


@dataclass
class InboundMessage:
    """Mensaje que el Core recibe. `raw` se conserva para poder guardar en la
    DLQ incluso cuerpos que no son JSON valido."""

    queue: str
    routing_key: str
    raw: bytes
    headers: dict[str, Any] = field(default_factory=dict)
    redelivered: bool = False

    def json(self) -> Any:
        """Parsea el cuerpo. Levanta `ValueError` si no es JSON."""
        return json.loads(self.raw.decode("utf-8"))

    @property
    def text(self) -> str:
        return self.raw.decode("utf-8", errors="replace")

    @property
    def attempt(self) -> int:
        try:
            return int(self.headers.get(HEADER_ATTEMPT, 0))
        except (TypeError, ValueError):
            return 0


MessageHandler = Callable[[InboundMessage], Awaitable[None]]


class Broker(ABC):
    """Puerto de mensajeria.

    Contrato de `consume`: si el handler termina sin excepcion, el mensaje se
    reconoce (ack). Si levanta, el mensaje se rechaza **sin requeue**, para que
    la cadena de reintentos y la DLQ las gobierne el Core y no el broker.
    """

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    async def declare(self, topology: Any) -> None:
        """Aplica una `Topology` de forma idempotente."""

    @abstractmethod
    async def publish(self, message: OutboundMessage) -> None: ...

    @abstractmethod
    async def consume(self, queue: str, handler: MessageHandler, prefetch: int = 16) -> None: ...

    @abstractmethod
    async def healthy(self) -> bool: ...

    @property
    @abstractmethod
    def is_connected(self) -> bool: ...
