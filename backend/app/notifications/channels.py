"""Adaptadores de canal de notificacion.

Cada canal implementa la misma interfaz, asi el servicio de notificaciones no
sabe si esta mandando un mail o dejando un aviso in-app. Los canales SMS y PUSH
quedan simulados: el enunciado no exige proveedores reales y el registro en el
historial es identico, con lo cual el flujo se puede demostrar completo.
"""

from __future__ import annotations

import asyncio
import smtplib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Any

import structlog

from app.core.config import settings
from app.models.notifications import Channel

logger = structlog.get_logger(__name__)


@dataclass
class SendResult:
    delivered: bool
    provider_response: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class ChannelAdapter(ABC):
    channel: Channel

    @abstractmethod
    async def send(self, *, recipient: str, subject: str, body: str) -> SendResult: ...


class EmailAdapter(ChannelAdapter):
    """Envio por SMTP.

    Sin `SMTP_HOST` configurado no falla: registra el envio como simulado. Eso
    permite correr la plataforma completa en desarrollo y en la defensa del TPO
    sin depender de un servidor de correo.
    """

    channel = Channel.EMAIL

    async def send(self, *, recipient: str, subject: str, body: str) -> SendResult:
        if not settings.smtp_host:
            logger.info("email_simulated", recipient=recipient, subject=subject)
            return SendResult(
                delivered=True,
                provider_response={
                    "simulated": True,
                    "reason": "SMTP_HOST no configurado",
                },
            )

        message = EmailMessage()
        message["From"] = settings.smtp_from
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)

        try:
            # smtplib es bloqueante: se corre en un thread para no frenar el loop.
            await asyncio.to_thread(self._send_sync, message)
        except Exception as exc:
            logger.warning("email_failed", recipient=recipient, error=str(exc))
            return SendResult(
                delivered=False,
                provider_response={"host": settings.smtp_host},
                error=f"{type(exc).__name__}: {exc}",
            )

        logger.info("email_sent", recipient=recipient, subject=subject)
        return SendResult(delivered=True, provider_response={"host": settings.smtp_host})

    def _send_sync(self, message: EmailMessage) -> None:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as client:
            if settings.smtp_use_tls:
                client.starttls()
            if settings.smtp_user and settings.smtp_password:
                client.login(settings.smtp_user, settings.smtp_password)
            client.send_message(message)


class InAppAdapter(ChannelAdapter):
    """Aviso dentro del panel.

    No tiene I/O externo: la propia fila de `notifications` es la bandeja, y el
    FE la lee filtrando por destinatario. Por eso siempre se considera entregado.
    """

    channel = Channel.IN_APP

    async def send(self, *, recipient: str, subject: str, body: str) -> SendResult:
        return SendResult(delivered=True, provider_response={"stored": True})


class SimulatedAdapter(ChannelAdapter):
    """Canal simulado para SMS y PUSH."""

    def __init__(self, channel: Channel) -> None:
        self.channel = channel

    async def send(self, *, recipient: str, subject: str, body: str) -> SendResult:
        logger.info(
            "notification_simulated",
            channel=self.channel.value,
            recipient=recipient,
            preview=body[:120],
        )
        return SendResult(
            delivered=True,
            provider_response={"simulated": True, "channel": self.channel.value},
        )


class ChannelRegistry:
    """Resuelve el adaptador de cada canal."""

    def __init__(self, adapters: dict[Channel, ChannelAdapter] | None = None) -> None:
        self._adapters: dict[Channel, ChannelAdapter] = adapters or {
            Channel.EMAIL: EmailAdapter(),
            Channel.IN_APP: InAppAdapter(),
            Channel.SMS: SimulatedAdapter(Channel.SMS),
            Channel.PUSH: SimulatedAdapter(Channel.PUSH),
        }

    def get(self, channel: Channel) -> ChannelAdapter:
        adapter = self._adapters.get(channel)
        if adapter is None:
            raise KeyError(f"No hay adaptador registrado para el canal {channel}.")
        return adapter

    def override(self, channel: Channel, adapter: ChannelAdapter) -> None:
        """Punto de inyeccion para los tests."""
        self._adapters[channel] = adapter
