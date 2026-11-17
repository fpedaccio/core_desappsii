"""Authentication throttling boundaries and HTTP integration."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from app.core.auth_rate_limit import AuthRateLimiter


def test_window_boundary_and_retry_after():
    now = [0.0]
    limiter = AuthRateLimiter(limit=2, clock=lambda: now[0])
    assert limiter.check("account") == 0
    assert limiter.check("account") == 0
    assert limiter.check("account") == 60
    now[0] = 59.2
    assert limiter.check("account") == 1
    now[0] = 60.0
    assert limiter.check("account") == 0


def test_independent_keys():
    limiter = AuthRateLimiter(limit=1)
    assert limiter.check("login:a") == 0
    assert limiter.check("login:a") > 0
    assert limiter.check("login:b") == 0
    assert limiter.check("module:a") == 0


def test_capacity_preserves_existing_counters():
    now = [0.0]
    limiter = AuthRateLimiter(limit=1, capacity=1, clock=lambda: now[0])
    assert limiter.check("a") == 0
    assert limiter.check("b") == 60
    assert limiter.check("a") == 60
    now[0] = 60
    assert limiter.check("b") == 0


def test_concurrent_admissions_are_bounded():
    limiter = AuthRateLimiter(limit=10, clock=lambda: 0.0)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: limiter.check("a"), range(100)))
    assert results.count(0) == 10
    assert results.count(60) == 90


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/v1/auth/login", {
            "email": "qa-rate-unknown@example.com", "password": "InvalidPassword9",
        }),
        ("/api/v1/auth/module-token", {
            "module": "qa-rate-unknown", "secret": "invalid-synthetic-secret",
        }),
    ],
)
async def test_auth_http_limit_and_recovery(client, path, payload):
    now = [0.0]
    client._transport.app.state.auth_rate_limiter = AuthRateLimiter(
        limit=2, clock=lambda: now[0]
    )
    for _ in range(2):
        response = await client.post(path, json=payload)
        assert response.status_code == 401, response.text

    response = await client.post(path, json=payload)
    assert response.status_code == 429
    assert response.json()["code"] == "RATE_LIMITED"
    assert response.json()["details"] == []
    assert response.headers["retry-after"] == "60"
    assert response.headers["cache-control"] == "no-store"
    assert "invalid-synthetic-secret" not in response.text
    assert "InvalidPassword9" not in response.text
    assert "qa-rate-unknown" not in response.text

    now[0] = 60
    response = await client.post(path, json=payload)
    assert response.status_code == 401, response.text
