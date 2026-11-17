"""Dashboard registry projections against real PostgreSQL."""

import uuid

from sqlalchemy import select

from app.models.registry import EventType, ModuleAccount, Publication, Subscription
from app.repositories.registry_repository import ModuleRepository


async def test_dashboard_registry_preserves_scope_activity_and_order(real):
    suffix = uuid.uuid4().hex[:12]
    names = ["qa-registry-" + suffix + ending for ending in ("", "-other", "-empty")]
    type_names = [suffix + ending for ending in ("Z", "M", "A")]
    empty_result = {
        "subscriptions": {"total": 0, "active": 0, "eventTypes": []},
        "publications": {"declared": []},
    }

    async with real.sessions() as session:
        try:
            modules = [
                ModuleAccount(name=name, display_name=name, active=index != 0)
                for index, name in enumerate(names)
            ]
            types = [EventType(name=name) for name in type_names]
            session.add_all(modules + types)
            await session.flush()

            for index, event_type in enumerate(types):
                session.add(Subscription(
                    module_id=modules[0].id,
                    event_type_id=event_type.id,
                    active=index != 1,
                ))
                session.add(Publication(
                    module_id=modules[0].id,
                    event_type_id=event_type.id,
                    active=index != 1,
                ))
            session.add(Subscription(
                module_id=modules[1].id, event_type_id=types[1].id, active=True,
            ))
            session.add(Publication(
                module_id=modules[1].id, event_type_id=types[1].id, active=True,
            ))
            await session.flush()

            repo = ModuleRepository(session)
            expected_names = sorted([type_names[0], type_names[2]])
            assert await repo.dashboard_registry(" " + names[0].upper() + " ") == {
                "subscriptions": {
                    "total": 3, "active": 2, "eventTypes": expected_names,
                },
                "publications": {"declared": expected_names},
            }
            assert await repo.dashboard_registry(names[1]) == {
                "subscriptions": {
                    "total": 1, "active": 1, "eventTypes": [type_names[1]],
                },
                "publications": {"declared": [type_names[1]]},
            }
            assert await repo.dashboard_registry(names[2]) == empty_result
            assert await repo.dashboard_registry(names[0] + "-missing") == empty_result
        finally:
            await session.rollback()

    async with real.sessions() as session:
        assert (await session.execute(
            select(ModuleAccount.id).where(ModuleAccount.name.in_(names))
        )).scalars().all() == []
        assert (await session.execute(
            select(EventType.id).where(EventType.name.in_(type_names))
        )).scalars().all() == []
