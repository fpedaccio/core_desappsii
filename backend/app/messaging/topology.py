"""Descripcion declarativa de la topologia de RabbitMQ.

La topologia se *deriva del registry*: no hay colas hardcodeadas por modulo.
Cuando un equipo se da de alta y declara sus suscripciones, el Core recalcula
esta especificacion y la aplica sobre el broker.

    publishers ──► muni.inbox (fanout) ──► core.inbox
                                               │
                                        [validar + persistir + rutear]
                                               ▼
                                      muni.events (topic, rk = nombre de cola)
                                               │
                                     ┌─────────┴─────────┐
                                     ▼                   ▼
                                  q.obras             q.rentas
                                     │ el consumidor rechaza el mensaje
                                     ▼
                      muni.retry.5s ──► q.retry.5s ─(TTL)─► muni.events
                      muni.retry.30s ─► q.retry.30s ─(TTL)─► muni.events
                                     │ agotados los reintentos
                                     ▼
                              muni.dlx ──► q.dlq ──► [dead_letters]

La routing key que usa el hub es **el nombre de la cola destino**. Eso mantiene
el ruteo explicito: el Core decide a quien le toca cada evento leyendo las
suscripciones activas, en vez de delegarlo a patrones de routing key.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.config import settings


@dataclass(frozen=True)
class ExchangeSpec:
    name: str
    type: str = "topic"
    durable: bool = True


@dataclass(frozen=True)
class QueueSpec:
    name: str
    durable: bool = True
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BindingSpec:
    queue: str
    exchange: str
    routing_key: str = "#"


@dataclass(frozen=True)
class Topology:
    exchanges: tuple[ExchangeSpec, ...] = ()
    queues: tuple[QueueSpec, ...] = ()
    bindings: tuple[BindingSpec, ...] = ()

    def merge(self, other: Topology) -> Topology:
        """Une dos topologias sin duplicar, respetando el orden de aparicion."""
        return Topology(
            exchanges=_dedupe(self.exchanges + other.exchanges, key=lambda e: e.name),
            queues=_dedupe(self.queues + other.queues, key=lambda q: q.name),
            bindings=_dedupe(
                self.bindings + other.bindings,
                key=lambda b: (b.queue, b.exchange, b.routing_key),
            ),
        )


def _dedupe(items: tuple, key) -> tuple:
    seen: set = set()
    out = []
    for item in items:
        marker = key(item)
        if marker not in seen:
            seen.add(marker)
            out.append(item)
    return tuple(out)


def retry_tier_name(delay_seconds: int) -> str:
    """Nombre legible del escalon de reintento: 5 -> '5s', 120 -> '2m'."""
    if delay_seconds < 60:
        return f"{delay_seconds}s"
    if delay_seconds % 60 == 0 and delay_seconds < 3600:
        return f"{delay_seconds // 60}m"
    return f"{delay_seconds}s"


def retry_exchange_for(delay_seconds: int) -> str:
    return f"{settings.exchange_retry}.{retry_tier_name(delay_seconds)}"


def retry_queue_for(delay_seconds: int) -> str:
    return f"q.retry.{retry_tier_name(delay_seconds)}"


def base_topology() -> Topology:
    """Exchanges y colas de infraestructura, independientes del registry."""
    exchanges = [
        # Fanout: cualquier modulo publica sin conocer el ruteo. El unico
        # consumidor es el Core.
        ExchangeSpec(settings.exchange_inbox, "fanout"),
        ExchangeSpec(settings.exchange_events, "topic"),
        ExchangeSpec(settings.exchange_dlx, "fanout"),
    ]
    queues = [
        # Durable: si el Core esta caido, los publishers siguen publicando sin
        # error y los mensajes esperan aca. Nada se pierde.
        QueueSpec(
            settings.queue_inbox, arguments={"x-dead-letter-exchange": settings.exchange_dlx}
        ),
        QueueSpec(settings.queue_dlq),
    ]
    bindings = [
        BindingSpec(settings.queue_inbox, settings.exchange_inbox),
        BindingSpec(settings.queue_dlq, settings.exchange_dlx),
    ]

    # Un exchange y una cola por escalon de backoff. Usar una cola por escalon
    # (en vez de una sola con TTL por mensaje) evita que un mensaje con espera
    # larga bloquee la cabeza de la cola y retrase a los de espera corta.
    for delay in settings.retry_delays:
        exchange = retry_exchange_for(delay)
        queue = retry_queue_for(delay)
        exchanges.append(ExchangeSpec(exchange, "fanout"))
        queues.append(
            QueueSpec(
                queue,
                arguments={
                    "x-message-ttl": delay * 1000,
                    # Al vencer el TTL vuelve a muni.events conservando la
                    # routing key original, o sea la cola destino.
                    "x-dead-letter-exchange": settings.exchange_events,
                },
            )
        )
        bindings.append(BindingSpec(queue, exchange))

    return Topology(tuple(exchanges), tuple(queues), tuple(bindings))


def consumer_topology(queue_names: list[str]) -> Topology:
    """Colas de los modulos consumidores, derivadas de las suscripciones activas."""
    queues = tuple(
        QueueSpec(name, arguments={"x-dead-letter-exchange": settings.exchange_dlx})
        for name in queue_names
    )
    bindings = tuple(
        BindingSpec(name, settings.exchange_events, routing_key=name) for name in queue_names
    )
    return Topology(queues=queues, bindings=bindings)


def full_topology(queue_names: list[str]) -> Topology:
    """Topologia completa: infraestructura + colas de consumidores."""
    return base_topology().merge(consumer_topology(sorted(set(queue_names))))
