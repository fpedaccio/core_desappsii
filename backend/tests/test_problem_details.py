"""Todas las respuestas de error siguen Problem Details (RFC 9457) — DEF-14.

El PDF de la catedra (eje C) pide errores en formato Problem Details con los
codigos de estado correctos. Se conservan como extension los campos que la API
ya devolvia (`code`, `message`, `details`, `traceId`) para no romper clientes.
"""

from __future__ import annotations

import uuid
from http import HTTPStatus

import pytest

from app.core.auth_rate_limit import AuthRateLimiter


def _assert_problem(response, status: int, code: str, path: str | None = None) -> dict:
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    # Miembros del estandar.
    assert body["type"] == "about:blank"
    assert body["title"] == HTTPStatus(status).phrase
    assert body["status"] == status
    assert isinstance(body["detail"], str) and body["detail"]
    if path is not None:
        assert body["instance"] == path
    # Extensiones que ya existian.
    assert body["code"] == code
    assert body["message"] == body["detail"]
    assert isinstance(body["details"], list)
    assert "traceId" in body
    # Nunca un stack trace al cliente.
    assert "Traceback" not in response.text
    return body


async def test_401_sin_token(client, make_envelope):
    response = await client.post("/api/v1/events", json=make_envelope())
    _assert_problem(response, 401, "UNAUTHORIZED", "/api/v1/events")


async def test_403_modulo_comun_en_operacion_de_admin(client, auth):
    headers = await auth("obras")
    response = await client.post("/api/v1/modules/obras/rotate-secret", headers=headers)
    _assert_problem(response, 403, "FORBIDDEN", "/api/v1/modules/obras/rotate-secret")


async def test_404_de_negocio(client, auth):
    headers = await auth("obras")
    path = f"/api/v1/events/{uuid.uuid4()}"
    response = await client.get(path, headers=headers)
    _assert_problem(response, 404, "NOT_FOUND", path)


async def test_404_de_ruta_inexistente(client):
    """Antes salia {"detail": "Not Found"}, fuera de la forma comun."""
    response = await client.get("/api/v1/no-existe")
    _assert_problem(response, 404, "NOT_FOUND", "/api/v1/no-existe")


async def test_405_metodo_no_permitido(client):
    response = await client.delete("/api/v1/events")
    body = _assert_problem(response, 405, "METHOD_NOT_ALLOWED", "/api/v1/events")
    assert body["detail"]
    assert "allow" in {k.lower() for k in response.headers}


async def test_409_transicion_invalida(client, auth, make_envelope):
    admin = await auth("core")
    await client.put(
        "/api/v1/event-types/ticketCreated/schema",
        json={"jsonSchema": {"type": "object", "required": ["priority"]}},
        headers=admin,
    )
    origen = await auth("atencion-ciudadana")
    await client.post("/api/v1/events", json=make_envelope(data={}), headers=origen)
    dead_letter_id = (await client.get("/api/v1/dlq", headers=admin)).json()["items"][0]["id"]
    await client.post(
        f"/api/v1/dlq/{dead_letter_id}/discard", json={"reason": "prueba"}, headers=admin
    )

    response = await client.post(f"/api/v1/dlq/{dead_letter_id}/retry", headers=admin)

    _assert_problem(response, 409, "CONFLICT")


async def test_422_validacion_nombra_el_campo(client, auth, make_envelope):
    headers = await auth("atencion-ciudadana")
    response = await client.post(
        "/api/v1/events", json=make_envelope(eventId="no-es-uuid"), headers=headers
    )
    body = _assert_problem(response, 422, "VALIDATION_ERROR", "/api/v1/events")
    assert any(d["field"] == "eventId" for d in body["details"])


async def test_422_parametro_de_consulta_fuera_de_rango(client, auth):
    headers = await auth("obras")
    response = await client.get("/api/v1/dashboard?windowHours=0", headers=headers)
    _assert_problem(response, 422, "VALIDATION_ERROR")


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/v1/auth/login", {"email": "qa-rate@munitest.com", "password": "Incorrecta9"}),
        ("/api/v1/auth/module-token", {"module": "qa-rate", "secret": "incorrecto"}),
    ],
)
async def test_429_rate_limit(client, path, payload):
    client._transport.app.state.auth_rate_limiter = AuthRateLimiter(limit=1, clock=lambda: 0.0)
    await client.post(path, json=payload)

    response = await client.post(path, json=payload)

    _assert_problem(response, 429, "RATE_LIMITED", path)
    assert response.headers["retry-after"] == "60"


async def test_503_limitador_compartido_no_disponible(client, monkeypatch):
    """El 503 que agrego el limitador compartido tambien sale como Problem Details."""

    class Unavailable:
        async def check(self, key):
            raise TimeoutError("private-storage-detail")

    app_state = client._transport.app.state
    monkeypatch.setattr(app_state, "auth_rate_limiter", Unavailable(), raising=False)
    response = await client.post(
        "/api/v1/auth/login", json={"email": "qa-pd@munitest.com", "password": "Incorrecta9"}
    )

    _assert_problem(response, 503, "AUTH_RATE_LIMIT_UNAVAILABLE", "/api/v1/auth/login")
    assert response.headers["retry-after"] == "5"
    assert "private-storage-detail" not in response.text
