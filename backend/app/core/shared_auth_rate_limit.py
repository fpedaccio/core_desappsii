"""PostgreSQL-backed authentication admission windows.

Each check commits independently of the authentication transaction.
All instances using this database coordinate through the same advisory lock.
Only endpoint paths and identity digests belong in keys.
"""

import asyncio
import math
from datetime import timedelta

from sqlalchemy import delete, func, select, text

from app.models.auth_rate_limit import AuthRateLimitBucket

# Reserved application namespace for authentication admission accounting.
_LOCK_NAMESPACE = 1129271877
_LOCK_RESOURCE = 1


class SharedAuthRateLimiter:
    """Bounded fixed windows shared by API processes using PostgreSQL."""

    def __init__(
        self,
        sessions,
        *,
        limit: int = 10,
        window: float = 60,
        capacity: int = 5000,
        timeout: float = 5,
    ) -> None:
        if (
            limit < 1
            or not math.isfinite(window)
            or window <= 0
            or capacity < 1
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("Limiter settings must be positive and finite")
        self.sessions = sessions
        self.limit = limit
        self.window = window
        self.capacity = capacity
        self.timeout = timeout

    async def check(self, key: str) -> int:
        """Return zero if admitted, otherwise Retry-After seconds.

        Storage errors propagate. Callers must reject authentication rather
        than fall back to independent in-memory counters.
        """
        if not key or len(key) > 256:
            raise ValueError("Invalid limiter key")

        async with asyncio.timeout(self.timeout):
            async with self.sessions() as session, session.begin():
                if session.get_bind().dialect.name != "postgresql":
                    raise RuntimeError("Shared limiter requires PostgreSQL")

                # Serializes capacity checks and updates across processes.
                # The lock is released on transaction commit or rollback.
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(:namespace, :resource)"),
                    {"namespace": _LOCK_NAMESPACE, "resource": _LOCK_RESOURCE},
                )
                # Read the database clock AFTER acquiring the lock.
                now = await session.scalar(select(func.clock_timestamp()))
                await session.execute(
                    delete(AuthRateLimitBucket).where(
                        AuthRateLimitBucket.expires_at <= now
                    )
                )

                bucket = await session.get(AuthRateLimitBucket, key)
                if bucket is not None:
                    if bucket.attempts >= self.limit:
                        return max(
                            1, math.ceil((bucket.expires_at - now).total_seconds())
                        )
                    bucket.attempts += 1
                    return 0

                count = await session.scalar(
                    select(func.count()).select_from(AuthRateLimitBucket)
                )
                if count >= self.capacity:
                    earliest = await session.scalar(
                        select(func.min(AuthRateLimitBucket.expires_at))
                    )
                    return max(1, math.ceil((earliest - now).total_seconds()))

                session.add(
                    AuthRateLimitBucket(
                        key=key,
                        expires_at=now + timedelta(seconds=self.window),
                        attempts=1,
                    )
                )
                return 0
