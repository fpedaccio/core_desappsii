"""HTTP behavior when shared authentication admission is unavailable."""

import pytest
from sqlalchemy.exc import SQLAlchemyError


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [TimeoutError, SQLAlchemyError, OSError])
@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/v1/auth/login", {
            "email": "qa-shared-unavailable@example.com",
            "password": "SyntheticPassword9",
        }),
        ("/api/v1/auth/module-token", {
            "module": "qa-shared-unavailable",
            "secret": "synthetic-secret",
        }),
    ],
)
async def test_storage_failure_returns_503(client, monkeypatch, failure, path, payload):
    class Unavailable:
        async def check(self, key):
            raise failure("private-storage-detail")

    app = client._transport.app
    monkeypatch.setattr(app.state, "auth_rate_limiter", Unavailable(), raising=False)
    response = await client.post(path, json=payload)
    assert response.status_code == 503
    assert response.json()["code"] == "AUTH_RATE_LIMIT_UNAVAILABLE"
    assert response.json()["details"] == []
    assert response.headers["retry-after"] == "5"
    assert response.headers["cache-control"] == "no-store"
    assert "private-storage-detail" not in response.text
    assert "synthetic-secret" not in response.text
    assert "SyntheticPassword9" not in response.text
    assert "accessToken" not in response.json()
