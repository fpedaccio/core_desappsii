"""Acceso a datos de la bitacora, entregas, DLQ y auditoria de reintentos.

Casi todas las consultas aceptan `module_scope`: cuando un modulo entra al
dashboard solo ve lo suyo (lo que publico + lo que le entregaron). El equipo 9
entra como admin y ve todo.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import selectinload

from app.models.events import (
    DeadLetter,
    DeadLetterStatus,
    Delivery,
    DeliveryStatus,
    EventLog,
    EventStatus,
    RetryAudit,
)
from app.repositories.base import BaseRepository, Page


def _enum_value(value: object) -> str:
    """Normaliza el valor de un enum, que segun el dialecto viene str o Enum."""
    return str(getattr(value, "value", value))


class EventLogRepository(BaseRepository[EventLog]):
    model = EventLog

    def _scoped(self, stmt: Select, module_scope: str | None) -> Select:
        """Limita a los eventos que le corresponden a un modulo.

        Son los que publico mas los que le entregaron. Sin esto un equipo veria
        el trafico de los otros ocho.
        """
        if not module_scope:
            return stmt
        return stmt.where(
            or_(
                EventLog.source_module == module_scope,
                EventLog.id.in_(
                    select(Delivery.event_log_id).where(Delivery.target_module == module_scope)
                ),
            )
        )

    async def get_by_event_id(self, event_id: uuid.UUID) -> EventLog | None:
        """La consulta que sostiene la idempotencia: ¿ya vimos este eventId?"""
        stmt = (
            select(EventLog)
            .options(selectinload(EventLog.deliveries))
            .where(EventLog.event_id == event_id)
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def get_with_deliveries(self, log_id: uuid.UUID) -> EventLog | None:
        stmt = (
            select(EventLog).options(selectinload(EventLog.deliveries)).where(EventLog.id == log_id)
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def search(
        self,
        *,
        module_scope: str | None = None,
        query: str | None = None,
        event_type: str | None = None,
        source_module: str | None = None,
        target_module: str | None = None,
        status: EventStatus | None = None,
        correlation_id: uuid.UUID | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        page: int = 1,
        size: int = 25,
    ) -> Page[EventLog]:
        stmt: Select = select(EventLog).options(selectinload(EventLog.deliveries))
        stmt = self._scoped(stmt, module_scope)

        if query:
            pattern = f"%{query.strip()}%"
            stmt = stmt.where(
                or_(
                    EventLog.event_type.ilike(pattern),
                    EventLog.source_module.ilike(pattern),
                )
            )
        if event_type:
            stmt = stmt.where(EventLog.event_type == event_type)
        if source_module:
            stmt = stmt.where(EventLog.source_module == source_module)
        if target_module:
            stmt = stmt.where(
                EventLog.id.in_(
                    select(Delivery.event_log_id).where(Delivery.target_module == target_module)
                )
            )
        if status:
            stmt = stmt.where(EventLog.status == status)
        if correlation_id:
            stmt = stmt.where(EventLog.correlation_id == correlation_id)
        if since:
            stmt = stmt.where(EventLog.received_at >= since)
        if until:
            stmt = stmt.where(EventLog.received_at <= until)

        return await self.paginate(stmt.order_by(EventLog.received_at.desc()), page=page, size=size)

    async def by_correlation(self, correlation_id: uuid.UUID) -> list[EventLog]:
        """La journey completa: todos los eventos que comparten correlationId."""
        stmt = (
            select(EventLog)
            .options(selectinload(EventLog.deliveries))
            .where(EventLog.correlation_id == correlation_id)
            .order_by(EventLog.occurred_at)
        )
        return list((await self.session.execute(stmt)).scalars().unique().all())

    # -- estadisticas ------------------------------------------------------
    async def count_by_status(
        self, *, module_scope: str | None = None, since: datetime | None = None
    ) -> dict[str, int]:
        stmt = select(EventLog.status, func.count()).group_by(EventLog.status)
        stmt = self._scoped(stmt, module_scope)
        if since:
            stmt = stmt.where(EventLog.received_at >= since)
        return {
            _enum_value(status): int(total)
            for status, total in (await self.session.execute(stmt)).all()
        }

    async def count_published(self, module: str, *, since: datetime | None = None) -> int:
        stmt = select(func.count()).select_from(EventLog).where(EventLog.source_module == module)
        if since:
            stmt = stmt.where(EventLog.received_at >= since)
        return int((await self.session.execute(stmt)).scalar_one())

    async def count_since(self, since: datetime, *, module_scope: str | None = None) -> int:
        stmt = select(func.count()).select_from(EventLog).where(EventLog.received_at >= since)
        stmt = self._scoped(stmt, module_scope)
        return int((await self.session.execute(stmt)).scalar_one())

    async def top_types(
        self, *, module_scope: str | None = None, since: datetime | None = None, limit: int = 10
    ) -> list[dict]:
        stmt = (
            select(EventLog.event_type, func.count().label("total"))
            .group_by(EventLog.event_type)
            .order_by(func.count().desc())
            .limit(limit)
        )
        stmt = self._scoped(stmt, module_scope)
        if since:
            stmt = stmt.where(EventLog.received_at >= since)
        return [
            {"eventType": name, "total": int(total)}
            for name, total in (await self.session.execute(stmt)).all()
        ]

    async def by_source_module(self, *, since: datetime | None = None) -> list[dict]:
        stmt = (
            select(EventLog.source_module, func.count().label("total"))
            .group_by(EventLog.source_module)
            .order_by(func.count().desc())
        )
        if since:
            stmt = stmt.where(EventLog.received_at >= since)
        return [
            {"module": name, "total": int(total)}
            for name, total in (await self.session.execute(stmt)).all()
        ]

    async def hourly_volume(
        self, *, module_scope: str | None = None, since: datetime | None = None
    ) -> list[dict]:
        """Volumen por hora, para el grafico del dashboard.

        Se agrupa en Python: la funcion para truncar a la hora difiere entre
        SQLite y PostgreSQL, y el volumen de una ventana de 24h es chico.
        """
        stmt = select(EventLog.received_at, EventLog.status)
        stmt = self._scoped(stmt, module_scope)
        if since:
            stmt = stmt.where(EventLog.received_at >= since)

        buckets: dict[str, dict[str, int]] = {}
        for received_at, status in (await self.session.execute(stmt)).all():
            key = received_at.replace(minute=0, second=0, microsecond=0).isoformat()
            bucket = buckets.setdefault(key, {"total": 0, "rejected": 0})
            bucket["total"] += 1
            if _enum_value(status) == EventStatus.REJECTED.value:
                bucket["rejected"] += 1
        return [
            {"hour": hour, "total": data["total"], "rejected": data["rejected"]}
            for hour, data in sorted(buckets.items())
        ]

    async def processing_stats(
        self, *, module_scope: str | None = None, since: datetime | None = None
    ) -> dict[str, float]:
        stmt = select(func.avg(EventLog.processing_ms), func.max(EventLog.processing_ms)).where(
            EventLog.processing_ms.is_not(None)
        )
        stmt = self._scoped(stmt, module_scope)
        if since:
            stmt = stmt.where(EventLog.received_at >= since)
        avg_ms, max_ms = (await self.session.execute(stmt)).one()
        return {"avgMs": round(float(avg_ms or 0), 2), "maxMs": float(max_ms or 0)}


class DeliveryRepository(BaseRepository[Delivery]):
    model = Delivery

    async def list_for_event(self, event_log_id: uuid.UUID) -> list[Delivery]:
        stmt = select(Delivery).where(Delivery.event_log_id == event_log_id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def find_for_event_and_module(
        self, event_log_id: uuid.UUID, target_module: str
    ) -> Delivery | None:
        return await self.find_one(event_log_id=event_log_id, target_module=target_module)

    async def search(
        self,
        *,
        target_module: str | None = None,
        status: DeliveryStatus | None = None,
        event_type: str | None = None,
        page: int = 1,
        size: int = 25,
    ) -> Page[Delivery]:
        stmt = select(Delivery)
        if target_module:
            stmt = stmt.where(Delivery.target_module == target_module)
        if status:
            stmt = stmt.where(Delivery.status == status)
        if event_type:
            stmt = stmt.where(Delivery.event_type == event_type)
        return await self.paginate(stmt.order_by(Delivery.created_at.desc()), page=page, size=size)

    async def count_by_status(self, *, target_module: str | None = None) -> dict[str, int]:
        stmt = select(Delivery.status, func.count()).group_by(Delivery.status)
        if target_module:
            stmt = stmt.where(Delivery.target_module == target_module)
        return {
            _enum_value(status): int(total)
            for status, total in (await self.session.execute(stmt)).all()
        }

    async def count_by_module_and_status(self) -> list[dict]:
        stmt = select(Delivery.target_module, Delivery.status, func.count()).group_by(
            Delivery.target_module, Delivery.status
        )
        return [
            {"module": module, "status": _enum_value(status), "total": int(total)}
            for module, status, total in (await self.session.execute(stmt)).all()
        ]

    async def due_for_retry(self, *, now: datetime, limit: int = 100) -> list[Delivery]:
        stmt = (
            select(Delivery)
            .where(
                Delivery.status == DeliveryStatus.RETRYING,
                Delivery.next_retry_at.is_not(None),
                Delivery.next_retry_at <= now,
            )
            .order_by(Delivery.next_retry_at)
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())


class DeadLetterRepository(BaseRepository[DeadLetter]):
    model = DeadLetter

    def _scoped(self, stmt: Select, module_scope: str | None) -> Select:
        if not module_scope:
            return stmt
        return stmt.where(
            or_(
                DeadLetter.source_module == module_scope,
                DeadLetter.target_module == module_scope,
            )
        )

    async def get_with_retries(self, dead_letter_id: uuid.UUID) -> DeadLetter | None:
        stmt = (
            select(DeadLetter)
            .options(selectinload(DeadLetter.retries))
            .where(DeadLetter.id == dead_letter_id)
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def search(
        self,
        *,
        module_scope: str | None = None,
        query: str | None = None,
        status: DeadLetterStatus | None = None,
        event_type: str | None = None,
        target_module: str | None = None,
        reason_code: str | None = None,
        page: int = 1,
        size: int = 25,
    ) -> Page[DeadLetter]:
        stmt = select(DeadLetter).options(selectinload(DeadLetter.retries))
        stmt = self._scoped(stmt, module_scope)
        if query:
            pattern = f"%{query.strip()}%"
            stmt = stmt.where(
                or_(
                    DeadLetter.event_type.ilike(pattern),
                    DeadLetter.reason.ilike(pattern),
                    DeadLetter.reason_code.ilike(pattern),
                )
            )
        if status:
            stmt = stmt.where(DeadLetter.status == status)
        if event_type:
            stmt = stmt.where(DeadLetter.event_type == event_type)
        if target_module:
            stmt = stmt.where(DeadLetter.target_module == target_module)
        if reason_code:
            stmt = stmt.where(DeadLetter.reason_code == reason_code)
        return await self.paginate(
            stmt.order_by(DeadLetter.created_at.desc()), page=page, size=size
        )

    async def count_open(self, *, module_scope: str | None = None) -> int:
        stmt = (
            select(func.count())
            .select_from(DeadLetter)
            .where(DeadLetter.status == DeadLetterStatus.OPEN)
        )
        stmt = self._scoped(stmt, module_scope)
        return int((await self.session.execute(stmt)).scalar_one())

    async def count_by_reason(self, *, module_scope: str | None = None) -> list[dict]:
        stmt = (
            select(DeadLetter.reason_code, func.count().label("total"))
            .group_by(DeadLetter.reason_code)
            .order_by(func.count().desc())
        )
        stmt = self._scoped(stmt, module_scope)
        return [
            {"reasonCode": reason, "total": int(total)}
            for reason, total in (await self.session.execute(stmt)).all()
        ]

    async def count_by_status(self, *, module_scope: str | None = None) -> dict[str, int]:
        stmt = select(DeadLetter.status, func.count()).group_by(DeadLetter.status)
        stmt = self._scoped(stmt, module_scope)
        return {
            _enum_value(status): int(total)
            for status, total in (await self.session.execute(stmt)).all()
        }


class RetryAuditRepository(BaseRepository[RetryAudit]):
    model = RetryAudit

    async def search(
        self,
        *,
        dead_letter_id: uuid.UUID | None = None,
        event_id: uuid.UUID | None = None,
        page: int = 1,
        size: int = 25,
    ) -> Page[RetryAudit]:
        stmt = select(RetryAudit)
        if dead_letter_id:
            stmt = stmt.where(RetryAudit.dead_letter_id == dead_letter_id)
        if event_id:
            stmt = stmt.where(RetryAudit.event_id == event_id)
        return await self.paginate(
            stmt.order_by(RetryAudit.created_at.desc()), page=page, size=size
        )
