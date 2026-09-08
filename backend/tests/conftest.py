"""Fixtures de la suite.

Dos decisiones que hacen que los tests corran en cualquier parte, incluido el CI,
sin infraestructura:

* **SQLite en memoria** en vez de PostgreSQL. Los modelos usan `JSONType`, que es
  JSONB en Postgres y JSON en SQLite, asi que el mismo codigo corre en los dos.
* **`FakeBroker`** en vez de RabbitMQ. Cumple el mismo contrato `Broker` y ademas
  rutea de verdad, asi que los tests del hub verifican que el evento llego a la
  cola correcta sin levantar nada.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_session
from app.core.security import hash_opaque_token, hash_password
from app.main import create_app
from app.messaging.fake import FakeBroker
from app.messaging.provider import set_broker
from app.messaging.topology import full_topology
from app.models.registry import EventType, ModuleAccount, Publication, Subscription
from app.models.users import User

MODULE_SECRET = "test-secret-de-maquina"
"""Secret de maquina de los modulos, para publicar eventos."""

USER_PASSWORD = "Test1234"
"""Contrasena de las personas de prueba: `<modulo>@munitest.com`."""


@pytest_asyncio.fixture
async def engine():
    # StaticPool + una sola conexion: si no, cada sesion abriria su propia base
    # en memoria y no verian los datos de las otras.
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


@pytest_asyncio.fixture
async def broker() -> AsyncIterator[FakeBroker]:
    fake = FakeBroker()
    await fake.connect()
    set_broker(fake)
    yield fake
    set_broker(None)


@pytest_asyncio.fixture
async def seeded(session_factory, broker):
    """Tres modulos con una persona cada uno, y dos tipos de evento.

    `atencion-ciudadana` publica `ticketCreated`, `obras` lo consume, y `core` es
    el admin. Cada modulo tiene su cuenta `<modulo>@munitest.com` y su secret de
    maquina. Alcanza para casi todos los casos.
    """
    async with session_factory() as session:
        modules = {}
        for name, display, is_admin in [
            ("atencion-ciudadana", "Atencion Ciudadana", False),
            ("obras", "Obras Publicas", False),
            ("core", "Core", True),
        ]:
            module = ModuleAccount(
                name=name,
                display_name=display,
                team="test",
                description="",
                secret_hash=hash_opaque_token(MODULE_SECRET),
                is_admin=is_admin,
                active=True,
                queue_name=f"q.{name}",
            )
            session.add(module)
            modules[name] = module

        types = {}
        for type_name in ("ticketCreated", "workOrderScheduled"):
            event_type = EventType(
                name=type_name,
                description="",
                owner_module=None,
                discovered=False,
                json_schema=None,
                total_received=0,
            )
            session.add(event_type)
            types[type_name] = event_type
        await session.flush()

        # Una persona por modulo: es con esto que se entra al dashboard.
        for name, module in modules.items():
            session.add(
                User(
                    email=f"{name}@munitest.com",
                    password_hash=hash_password(USER_PASSWORD),
                    full_name=f"Persona de {name}",
                    module_id=module.id,
                    active=True,
                    failed_login_attempts=0,
                )
            )

        session.add(
            Subscription(
                module_id=modules["obras"].id,
                event_type_id=types["ticketCreated"].id,
                max_attempts=4,
                active=True,
            )
        )
        session.add(
            Publication(
                module_id=modules["atencion-ciudadana"].id,
                event_type_id=types["ticketCreated"].id,
                active=True,
            )
        )
        await session.commit()

    # La topologia tiene que existir para que el FakeBroker rutee.
    await broker.declare(full_topology(["q.obras", "q.atencion-ciudadana"]))
    return {"modules": modules, "types": types}


@pytest_asyncio.fixture
async def client(session_factory, broker, seeded) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def override_get_session():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_session] = override_get_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def auth(client):
    """Headers de la **persona** de un modulo: `await auth("obras")`.

    Es el camino del dashboard, el que usa casi todos los tests.
    """

    async def _login(module: str) -> dict[str, str]:
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": f"{module}@munitest.com", "password": USER_PASSWORD},
        )
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['accessToken']}"}

    return _login


@pytest_asyncio.fixture
async def machine_auth(client):
    """Headers del **backend** de un modulo: `await machine_auth("obras")`.

    Es el camino de publicar eventos, con el secret de maquina.
    """

    async def _token(module: str) -> dict[str, str]:
        response = await client.post(
            "/api/v1/auth/module-token",
            json={"module": module, "secret": MODULE_SECRET},
        )
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['accessToken']}"}

    return _token


def envelope(**overrides):
    """Un sobre valido. Se le pisan los campos que el test necesite."""
    base = {
        "eventId": str(uuid.uuid4()),
        "eventType": "ticketCreated",
        "eventVersion": "1.0",
        "occurredAt": "2026-09-08T10:00:00-03:00",
        "sourceModule": "atencion-ciudadana",
        "data": {"ticketId": "TK-001"},
    }
    base.update(overrides)
    return base


@pytest.fixture
def make_envelope():
    return envelope
