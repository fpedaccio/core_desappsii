"""Broker en memoria.

Cumple el mismo contrato que el adaptador de RabbitMQ y ademas rutea de verdad
(fanout y topic con comodines `*`/`#`), asi los tests del hub verifican que un
evento llego a la cola correcta sin depender de infraestructura externa.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from app.messaging.broker import (
    Broker,
    InboundMessage,
    MessageHandler,
    OutboundMessage,
)
from app.messaging.topology import Topology


class FakeBroker(Broker):
    def __init__(self, *, healthy: bool = True, fail_on_publish: bool = False) -> None:
        self.published: list[OutboundMessage] = []
        self.queues: dict[str, list[OutboundMessage]] = defaultdict(list)
        self.declared: Topology | None = None
        self.handlers: dict[str, MessageHandler] = {}
        self._exchange_types: dict[str, str] = {}
        self._bindings: list[tuple[str, str, str]] = []  # (queue, exchange, routing_key)
        self._connected = False
        self._healthy = healthy
        self._fail_on_publish = fail_on_publish

    # -- ciclo de vida -----------------------------------------------------
    async def connect(self) -> None:
        self._connected = True

    async def close(self) -> None:
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def healthy(self) -> bool:
        return self._healthy and self._connected

    # -- topologia ---------------------------------------------------------
    async def declare(self, topology: Any) -> None:
        self.declared = topology
        for exchange in topology.exchanges:
            self._exchange_types[exchange.name] = exchange.type
        for queue in topology.queues:
            self.queues.setdefault(queue.name, [])
        for binding in topology.bindings:
            entry = (binding.queue, binding.exchange, binding.routing_key)
            if entry not in self._bindings:
                self._bindings.append(entry)

    # -- publicacion -------------------------------------------------------
    async def publish(self, message: OutboundMessage) -> None:
        if self._fail_on_publish:
            raise ConnectionError("FakeBroker configurado para fallar al publicar")
        self.published.append(message)
        for queue in self._matching_queues(message.exchange, message.routing_key):
            self.queues[queue].append(message)

    def _matching_queues(self, exchange: str, routing_key: str) -> list[str]:
        exchange_type = self._exchange_types.get(exchange, "topic")
        matched = []
        for queue, bound_exchange, pattern in self._bindings:
            if bound_exchange != exchange:
                continue
            if exchange_type == "fanout" or _topic_matches(pattern, routing_key):
                matched.append(queue)
        return matched

    # -- consumo -----------------------------------------------------------
    async def consume(self, queue: str, handler: MessageHandler, prefetch: int = 16) -> None:
        self.handlers[queue] = handler

    async def deliver(self, queue: str, message: InboundMessage) -> None:
        """Entrega un mensaje al handler registrado. Lo usan los tests."""
        handler = self.handlers.get(queue)
        if handler is None:
            raise AssertionError(f"No hay consumidor registrado para la cola {queue!r}")
        await handler(message)

    async def drain(self, queue: str) -> int:
        """Entrega al handler todo lo encolado y devuelve cuantos proceso."""
        pending, self.queues[queue] = self.queues[queue], []
        for message in pending:
            await self.deliver(
                queue,
                InboundMessage(
                    queue=queue,
                    routing_key=message.routing_key,
                    raw=message.encoded(),
                    headers=dict(message.headers),
                ),
            )
        return len(pending)

    # -- utilidades para tests --------------------------------------------
    def messages_for(self, queue: str) -> list[dict[str, Any]]:
        return [message.body for message in self.queues.get(queue, [])]

    def routing_keys(self, exchange: str | None = None) -> list[str]:
        return [
            message.routing_key
            for message in self.published
            if exchange is None or message.exchange == exchange
        ]

    def reset(self) -> None:
        self.published.clear()
        self.queues.clear()


def _topic_matches(pattern: str, routing_key: str) -> bool:
    """Semantica de routing key de AMQP: `*` = un segmento, `#` = cero o mas."""
    if pattern in {"#", ""}:
        return True
    regex = "^"
    for index, segment in enumerate(pattern.split(".")):
        if index:
            regex += r"\."
        if segment == "*":
            regex += r"[^.]+"
        elif segment == "#":
            # `#` absorbe el resto, incluido el punto que lo precede.
            regex = regex[:-2] + r"(\..*)?" if index else regex + r".*"
            return re.match(regex + "$", routing_key) is not None
        else:
            regex += re.escape(segment)
    return re.match(regex + "$", routing_key) is not None
