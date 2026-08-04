"""Instancia unica de broker que usa la aplicacion.

Arrancar sin broker es un estado valido: la API sigue sirviendo consultas,
`/health/ready` reporta el broker caido y las publicaciones fallan con 503
(`ExternalUnavailableError`) en vez de tirar el proceso. Es la regla 7 del
enunciado aplicada al propio Core.
"""

from __future__ import annotations

import structlog

from app.core.config import settings
from app.messaging.broker import Broker
from app.messaging.rabbitmq import RabbitMQBroker

logger = structlog.get_logger(__name__)

_broker: Broker | None = None


MEMORY_URL = "memory://"
"""Broker en memoria, para desarrollo local sin RabbitMQ instalado.

El ruteo funciona de verdad (exchanges, colas, bindings y comodines de routing
key), asi que el hub se puede probar de punta a punta. Lo que no hay es
persistencia entre reinicios ni consumidores externos: para eso, RabbitMQ.
"""


def get_broker() -> Broker:
    global _broker
    if _broker is None:
        if settings.rabbitmq_url.strip().lower().startswith("memory"):
            from app.messaging.fake import FakeBroker

            logger.warning(
                "using_in_memory_broker",
                hint="Modo desarrollo. Configura RABBITMQ_URL con un amqp:// real "
                "para tener persistencia y consumidores externos.",
            )
            _broker = FakeBroker()
        else:
            _broker = RabbitMQBroker()
    return _broker


def set_broker(broker: Broker | None) -> None:
    """Punto de inyeccion para los tests (FakeBroker)."""
    global _broker
    _broker = broker


async def connect_broker() -> bool:
    """Intenta conectar y declarar la topologia base. Devuelve si lo logro."""
    broker = get_broker()
    try:
        await broker.connect()
        return True
    except Exception as exc:
        if settings.broker_required:
            raise
        logger.warning(
            "broker_unavailable_on_startup",
            error=str(exc),
            hint="El Core arranca en modo degradado: la API responde, la "
            "mensajeria queda deshabilitada hasta que el broker vuelva.",
        )
        return False
