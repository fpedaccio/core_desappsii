"""Hourly aggregation against real PostgreSQL, with rolled-back fixtures."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from app.models.events import Delivery, EventLog
from app.repositories.event_repository import EventLogRepository


@pytest.mark.parametrize("zone", ["UTC", "America/Argentina/Buenos_Aires"])
async def test_hourly_volume_preserves_scope_dates_and_counts(real, zone):
    suffix = uuid.uuid4().hex[:12]
    owner = "qa-hourly-a-" + suffix
    other = "qa-hourly-b-" + suffix
    event_type = "qaHourly" + suffix

    async with real.sessions() as session:
        transaction = await session.begin()
        try:
            await session.execute(
                text("SELECT set_config('TimeZone', :zone, true)"), {"zone": zone}
            )
            specs = [
                (owner, "2026-11-01T23:59:59+00:00", "ROUTED"),
                (owner, "2026-11-02T00:00:00+00:00", "REJECTED"),
                (other, "2026-11-01T21:30:00-03:00", "ROUTED"),
                (other, "2026-11-02T01:00:00+00:00", "REJECTED"),
                (owner, "2026-11-02T01:15:00+00:00", "ROUTED"),
            ]
            records = []
            for module, timestamp, status in specs:
                instant = datetime.fromisoformat(timestamp)
                record = EventLog(
                    event_id=uuid.uuid4(),
                    event_type=event_type,
                    event_version="1.0",
                    source_module=module,
                    occurred_at=instant,
                    received_at=instant,
                    envelope={"data": {"synthetic": True}},
                    ingestion_channel="HTTP",
                    status=status,
                )
                session.add(record)
                records.append(record)
            await session.flush()

            # Own and received events must be included without double counting.
            for index in (0, 2):
                session.add(Delivery(
                    event_log_id=records[index].id,
                    target_module=owner,
                    queue_name="q." + owner,
                    event_type=event_type,
                    status="DELIVERED",
                    attempts=1,
                    max_attempts=4,
                ))
            await session.flush()

            repo = EventLogRepository(session)
            expected = [
                {"hour": "2026-11-01T23:00:00+00:00", "total": 1, "rejected": 0},
                {"hour": "2026-11-02T00:00:00+00:00", "total": 2, "rejected": 1},
                {"hour": "2026-11-02T01:00:00+00:00", "total": 1, "rejected": 0},
            ]
            assert await repo.hourly_volume(module_scope=owner) == expected
            assert await repo.hourly_volume(
                module_scope=owner, since=datetime(2026, 11, 2, tzinfo=UTC)
            ) == expected[1:]
            assert await repo.hourly_volume(
                module_scope=owner,
                since=datetime.fromisoformat("2026-11-01T21:15:00-03:00"),
            ) == [
                {"hour": "2026-11-02T00:00:00+00:00", "total": 1, "rejected": 0},
                {"hour": "2026-11-02T01:00:00+00:00", "total": 1, "rejected": 0},
            ]
            assert await repo.hourly_volume(module_scope=other) == [
                {"hour": "2026-11-02T00:00:00+00:00", "total": 1, "rejected": 0},
                {"hour": "2026-11-02T01:00:00+00:00", "total": 1, "rejected": 1},
            ]
            assert await repo.hourly_volume(module_scope="qa-none-" + suffix) == []
            assert await repo.hourly_volume(
                module_scope=owner, since=datetime(2026, 11, 3, tzinfo=UTC)
            ) == []
        finally:
            await transaction.rollback()
