"""Opt-in tests: dedicated PostgreSQL/RabbitMQ containers, never the shared server."""

from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import dataclass
from urllib.parse import urlsplit

import pytest
import pytest_asyncio

# Reject accidental invocation before importing application configuration.
if os.environ.get("RUN_REAL_INTEGRATION") != "1":
    raise pytest.UsageError(
        "Run these tests with deploy/integration_up.py, not on a shared environment."
    )
db = urlsplit(os.environ.get("DATABASE_URL", ""))
amqp = urlsplit(os.environ.get("RABBITMQ_URL", ""))
if (
    db.hostname != "integration-postgres"
    or db.path != "/core_integration"
    or amqp.hostname != "integration-rabbitmq"
):
    raise pytest.UsageError("Integration endpoints must be the dedicated Compose services.")

import aio_pika  # noqa: E402
import httpx  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

import app.models  # noqa: E402, F401 - register all mapped relationships
from app.core.config import settings  # noqa: E402
from app.core.database import Base  # noqa: E402
from app.messaging.provider import set_broker  # noqa: E402
from app.messaging.rabbitmq import RabbitMQBroker  # noqa: E402
from app.messaging.topology import full_topology  # noqa: E402
from app.models.registry import EventType, ModuleAccount, Subscription  # noqa: E402
from app.repositories.event_repository import (  # noqa: E402
    DeadLetterRepository,
    DeliveryRepository,
    EventLogRepository,
    RetryAuditRepository,
)
from app.repositories.registry_repository import (  # noqa: E402
    EventTypeRepository,
    SubscriptionRepository,
)
from app.services.delivery_service import DeliveryService  # noqa: E402
from app.services.envelope import EventEnvelope  # noqa: E402
from app.services.event_hub_service import EventHubService  # noqa: E402
from app.workers import inbox_worker  # noqa: E402


@dataclass(repr=False)
class RealContext:
    sessions: object
    broker: RabbitMQBroker
    channel: object
    event_type: str
    producer: str
    target: str
    queue: str

    def envelope(self):
        from datetime import UTC, datetime
        return EventEnvelope.model_validate({
            "eventId": str(uuid.uuid4()), "eventType": self.event_type,
            "sourceModule": self.producer, "occurredAt": datetime.now(UTC).isoformat(),
            "data": {"testValue": str(uuid.uuid4())},
        })

    def hub(self, session):
        return EventHubService(
            event_log_repo=EventLogRepository(session), delivery_repo=DeliveryRepository(session),
            dead_letter_repo=DeadLetterRepository(session),
            event_type_repo=EventTypeRepository(session),
            subscription_repo=SubscriptionRepository(session), broker=self.broker,
        )

    def deliveries(self, session):
        return DeliveryService(
            delivery_repo=DeliveryRepository(session),
            dead_letter_repo=DeadLetterRepository(session),
            retry_audit_repo=RetryAuditRepository(session),
            event_log_repo=EventLogRepository(session),
            hub=self.hub(session),
            broker=self.broker,
        )

    async def get_message(self, timeout=10):
        queue = await self.channel.get_queue(self.queue)
        async with asyncio.timeout(timeout):
            while True:
                message = await queue.get(fail=False)
                if message is not None:
                    return message
                await asyncio.sleep(0.05)

    async def row(self, model, condition, timeout=15):
        async with asyncio.timeout(timeout):
            while True:
                async with self.sessions() as session:
                    result = await session.execute(select(model).where(condition))
                    row = result.scalar_one_or_none()
                    if row is not None:
                        return row
                await asyncio.sleep(0.05)


@pytest_asyncio.fixture
async def real(monkeypatch):
    namespace = "it." + uuid.uuid4().hex
    for field, suffix in [("exchange_inbox", "in"), ("exchange_events", "events"),
                          ("exchange_dlx", "dlx"), ("exchange_retry", "retry"),
                          ("queue_inbox", "inbox"), ("queue_dlq", "dlq")]:
        monkeypatch.setattr(settings, field, f"{namespace}.{suffix}")
    # Keep the actual default delays. maxAttempts=2 exercises the real 5s tier.
    engine = create_async_engine(settings.database_url, poolclass=NullPool,
                                 connect_args={"server_settings": {"statement_timeout": "10000"}})
    sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    # Retry queue names are fixed in the real topology; isolate the entire vhost,
    # not just exchanges, so each declaration keeps its actual queue arguments.
    broker_url = amqp._replace(path="/" + namespace).geturl()
    broker = RabbitMQBroker(url=broker_url)
    admin = httpx.AsyncClient(
        base_url="http://integration-rabbitmq:15672",
        auth=(amqp.username, amqp.password), timeout=5,
    )
    created_vhost = False
    probe = None
    try:
        async with asyncio.timeout(30):
            while True:
                try:
                    response = await admin.get("/api/overview")
                    if response.status_code == 200:
                        break
                    if response.status_code in (401, 403):
                        response.raise_for_status()
                except httpx.TransportError:
                    pass
                await asyncio.sleep(0.2)
        response = await admin.put(f"/api/vhosts/{namespace}", json={})
        response.raise_for_status()
        created_vhost = True
        response = await admin.put(
            f"/api/permissions/{namespace}/{amqp.username}",
            json={"configure": ".*", "write": ".*", "read": ".*"},
        )
        response.raise_for_status()
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        await broker.connect()
        probe = await aio_pika.connect(broker_url)
        channel = await probe.channel()
        ctx = RealContext(sessions, broker, channel, namespace, namespace + ".producer",
                          namespace + ".consumer", namespace + ".queue")
        async with sessions() as session:
            producer = ModuleAccount(
                name=ctx.producer, display_name="Synthetic producer", active=True
            )
            consumer = ModuleAccount(
                name=ctx.target, display_name="Synthetic consumer",
                queue_name=ctx.queue, active=True,
            )
            event_type = EventType(name=ctx.event_type, owner_module=ctx.producer, discovered=False)
            session.add_all([producer, consumer, event_type])
            await session.flush()
            session.add(Subscription(module_id=consumer.id, event_type_id=event_type.id,
                                     max_attempts=2, active=True))
            await session.commit()
        await broker.declare(full_topology([ctx.queue]))
        set_broker(broker)
        monkeypatch.setattr(inbox_worker, "SessionFactory", sessions)
        yield ctx
    finally:
        await broker.close()
        set_broker(None)
        if probe is not None:
            await probe.close()
        await engine.dispose()
        try:
            if created_vhost:
                response = await admin.delete(f"/api/vhosts/{namespace}")
                if response.status_code != 404:
                    response.raise_for_status()
        finally:
            await admin.aclose()
