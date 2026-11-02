"""Shared admission accounting against isolated integration PostgreSQL."""

import asyncio
import json
import sys
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import delete, func, select, update

from app.core.shared_auth_rate_limit import SharedAuthRateLimiter
from app.models.auth_rate_limit import AuthRateLimitBucket


@pytest.fixture
async def store_sessions(real):
    # This fixture runs only in the isolated integration database.
    async with real.sessions() as session:
        await session.execute(delete(AuthRateLimitBucket))
        await session.commit()
    try:
        yield real.sessions
    finally:
        async with real.sessions() as session:
            await session.execute(delete(AuthRateLimitBucket))
            await session.commit()


async def test_shared_instances_and_independent_keys(store_sessions):
    first = SharedAuthRateLimiter(store_sessions, limit=2)
    second = SharedAuthRateLimiter(store_sessions, limit=2)
    assert await first.check("login:a") == 0
    assert await second.check("login:a") == 0
    assert 1 <= await first.check("login:a") <= 60
    assert await second.check("login:b") == 0
    assert await second.check("module:a") == 0


async def test_capacity_and_expired_window_recovery(store_sessions):
    limiter = SharedAuthRateLimiter(store_sessions, limit=1, capacity=1)
    assert await limiter.check("a") == 0
    assert 1 <= await limiter.check("b") <= 60
    assert 1 <= await limiter.check("a") <= 60

    async with store_sessions() as session:
        now = await session.scalar(select(func.clock_timestamp()))
        await session.execute(
            update(AuthRateLimitBucket)
            .where(AuthRateLimitBucket.key == "a")
            .values(expires_at=now - timedelta(seconds=1))
        )
        await session.commit()

    assert await limiter.check("b") == 0
    async with store_sessions() as session:
        assert await session.get(AuthRateLimitBucket, "a") is None
        assert await session.scalar(
            select(func.count()).select_from(AuthRateLimitBucket)
        ) == 1


async def test_admission_survives_other_transaction_rollback(store_sessions):
    limiter = SharedAuthRateLimiter(store_sessions, limit=1)
    async with store_sessions() as auth_session:
        await auth_session.execute(select(1))
        assert await limiter.check("login:rollback") == 0
        await auth_session.rollback()

    recreated = SharedAuthRateLimiter(store_sessions, limit=1)
    assert await recreated.check("login:rollback") > 0
    async with store_sessions() as session:
        bucket = await session.get(AuthRateLimitBucket, "login:rollback")
        assert bucket.attempts == 1


_CHILD = """
import asyncio
import json
import sys

from app.core.database import SessionFactory, engine
from app.core.shared_auth_rate_limit import SharedAuthRateLimiter

async def main():
    try:
        limiter = SharedAuthRateLimiter(SessionFactory)
        results = [await limiter.check(sys.argv[1]) for _ in range(8)]
        print(json.dumps(results))
    finally:
        await engine.dispose()

asyncio.run(main())
"""


async def test_four_processes_share_ten_admissions(store_sessions):
    key = "module:" + uuid.uuid4().hex

    async def child():
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-c", _CHILD, key,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=30)
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
        assert process.returncode == 0, "Independent limiter process failed"
        return json.loads(stdout.decode())

    batches = await asyncio.gather(*(child() for _ in range(4)))
    results = [result for batch in batches for result in batch]
    assert len(results) == 32
    assert results.count(0) == 10
    assert all(1 <= result <= 60 for result in results if result != 0)
    async with store_sessions() as session:
        bucket = await session.get(AuthRateLimitBucket, key)
        assert bucket.attempts == 10
