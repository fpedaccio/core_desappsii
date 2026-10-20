"""La politica de reintentos, detras de una interfaz.

**Por que existe este archivo.** La regla de cuanto esperar antes del proximo
intento estaba escrita dos veces, identica, en `event_hub_service` y en
`delivery_service`:

    def _delay_for(attempt: int) -> int:
        delays = settings.retry_delays or [5]
        return delays[min(max(attempt, 1), len(delays)) - 1]

Que estuviera duplicada no es solo repeticion: significa que **cambiar la
politica obliga a modificar los dos servicios**, y que nada garantiza que sigan
de acuerdo. Es una violacion del principio abierto/cerrado — para extender el
comportamiento hay que editar codigo existente — y el dia que alguien agregue
una tercera politica (backoff exponencial, jitter) la va a tener que escribir
en los dos lados otra vez.

Aca la politica pasa a ser un objeto con una interfaz (Strategy). Los servicios
reciben una `RetryPolicy` y no saben como calcula: para agregar una nueva se
escribe una clase, no se toca ningun servicio.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.core.config import settings


class RetryPolicy(ABC):
    """Cuanto esperar antes del proximo intento, y cuando dejar de intentar."""

    @abstractmethod
    def delay_for(self, attempt: int) -> int:
        """Segundos a esperar antes del intento numero `attempt` (base 1)."""

    def exhausted(self, attempt: int, max_attempts: int) -> bool:
        """Si ya no quedan intentos. Comun a todas las politicas."""
        return attempt >= max_attempts


class TieredBackoff(RetryPolicy):
    """Escalones fijos, tomados de `RETRY_DELAYS`.

    Es la politica que el Core usa hoy, y la que hace posible el backoff sin
    ningun proceso durmiendo: cada escalon es una cola de RabbitMQ con su
    `x-message-ttl`, asi que el que espera es el broker.

    Si se piden mas intentos que escalones configurados, **se repite el
    ultimo**. Preferimos eso a fallar: `maxAttempts` lo elige cada modulo en su
    suscripcion y no tiene por que conocer nuestra lista de escalones.
    """

    def __init__(self, delays: list[int] | None = None) -> None:
        self._delays = list(delays) if delays else list(settings.retry_delays) or [5]

    @property
    def tiers(self) -> list[int]:
        return list(self._delays)

    def delay_for(self, attempt: int) -> int:
        indice = min(max(attempt, 1), len(self._delays)) - 1
        return self._delays[indice]


def default_retry_policy() -> RetryPolicy:
    """La politica configurada. Unico lugar donde se decide cual se usa."""
    return TieredBackoff()
