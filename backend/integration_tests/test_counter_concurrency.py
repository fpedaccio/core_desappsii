"""Real PostgreSQL/RabbitMQ regression for concurrent receipt accounting."""

import asyncio

from sqlalchemy import func, select

from app.models.events import Delivery, EventLog
from app.models.registry import EventType
from app.repositories.registry_repository import EventTypeRepository


async def test_concurrent_ingestion_keeps_exact_receipt_count(real):
    count = 20
    barrier = asyncio.Barrier(count)

    class SynchronizedRepository(EventTypeRepository):
        async def get_or_create(self, *args, **kwargs):
            result = await super().get_or_create(*args, **kwargs)
            await asyncio.wait_for(barrier.wait(), timeout=15)
            return result

    envelopes = [real.envelope() for _ in range(count)]

    async def ingest(envelope):
        async with real.sessions() as session:
            hub = real.hub(session)
            hub.event_type_repo = SynchronizedRepository(session)
            result = await hub.ingest(envelope)
            assert result.accepted
            assert result.routed_to == [real.target]
            await session.commit()

    await asyncio.wait_for(
        asyncio.gather(*(ingest(envelope) for envelope in envelopes)),
        timeout=45,
    )
    async with real.sessions() as session:
        event_type = await session.scalar(
            select(EventType).where(EventType.name == real.event_type)
        )
        assert event_type.total_received == count
        assert await session.scalar(
            select(func.count()).select_from(EventLog).where(
                EventLog.event_type == real.event_type
            )
        ) == count
        assert await session.scalar(
            select(func.count()).select_from(Delivery)
            .join(EventLog, EventLog.id == Delivery.event_log_id)
            .where(EventLog.event_type == real.event_type)
        ) == count

    async with real.sessions() as session:
        assert (await real.hub(session).ingest(envelopes[0])).duplicate
        await session.commit()
    async with real.sessions() as session:
        event_type = await session.scalar(
            select(EventType).where(EventType.name == real.event_type)
        )
        assert event_type.total_received == count
