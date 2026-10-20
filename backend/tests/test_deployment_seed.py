"""Production bootstrap must fail before touching a database when unsafe."""

import pytest

from app.seeds import __main__ as seed


@pytest.mark.parametrize("password", ["Cambiala123", "short"])
async def test_production_rejects_unsafe_seed_password(monkeypatch, password):
    monkeypatch.setattr(seed.settings, "environment", "production")
    monkeypatch.setattr(seed, "SEED_PASSWORD", password)
    with pytest.raises(RuntimeError, match="SEED_INITIAL_PASSWORD"):
        await seed.run()


async def test_production_refuses_destructive_seed(monkeypatch):
    monkeypatch.setattr(seed.settings, "environment", "production")
    monkeypatch.setattr(seed, "SEED_PASSWORD", "a-safe-test-password")
    with pytest.raises(RuntimeError, match="--drop"):
        await seed.run(drop=True)


def test_production_report_does_not_print_initial_password(monkeypatch, capsys):
    monkeypatch.setattr(seed.settings, "environment", "production")
    monkeypatch.setattr(seed, "SEED_PASSWORD", "a-safe-test-password")
    seed._report({}, {})
    assert "a-safe-test-password" not in capsys.readouterr().out
