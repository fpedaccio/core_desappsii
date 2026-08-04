"""Monitoreo: salud de los modulos, metricas y dashboards.

El health poller sondea el `health_url` de cada modulo registrado. Es la unica
llamada sincronica que el Core hace hacia afuera, y esta pensada para no
propagar fallas: cada sondeo tiene timeout propio y una excepcion se registra
como `DOWN` en vez de cortar el ciclo (regla 7 del enunciado).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import httpx
import structlog

from app.core.config import settings
from app.core.database import utcnow
from app.messaging.broker import Broker
from app.models.monitoring import HealthCheck, HealthStatus
from app.repositories.contract_repository import ModuleRepository
from app.repositories.event_repository import (
    DeadLetterRepository,
    DeliveryRepository,
    EventLogRepository,
)
from app.repositories.monitoring_repository import HealthCheckRepository
from app.repositories.notification_repository import NotificationRepository

logger = structlog.get_logger(__name__)

DEGRADED_LATENCY_MS = 2000
"""Responde, pero lento: se marca DEGRADED para que se vea en el tablero."""


@dataclass
class ModuleHealth:
    module_name: str
    display_name: str
    status: HealthStatus
    latency_ms: int | None
    http_status: int | None
    error: str | None
    checked_at: datetime | None
    uptime_24h: float


class MonitoringService:
    def __init__(
        self,
        *,
        module_repo: ModuleRepository,
        health_repo: HealthCheckRepository,
        event_log_repo: EventLogRepository,
        delivery_repo: DeliveryRepository,
        dead_letter_repo: DeadLetterRepository,
        notification_repo: NotificationRepository,
        broker: Broker,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.module_repo = module_repo
        self.health_repo = health_repo
        self.event_log_repo = event_log_repo
        self.delivery_repo = delivery_repo
        self.dead_letter_repo = dead_letter_repo
        self.notification_repo = notification_repo
        self.broker = broker
        self._http_client = http_client

    # ------------------------------------------------------------------
    # Health de los modulos
    # ------------------------------------------------------------------
    async def poll_modules(self) -> list[HealthCheck]:
        """Sondea todos los modulos con `health_url` declarado."""
        modules = await self.module_repo.list_with_health_url()
        if not modules:
            return []

        client = self._http_client or httpx.AsyncClient(
            timeout=settings.health_poll_timeout_seconds
        )
        owns_client = self._http_client is None
        checks: list[HealthCheck] = []

        try:
            for module in modules:
                checks.append(await self._probe(client, module.name, module.health_url or ""))
        finally:
            if owns_client:
                await client.aclose()

        logger.info(
            "health_poll_completed",
            modules=len(checks),
            down=sum(1 for c in checks if c.status == HealthStatus.DOWN),
        )
        return checks

    async def _probe(
        self, client: httpx.AsyncClient, module_name: str, url: str
    ) -> HealthCheck:
        started = utcnow()
        status = HealthStatus.DOWN
        http_status: int | None = None
        error: str | None = None

        try:
            response = await client.get(url)
            http_status = response.status_code
            latency_ms = _elapsed_ms(started)
            if response.is_success:
                status = (
                    HealthStatus.DEGRADED
                    if latency_ms > DEGRADED_LATENCY_MS
                    else HealthStatus.UP
                )
            else:
                error = f"HTTP {response.status_code}"
        except Exception as exc:
            # Un modulo caido es un dato, no un error del Core.
            latency_ms = _elapsed_ms(started)
            error = f"{type(exc).__name__}: {exc}"

        check = HealthCheck(
            module_name=module_name,
            status=status,
            latency_ms=latency_ms,
            http_status=http_status,
            error=error[:1000] if error else None,
            checked_at=utcnow(),
        )
        self.health_repo.add(check)
        return check

    async def module_health(self) -> list[ModuleHealth]:
        """Estado actual de cada modulo, con su disponibilidad de las ultimas 24h."""
        modules = await self.module_repo.list_ordered()
        latest = {check.module_name: check for check in await self.health_repo.latest_per_module()}
        since = utcnow() - timedelta(hours=24)

        result: list[ModuleHealth] = []
        for module in modules:
            check = latest.get(module.name)
            result.append(
                ModuleHealth(
                    module_name=module.name,
                    display_name=module.display_name,
                    status=_as_status(check.status) if check else HealthStatus.UNKNOWN,
                    latency_ms=check.latency_ms if check else None,
                    http_status=check.http_status if check else None,
                    error=check.error if check else None,
                    checked_at=check.checked_at if check else None,
                    uptime_24h=await self.health_repo.uptime_ratio(module.name, since=since),
                )
            )
        return result

    # ------------------------------------------------------------------
    # Readiness del propio Core
    # ------------------------------------------------------------------
    async def readiness(self) -> dict[str, Any]:
        """Chequea las dependencias propias: base de datos y broker.

        El Core se considera listo con la base arriba. El broker caido lo deja
        `degraded`, no `down`: la API sigue sirviendo consultas y los eventos
        esperan en `core.inbox`.
        """
        database_ok = True
        database_error: str | None = None
        try:
            await self.event_log_repo.count_by_status()
        except Exception as exc:
            database_ok = False
            database_error = f"{type(exc).__name__}: {exc}"

        broker_ok = False
        try:
            broker_ok = await self.broker.healthy()
        except Exception:
            broker_ok = False

        if not database_ok:
            state = "down"
        elif not broker_ok:
            state = "degraded"
        else:
            state = "up"

        return {
            "status": state,
            "checks": {
                "database": {"status": "up" if database_ok else "down", "error": database_error},
                "broker": {
                    "status": "up" if broker_ok else "down",
                    "detail": None
                    if broker_ok
                    else "Los eventos quedan encolados en core.inbox hasta que vuelva.",
                },
            },
        }

    # ------------------------------------------------------------------
    # Dashboards
    # ------------------------------------------------------------------
    async def technical_dashboard(self, *, window_hours: int = 24) -> dict[str, Any]:
        """Tablero tecnico: el pulso del hub."""
        since = utcnow() - timedelta(hours=window_hours)
        last_minute = utcnow() - timedelta(minutes=1)
        last_hour = utcnow() - timedelta(hours=1)

        events_by_status = await self.event_log_repo.count_by_status(since=since)
        events_last_hour = await self.event_log_repo.count_since(last_hour)

        return {
            "windowHours": window_hours,
            "generatedAt": utcnow(),
            "events": {
                "byStatus": events_by_status,
                "total": sum(events_by_status.values()),
                "lastMinute": await self.event_log_repo.count_since(last_minute),
                "lastHour": events_last_hour,
                "perMinuteLastHour": round(events_last_hour / 60, 2),
                "topTypes": await self.event_log_repo.count_by_type(since=since),
                "byModule": await self.event_log_repo.count_by_module(since=since),
                "processing": await self.event_log_repo.processing_time_stats(since=since),
            },
            "deliveries": {
                "byStatus": await self.delivery_repo.count_by_status(),
                "byModule": await self.delivery_repo.count_by_module_and_status(),
            },
            "deadLetters": {
                "open": await self.dead_letter_repo.count_open(),
                "byStatus": await self.dead_letter_repo.count_by_status(),
                "byReason": await self.dead_letter_repo.count_by_reason(),
            },
            "modules": [_health_to_dict(item) for item in await self.module_health()],
            "broker": {"connected": await _safe_healthy(self.broker)},
        }

    async def communications_dashboard(self, *, window_hours: int = 24) -> dict[str, Any]:
        """Tablero de comunicaciones: que se notifico y que fallo."""
        since = utcnow() - timedelta(hours=window_hours)
        by_status = await self.notification_repo.count_by_status(since=since)
        total = sum(by_status.values())
        sent = by_status.get("SENT", 0)

        return {
            "windowHours": window_hours,
            "generatedAt": utcnow(),
            "total": total,
            "byStatus": by_status,
            "byChannel": await self.notification_repo.count_by_channel(since=since),
            "topTemplates": await self.notification_repo.count_by_template(),
            "successRate": round(sent / total, 4) if total else None,
        }


def _health_to_dict(item: ModuleHealth) -> dict[str, Any]:
    return {
        "moduleName": item.module_name,
        "displayName": item.display_name,
        "status": _value(item.status),
        "latencyMs": item.latency_ms,
        "httpStatus": item.http_status,
        "error": item.error,
        "checkedAt": item.checked_at,
        "uptime24h": item.uptime_24h,
    }


async def _safe_healthy(broker: Broker) -> bool:
    try:
        return await broker.healthy()
    except Exception:
        return False


def _as_status(value: object) -> HealthStatus:
    if isinstance(value, HealthStatus):
        return value
    try:
        return HealthStatus(str(value))
    except ValueError:
        return HealthStatus.UNKNOWN


def _value(value: object) -> str:
    return str(getattr(value, "value", value))


def _elapsed_ms(started: datetime) -> int:
    return max(int((utcnow() - started).total_seconds() * 1000), 0)
