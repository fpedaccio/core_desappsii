"""Regression tests for NUL characters in textual query filters."""

import pytest

FILTERS = [
    ("/api/v1/catalogos/barrios", "zona"),
    ("/api/v1/catalogos/barrios", "q"),
    ("/api/v1/events", "query"),
    ("/api/v1/events", "eventType"),
    ("/api/v1/events", "sourceModule"),
    ("/api/v1/events", "targetModule"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("path", "parameter"), FILTERS)
async def test_null_query_filter_returns_validation_error(client, auth, path, parameter):
    headers = await auth("obras")
    response = await client.get(
        path,
        params={parameter: "before\x00after"},
        headers=headers,
    )

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert any(detail["field"] == parameter for detail in body["details"])
    assert "before" not in response.text
    assert "after" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["", "?rbol ?", "%00"])
async def test_valid_text_search_remains_accepted(client, auth, value):
    headers = await auth("obras")

    for path, parameter in [
        ("/api/v1/catalogos/barrios", "q"),
        ("/api/v1/events", "query"),
    ]:
        response = await client.get(
            path,
            params={parameter: value},
            headers=headers,
        )
        assert response.status_code == 200, response.text
