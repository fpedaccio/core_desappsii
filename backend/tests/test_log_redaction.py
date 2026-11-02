"""Redaction at field, nested-data and rendered-log boundaries."""

import copy
import io
import json

import pytest
import structlog

from app.core import logging as core_logging
from app.core.log_redaction import REDACTED, redact_log_event


def clean(value):
    return redact_log_event(None, "info", value)


def test_email_redacted_from_field_actor_and_message():
    result = clean({
        "email": "qa-person@example.com",
        "actor": "qa-person@example.com",
        "event": "Login failed for qa-person@example.com",
        "trace_id": "synthetic-trace-123",
    })
    assert "qa-person@example.com" not in json.dumps(result)
    assert result["trace_id"] == "synthetic-trace-123"


@pytest.mark.parametrize("key", [
    "password", "password_hash", "secret", "machineSecret",
    "Authorization", "accessToken", "api_key", "cookie", "jwt_private_key",
])
def test_sensitive_fields_redacted(key):
    assert clean({key: "opaque-sensitive-value"})[key] == REDACTED


def test_nested_data_does_not_mutate_original():
    original = {"items": [{"password": "hidden", "email": "qa@example.com"}]}
    snapshot = copy.deepcopy(original)
    result = clean(original)
    assert original == snapshot
    assert result["items"][0] == {"password": REDACTED, "email": REDACTED}


def test_jwt_and_bearer_redacted_from_free_text():
    jwt = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJxYSJ9.syntheticSignature"
    result = clean({"message": "Bearer opaque-token; jwt=" + jwt})
    rendered = json.dumps(result)
    assert "opaque-token" not in rendered
    assert jwt not in rendered


def test_connection_credentials_redacted():
    result = clean({"error": "amqp://qa-user:opaque-password@rabbitmq:5672/core"})
    assert "qa-user" not in result["error"]
    assert "opaque-password" not in result["error"]
    assert "rabbitmq:5672/core" in result["error"]


def test_private_key_redacted_from_free_text():
    value = "-----BEGIN PRIVATE KEY-----\nsynthetic-content\n-----END PRIVATE KEY-----"
    assert clean({"message": value})["message"] == REDACTED


def test_numbers_booleans_and_none_preserved():
    assert clean({"attempts": 4, "active": False, "value": None}) == {
        "attempts": 4, "active": False, "value": None,
    }


def test_recursive_data_is_bounded():
    value = {}
    value["self"] = value
    result = clean(value)
    assert REDACTED in json.dumps(result)


def test_redactor_is_after_exception_formatting_and_before_renderer(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        core_logging.structlog, "configure",
        lambda **kwargs: captured.update(kwargs),
    )
    core_logging.configure_logging()
    processors = captured["processors"]
    assert processors.index(redact_log_event) > processors.index(
        structlog.processors.format_exc_info
    )
    assert processors[-2] is redact_log_event

    stream = io.StringIO()
    logger = structlog.wrap_logger(
        structlog.PrintLogger(file=stream),
        processors=[redact_log_event, structlog.processors.JSONRenderer()],
    )
    logger.info("qa-log", email="qa@example.com", password="opaque-sensitive-value")
    output = stream.getvalue()
    assert "qa@example.com" not in output
    assert "opaque-sensitive-value" not in output
    assert REDACTED in output
