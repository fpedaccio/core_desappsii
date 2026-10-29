"""Behavior checks against real PostgreSQL and RabbitMQ; no FakeBroker or SQLite."""

import asyncio
import json
import time
import uuid

import pytest
from sqlalchemy import func, select, text

from app.core.config import settings
from app.messaging.broker import HEADER_ATTEMPT, HEADER_EVENT_ID, OutboundMessage
from app.models.events import DeadLetter, Delivery, EventLog, RetryAudit
from app.models.registry import EventType
from app.workers import inbox_worker


async def test_real_adapter_publishes_and_consumes(real):
    received = asyncio.get_running_loop().create_future()

    async def handler(message):
        if not received.done():
            received.set_result(message)

    await real.broker.consume(real.queue, handler)
    body = {"syntheticId": str(uuid.uuid4())}
    await real.broker.publish(OutboundMessage(settings.exchange_events, real.queue, body,
                                             headers={"integration-marker": real.event_type}))
    message = await asyncio.wait_for(received, 10)
    assert message.json() == body
    assert message.headers["integration-marker"] == real.event_type
    assert message.queue == real.queue


async def test_postgres_commit_jsonb_and_repository_read(real):
    envelope = real.envelope()
    async with real.sessions() as session:
        result = await real.hub(session).ingest(envelope)
        assert result.accepted and result.routed_to == [real.target]
        await session.commit()
    async with real.sessions() as session:
        stored = await real.hub(session).event_log_repo.get_by_event_id(envelope.event_id)
        assert stored.envelope == envelope.to_wire()
        assert stored.occurred_at.tzinfo is not None
        data_type = await session.scalar(text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='event_log' "
            "AND column_name='envelope'"
        ))
        assert data_type == "jsonb"
    message = await real.get_message()
    assert message.message_id == str(envelope.event_id)
    assert int(message.delivery_mode) == 2
    assert json.loads(message.body) == envelope.to_wire()
    await message.ack()


async def test_postgres_transaction_rolls_back_uncommitted_registry_change(real):
    name = "rollback." + uuid.uuid4().hex
    async with real.sessions() as session:
        with pytest.raises(RuntimeError, match="synthetic rollback"):
            async with session.begin():
                session.add(EventType(name=name, discovered=False))
                await session.flush()
                raise RuntimeError("synthetic rollback")
    async with real.sessions() as session:
        assert await session.scalar(select(EventType.id).where(EventType.name == name)) is None


async def test_duplicate_eventid_does_not_create_or_publish_another_delivery(real):
    envelope = real.envelope()
    async with real.sessions() as session:
        assert not (await real.hub(session).ingest(envelope)).duplicate
        await session.commit()
    async with real.sessions() as session:
        assert (await real.hub(session).ingest(envelope)).duplicate
        await session.commit()
    async with real.sessions() as session:
        result = await session.execute(
            select(EventLog).where(EventLog.event_id == envelope.event_id)
        )
        stored = result.scalar_one()
        deliveries = select(func.count()).select_from(Delivery).where(
            Delivery.event_log_id == stored.id
        )
        events = select(func.count()).select_from(EventLog).where(
            EventLog.event_id == envelope.event_id
        )
        assert await session.scalar(deliveries) == 1
        assert await session.scalar(events) == 1
    message = await real.get_message()
    assert json.loads(message.body)["eventId"] == str(envelope.event_id)
    await message.ack()
    queue = await real.channel.get_queue(real.queue)
    assert await queue.get(fail=False) is None


async def test_real_amqp_worker_persists_and_routes(real):
    await real.broker.consume(settings.queue_inbox, inbox_worker._handle_inbox)
    envelope = real.envelope()
    await real.broker.publish(OutboundMessage(settings.exchange_inbox, "", envelope.to_wire()))
    stored = await real.row(EventLog, EventLog.event_id == envelope.event_id)
    assert stored.status == "ROUTED"
    assert stored.ingestion_channel == "AMQP"
    message = await real.get_message()
    assert message.headers[HEADER_EVENT_ID] == str(envelope.event_id)
    assert json.loads(message.body) == envelope.to_wire()
    await message.ack()


async def test_invalid_schema_is_persisted_without_consumer_delivery(real):
    async with real.sessions() as session:
        result = await session.execute(select(EventType).where(EventType.name == real.event_type))
        event_type = result.scalar_one()
        event_type.json_schema = {"type": "object", "required": ["requiredField"]}
        await session.commit()
    envelope = real.envelope()
    async with real.sessions() as session:
        result = await real.hub(session).ingest(envelope)
        assert result.rejection_code == "SCHEMA_VIOLATION"
        await session.commit()
    dead = await real.row(DeadLetter, DeadLetter.event_id == envelope.event_id)
    assert dead.status == "OPEN" and dead.reason_code == "SCHEMA_VIOLATION"
    assert dead.raw_payload == envelope.to_wire()
    queue = await real.channel.get_queue(real.queue)
    assert await queue.get(fail=False) is None


async def test_nack_uses_real_ttl_retry_then_persists_terminal_dlq(real):
    await real.broker.consume(settings.queue_dlq, inbox_worker._handle_dlq)
    attempts = []

    async def reject(message):
        attempts.append((
            message.headers[HEADER_ATTEMPT], time.monotonic(), message.json(), message.headers,
        ))
        raise RuntimeError("Synthetic consumer rejection")

    envelope = real.envelope()
    async with real.sessions() as session:
        assert (await real.hub(session).ingest(envelope)).accepted
        await session.commit()
    # Exercise retries for a committed delivery; DB/AMQP atomicity is a separate scenario.
    await real.broker.consume(real.queue, reject)
    dead = await real.row(DeadLetter, DeadLetter.event_id == envelope.event_id, timeout=20)
    assert dead.reason_code == "DELIVERY_FAILED" and dead.status == "OPEN"
    assert dead.attempts == 2
    assert [item[0] for item in attempts] == [1, 2]
    assert attempts[1][1] - attempts[0][1] >= 4.5
    assert all(item[2] == envelope.to_wire() for item in attempts)
    assert all(item[3][HEADER_EVENT_ID] == str(envelope.event_id) for item in attempts)
    async with real.sessions() as session:
        audits = select(func.count()).select_from(RetryAudit).where(
            RetryAudit.event_id == envelope.event_id
        )
        assert await session.scalar(audits) >= 2


async def test_malformed_amqp_is_recorded_by_real_worker(real):
    await real.broker.consume(settings.queue_inbox, inbox_worker._handle_inbox)
    marker = "synthetic-malformed-" + uuid.uuid4().hex
    await real.broker.publish(OutboundMessage(settings.exchange_inbox, "", {"marker": marker}))
    dead = await real.row(DeadLetter, DeadLetter.raw_body.contains(marker))
    assert dead.reason_code == "MALFORMED_MESSAGE" and dead.status == "OPEN"
    assert json.loads(dead.raw_body) == {"marker": marker}
    queue = await real.channel.get_queue(real.queue)
    assert await queue.get(fail=False) is None
