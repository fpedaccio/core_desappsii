"""Publication timestamp updates against real PostgreSQL."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.models.registry import ModuleAccount
from app.repositories.registry_repository import ModuleRepository


async def test_publication_timestamp_updates_only_target_and_does_not_commit(real):
    suffix = uuid.uuid4().hex[:12]
    target = "qa-timestamp-" + suffix
    other = "qa-other-" + suffix
    missing = "qa-missing-" + suffix
    before = datetime(2026, 1, 1, tzinfo=UTC)
    after = datetime(2026, 1, 2, tzinfo=UTC)

    async with real.sessions() as session:
        try:
            session.add_all([
                ModuleAccount(
                    name=target, display_name="Timestamp target",
                    active=True, last_publish_at=before,
                ),
                ModuleAccount(
                    name=other, display_name="Timestamp control",
                    active=True, last_publish_at=before,
                ),
            ])
            await session.flush()
            repo = ModuleRepository(session)
            await repo.record_publication(
                "  " + target.upper() + "  ", published_at=after,
            )
            await repo.record_publication(missing, published_at=after)

            rows = (await session.execute(
                select(
                    ModuleAccount.name,
                    ModuleAccount.display_name,
                    ModuleAccount.active,
                    ModuleAccount.last_publish_at,
                ).where(ModuleAccount.name.in_([target, other, missing]))
            )).all()
            actual = {
                name: (display, active, timestamp)
                for name, display, active, timestamp in rows
            }
            assert actual == {
                target: ("Timestamp target", True, after),
                other: ("Timestamp control", True, before),
            }
        finally:
            await session.rollback()

    async with real.sessions() as session:
        remaining = (await session.execute(
            select(ModuleAccount.name).where(
                ModuleAccount.name.in_([target, other, missing])
            )
        )).scalars().all()
        assert remaining == []
