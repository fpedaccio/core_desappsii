"""Acceso a datos de la trazabilidad del hub: bitacora, entregas, DLQ y auditoria."""

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
    ProcessedEvent,
    RetryAudit,
)
from app.repositories.base import BaseRepository, Page


class EventLogRepository(BaseRepository[EventLog]):
    model = EventLog

    async def get_by_event_id(self, event_id: uuid.UUID) -> EventLog | None:
        """Consulta que sostiene la idempotencia: ¿ya vimos este eventId?"""
        stmt = (
            select(EventLog)
            .options(selectinload(EventLog.deliveries))
            .where(EventLog.event_id == event_id)
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def get_with_deliveries(self, log_id: uuid.UUID) -> EventLog | None:
        stmt = (
            select(EventLog)
            .options(selectinload(EventLog.deliveries))
            .where(EventLog.id == log_id)
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def search(
        self,
        *,
        query: str | None = None,
        event_type: str | None = None,
        source_module: str | None = None,
        status: EventStatus | None = None,
        correlation_id: uuid.UUID | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        page: int = 1,
        size: int = 20,
    ) -> Page[EventLog]:
        stmt: Select = select(EventLog).options(selectinload(EventLog.deliveries))
        if query:
            pattern = f"%{query.strip()}%"
            stmt = stmt.where(
                or_(EventLog.event_type.ilike(pattern), EventLog.source_module.ilike(pattern))
            )
        if event_type:
            stmt = stmt.where(EventLog.event_type == event_type)
        if source_module:
            stmt = stmt.where(EventLog.source_module == source_module)
        if status:
            stmt = stmt.where(EventLog.status == status)
        if correlation_id:
            stmt = stmt.where(EventLog.correlation_id == correlation_id)
        if since:
            stmt = stmt.where(EventLog.received_at >= since)
        if until:
            stmt = stmt.where(EventLog.received_at <= until)
        return await self.paginate(
            stmt.order_by(EventLog.received_at.desc()), page=page, size=size
        )

    async def by_correlation(self, correlation_id: uuid.UUID) -> list[EventLog]:
        """La journey completa: todos los eventos que comparten correlationId."""
        stmt = (
            select(EventLog)
            .options(selectinload(EventLog.deliveries))
            .where(EventLog.correlation_id == correlation_id)
            .order_by(EventLog.occurred_at)
        )
        return list((await self.session.execute(stmt)).scalars().unique().all())

    async def count_by_status(self, *, since: datetime | None = None) -> dict[str, int]:
        stmt = select(EventLog.status, func.count()).group_by(EventLog.status)
        if since:
            stmt = stmt.where(EventLog.received_at >= since)
        rows = (await self.session.execute(stmt)).all()
        return {str(_enum_value(status)): int(count) for status, count in rows}

    async def count_by_type(self, *, since: datetime | None = None, limit: int = 10) -> list[dict]:
        stmt = (
            select(EventLog.event_type, func.count().label("total"))
            .group_by(EventLog.event_type)
            .order_by(func.count().desc())
            .limit(limit)
        )
        if since:
            stmt = stmt.where(EventLog.received_at >= since)
        rows = (await self.session.execute(stmt)).all()
        return [{"eventType": event_type, "total": int(total)} for event_type, total in rows]

    async def count_by_module(self, *, since: datetime | None = None) -> list[dict]:
        stmt = (
            select(EventLog.source_module, func.count().label("total"))
            .group_by(EventLog.source_module)
            .order_by(func.count().desc())
        )
        if since:
            stmt = stmt.where(EventLog.received_at >= since)
        rows = (await self.session.execute(stmt)).all()
        return [{"module": module, "total": int(total)} for module, total in rows]

    async def count_since(self, since: datetime) -> int:
        stmt = select(func.count()).select_from(EventLog).where(EventLog.received_at >= since)
        return int((await self.session.execute(stmt)).scalar_one())

    async def processing_time_stats(self, *, since: datetime | None = None) -> dict[str, float]:
        stmt = select(
            func.avg(EventLog.processing_ms),
            func.max(EventLog.processing_ms),
        ).where(EventLog.processing_ms.is_not(None))
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
        page: int = 1,
        size: int = 20,
    ) -> Page[Delivery]:
        stmt = select(Delivery)
        if target_module:
            stmt = stmt.where(Delivery.target_module == target_module)
        if status:
            stmt = stmt.where(Delivery.status == status)
        return await self.paginate(stmt.order_by(Delivery.created_at.desc()), page=page, size=size)

    async def count_by_status(self) -> dict[str, int]:
        stmt = select(Delivery.status, func.count()).group_by(Delivery.status)
        rows = (await self.session.execute(stmt)).all()
        return {str(_enum_value(status)): int(count) for status, count in rows}

    async def count_by_module_and_status(self) -> list[dict]:
        stmt = select(Delivery.target_module, Delivery.status, func.count()).group_by(
            Delivery.target_module, Delivery.status
        )
        rows = (await self.session.execute(stmt)).all()
        return [
            {"module": module, "status": str(_enum_value(status)), "total": int(total)}
            for module, status, total in rows
        ]

    async def due_for_retry(self, *, now: datetime, limit: int = 100) -> list[Delivery]:
        """Entregas cuyo backoff ya vencio y hay que volver a intentar."""
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
        query: str | None = None,
        status: DeadLetterStatus | None = None,
        event_type: str | None = None,
        target_module: str | None = None,
        reason_code: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> Page[DeadLetter]:
        stmt = select(DeadLetter).options(selectinload(DeadLetter.retries))
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

    async def list_by_ids(self, ids: list[uuid.UUID]) -> list[DeadLetter]:
        if not ids:
            return []
        stmt = (
            select(DeadLetter)
            .options(selectinload(DeadLetter.retries))
            .where(DeadLetter.id.in_(ids))
        )
        return list((await self.session.execute(stmt)).scalars().unique().all())

    async def count_open(self) -> int:
        stmt = (
            select(func.count())
            .select_from(DeadLetter)
            .where(DeadLetter.status == DeadLetterStatus.OPEN)
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def count_by_reason(self) -> list[dict]:
        stmt = (
            select(DeadLetter.reason_code, func.count().label("total"))
            .group_by(DeadLetter.reason_code)
            .order_by(func.count().desc())
        )
        rows = (await self.session.execute(stmt)).all()
        return [{"reasonCode": reason, "total": int(total)} for reason, total in rows]

    async def count_by_status(self) -> dict[str, int]:
        stmt = select(DeadLetter.status, func.count()).group_by(DeadLetter.status)
        rows = (await self.session.execute(stmt)).all()
        return {str(_enum_value(status)): int(count) for status, count in rows}


class RetryAuditRepository(BaseRepository[RetryAudit]):
    model = RetryAudit

    async def search(
        self,
        *,
        dead_letter_id: uuid.UUID | None = None,
        event_id: uuid.UUID | None = None,
        page: int = 1,
        size: int = 20,
    ) -> Page[RetryAudit]:
        stmt = select(RetryAudit)
        if dead_letter_id:
            stmt = stmt.where(RetryAudit.dead_letter_id == dead_letter_id)
        if event_id:
            stmt = stmt.where(RetryAudit.event_id == event_id)
        return await self.paginate(
            stmt.order_by(RetryAudit.created_at.desc()), page=page, size=size
        )


class ProcessedEventRepository(BaseRepository[ProcessedEvent]):
    model = ProcessedEvent

    async def was_processed(self, consumer: str, event_id: uuid.UUID) -> bool:
        return await self.exists(consumer=consumer, event_id=event_id)

    async def mark(
        self,
        *,
        consumer: str,
        event_id: uuid.UUID,
        event_type: str | None,
        processed_at: datetime,
        result: str | None = None,
    ) -> ProcessedEvent:
        record = ProcessedEvent(
            consumer=consumer,
            event_id=event_id,
            event_type=event_type,
            processed_at=processed_at,
            result=result,
        )
        return self.add(record)

    async def list_for_event(self, event_id: uuid.UUID) -> list[ProcessedEvent]:
        stmt = select(ProcessedEvent).where(ProcessedEvent.event_id == event_id)
        return list((await self.session.execute(stmt)).scalars().all())


def _enum_value(value: object) -> object:
    """Normaliza el valor de un enum, que segun el dialecto viene como str o Enum."""
    return getattr(value, "value", value)
