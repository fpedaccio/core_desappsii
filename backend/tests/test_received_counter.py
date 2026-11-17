"""Receipt accounting with stale snapshots, rollback and duplicates."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.registry import EventType
from app.repositories.registry_repository import EventTypeRepository

pytestmark = pytest.mark.asyncio


async def test_stale_snapshots_do_not_lose_increments(session_factory, seeded):
    earlier = datetime(2026, 10, 31, 12, tzinfo=UTC)
    later = earlier + timedelta(seconds=10)
    async with session_factory() as first, session_factory() as second:
        a = await EventTypeRepository(first).get_by_name("ticketCreated")
        b = await EventTypeRepository(second).get_by_name("ticketCreated")
        assert a.total_received == b.total_received == 0
        await EventTypeRepository(first).record_received("ticketCreated", seen_at=later)
        await first.commit()
        await EventTypeRepository(second).record_received("ticketCreated", seen_at=earlier)
        await second.commit()

    async with session_factory() as session:
        event = await session.scalar(
            select(EventType).where(EventType.name == "ticketCreated")
        )
        assert event.total_received == 2
        assert event.first_seen_at.replace(tzinfo=UTC) == earlier
        assert event.last_seen_at.replace(tzinfo=UTC) == later


async def test_counter_update_rolls_back(session_factory, seeded):
    async with session_factory() as session:
        await EventTypeRepository(session).record_received(
            "ticketCreated", seen_at=datetime.now(UTC)
        )
        await session.rollback()
    async with session_factory() as session:
        event = await session.scalar(
            select(EventType).where(EventType.name == "ticketCreated")
        )
        assert event.total_received == 0


async def test_rejected_events_count_once_and_duplicates_do_not_count(
    client, auth, make_envelope
):
    admin = await auth("core")
    response = await client.put(
        "/api/v1/event-types/ticketCreated/schema",
        json={"jsonSchema": {"type": "object", "required": ["marker"]}},
        headers=admin,
    )
    assert response.status_code == 200
    producer = await auth("atencion-ciudadana")
    valid = make_envelope(data={"marker": "synthetic"})
    invalid = make_envelope(data={})
    assert (await client.post(
        "/api/v1/events", json=valid, headers=producer
    )).status_code == 202
    assert (await client.post(
        "/api/v1/events", json=invalid, headers=producer
    )).status_code == 422
    for envelope in (valid, invalid):
        duplicate = await client.post(
            "/api/v1/events", json=envelope, headers=producer
        )
        assert duplicate.status_code == 200
        assert duplicate.json()["duplicate"] is True
    detail = await client.get("/api/v1/event-types/ticketCreated", headers=admin)
    assert detail.json()["totalReceived"] == 2
