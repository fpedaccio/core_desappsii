"""Adaptador de RabbitMQ sobre aio-pika.

Unica pieza del proyecto que conoce AMQP. Todo lo demas habla con `Broker`.
"""

from __future__ import annotations

import aio_pika
import structlog
from aio_pika.abc import AbstractRobustChannel, AbstractRobustConnection

from app.core.config import settings
from app.messaging.broker import Broker, InboundMessage, MessageHandler, OutboundMessage
from app.messaging.topology import Topology

logger = structlog.get_logger(__name__)

_EXCHANGE_TYPES = {
    "topic": aio_pika.ExchangeType.TOPIC,
    "fanout": aio_pika.ExchangeType.FANOUT,
    "direct": aio_pika.ExchangeType.DIRECT,
}


class RabbitMQBroker(Broker):
    def __init__(self, url: str | None = None) -> None:
        self._url = url or settings.rabbitmq_url
        self._connection: AbstractRobustConnection | None = None
        self._channel: AbstractRobustChannel | None = None
        self._exchanges: dict[str, aio_pika.abc.AbstractExchange] = {}

    async def connect(self) -> None:
        if self._connection is not None and not self._connection.is_closed:
            return
        # `connect_robust` reconecta solo si el broker se reinicia.
        self._connection = await aio_pika.connect_robust(self._url)
        self._channel = await self._connection.channel(publisher_confirms=True)  # type: ignore[assignment]
        logger.info("broker_connected", url=_redact(self._url))

    async def close(self) -> None:
        if self._connection is not None and not self._connection.is_closed:
            await self._connection.close()
        self._connection = None
        self._channel = None
        self._exchanges.clear()

    @property
    def is_connected(self) -> bool:
        return self._connection is not None and not self._connection.is_closed

    async def healthy(self) -> bool:
        return self.is_connected and self._channel is not None and not self._channel.is_closed

    async def declare(self, topology: Topology) -> None:
        """Declara exchanges, colas y bindings. Idempotente: se puede reaplicar."""
        channel = await self._require_channel()

        for spec in topology.exchanges:
            exchange = await channel.declare_exchange(
                spec.name,
                _EXCHANGE_TYPES.get(spec.type, aio_pika.ExchangeType.TOPIC),
                durable=spec.durable,
            )
            self._exchanges[spec.name] = exchange

        declared_queues: dict[str, aio_pika.abc.AbstractQueue] = {}
        for spec in topology.queues:
            declared_queues[spec.name] = await channel.declare_queue(
                spec.name, durable=spec.durable, arguments=spec.arguments or None
            )

        for spec in topology.bindings:
            queue = declared_queues.get(spec.queue) or await channel.declare_queue(
                spec.queue, durable=True
            )
            await queue.bind(spec.exchange, routing_key=spec.routing_key)

        logger.info(
            "topology_declared",
            exchanges=len(topology.exchanges),
            queues=len(topology.queues),
            bindings=len(topology.bindings),
        )

    async def publish(self, message: OutboundMessage) -> None:
        channel = await self._require_channel()
        exchange = self._exchanges.get(message.exchange)
        if exchange is None:
            exchange = await channel.get_exchange(message.exchange, ensure=False)
            self._exchanges[message.exchange] = exchange

        amqp_message = aio_pika.Message(
            body=message.encoded(),
            content_type="application/json",
            # Persistente: los mensajes sobreviven un reinicio del broker.
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            headers=message.headers or {},
            message_id=message.message_id,
            expiration=(message.expiration_ms / 1000) if message.expiration_ms else None,
        )
        await exchange.publish(amqp_message, routing_key=message.routing_key)

    async def consume(self, queue: str, handler: MessageHandler, prefetch: int = 16) -> None:
        channel = await self._require_channel()
        await channel.set_qos(prefetch_count=prefetch)
        amqp_queue = await channel.declare_queue(queue, durable=True, passive=True)

        async def _on_message(message: aio_pika.abc.AbstractIncomingMessage) -> None:
            inbound = InboundMessage(
                queue=queue,
                routing_key=message.routing_key or "",
                raw=message.body,
                headers=dict(message.headers or {}),
                redelivered=bool(message.redelivered),
            )
            try:
                await handler(inbound)
                await message.ack()
            except Exception as exc:
                # requeue=False a proposito: la cadena de reintentos y la DLQ las
                # gobierna el Core, no el redelivery del broker.
                logger.exception("message_handler_failed", queue=queue, error=str(exc))
                await message.nack(requeue=False)

        await amqp_queue.consume(_on_message)
        logger.info("consumer_started", queue=queue, prefetch=prefetch)

    async def _require_channel(self) -> AbstractRobustChannel:
        if self._channel is None or self._channel.is_closed:
            await self.connect()
        assert self._channel is not None  # noqa: S101 - garantizado por connect()
        return self._channel


def _redact(url: str) -> str:
    """Oculta la contrasena antes de loguear la URL del broker."""
    if "@" not in url:
        return url
    scheme, _, rest = url.partition("://")
    _, _, host = rest.partition("@")
    return f"{scheme}://***@{host}"
