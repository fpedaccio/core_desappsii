"""DEF-19: el sourceModule de un evento por AMQP tiene que ser el del publicador.

Por HTTP el modulo sale del token (403 si el sobre declara otro). Por AMQP la
identidad es el usuario de la conexion, que llega en la propiedad `user_id` y
se vincula a un modulo con `AMQP_IDENTITIES`. En `enforce`, lo que no se puede
atribuir va a la DLQ como SOURCE_UNVERIFIED, sin crear el evento ni entregarlo.

En los fixtures, `atencion-ciudadana` publica `ticketCreated` y `obras` lo
consume.
"""

from __future__ import annotations

import json

import pytest

from app.core.config import Settings, settings
from app.messaging.broker import InboundMessage
from app.services.source_identity import (
    IDENTITY_MISSING,
    IDENTITY_UNKNOWN,
    SOURCE_MISMATCH,
    check_source,
)
from app.workers import inbox_worker

IDENTIDADES = {"amqp-atencion": "atencion-ciudadana", "amqp-obras": "obras"}


@pytest.fixture
def worker(monkeypatch, session_factory, broker, seeded):
    """El handler de core.inbox, sobre la base y el broker de los tests."""
    monkeypatch.setattr(inbox_worker, "SessionFactory", session_factory)
    monkeypatch.setattr(inbox_worker, "get_broker", lambda: broker)
    monkeypatch.setattr(settings, "amqp_identities", dict(IDENTIDADES))

    async def _publicar(sobre: dict, *, user_id: str | None, modo: str = "enforce") -> None:
        monkeypatch.setattr(settings, "amqp_source_check", modo)
        await inbox_worker._handle_inbox(
            InboundMessage(
                queue="core.inbox",
                routing_key="",
                raw=json.dumps(sobre).encode(),
                user_id=user_id,
            )
        )

    return _publicar


def _entregas(broker, sobre: dict) -> list:
    return [m for m in broker.published if m.message_id == sobre["eventId"]]


async def _dead_letter(client, admin, sobre: dict) -> dict:
    items = (await client.get("/api/v1/dlq", headers=admin)).json()["items"]
    return next(d for d in items if d["eventId"] == sobre["eventId"])


# ----------------------------------------------------------------------
# La regla
# ----------------------------------------------------------------------
def test_sin_user_id_no_hay_identidad():
    assert check_source(None, "obras", identities=IDENTIDADES).code == IDENTITY_MISSING


def test_un_usuario_sin_vinculo_no_identifica_a_nadie():
    # Una cuenta compartida (como `core`) no se autoriza por su nombre.
    resultado = check_source("core", "core", identities=IDENTIDADES)
    assert resultado.code == IDENTITY_UNKNOWN


def test_un_usuario_vinculado_no_puede_declarar_otro_modulo():
    resultado = check_source("amqp-obras", "atencion-ciudadana", identities=IDENTIDADES)
    assert resultado.code == SOURCE_MISMATCH
    assert resultado.authenticated_module == "obras"


def test_el_usuario_vinculado_publica_como_su_modulo():
    resultado = check_source("amqp-obras", "Obras", identities=IDENTIDADES)
    assert resultado.ok is True
    assert resultado.authenticated_module == "obras"


def test_el_vinculo_se_configura_como_csv_o_json():
    assert Settings(amqp_identities="u1=Obras, u2=rentas").amqp_identities == {
        "u1": "obras",
        "u2": "rentas",
    }
    assert Settings(amqp_identities='{"u1": "Obras"}').amqp_identities == {"u1": "obras"}
    with pytest.raises(ValueError):
        Settings(amqp_identities="u1")


# ----------------------------------------------------------------------
# enforce
# ----------------------------------------------------------------------
async def test_enforce_acepta_al_publicador_legitimo(worker, client, auth, broker, make_envelope):
    sobre = make_envelope()

    await worker(sobre, user_id="amqp-atencion")

    evento = await client.get(f"/api/v1/events/{sobre['eventId']}", headers=await auth("core"))
    assert evento.status_code == 200
    assert evento.json()["ingestionChannel"] == "AMQP"
    assert [m.routing_key for m in _entregas(broker, sobre)] == ["q.obras"]


@pytest.mark.parametrize(
    ("user_id", "codigo"),
    [
        ("amqp-obras", SOURCE_MISMATCH),
        (None, IDENTITY_MISSING),
        ("core", IDENTITY_UNKNOWN),
    ],
)
async def test_enforce_rechaza_sin_entregas_y_lo_deja_auditado(
    worker, client, auth, broker, make_envelope, user_id, codigo
):
    sobre = make_envelope()

    await worker(sobre, user_id=user_id)

    admin = await auth("core")
    # Ni evento ni entregas.
    assert (
        await client.get(f"/api/v1/events/{sobre['eventId']}", headers=admin)
    ).status_code == 404
    assert _entregas(broker, sobre) == []
    # Queda auditado en la DLQ, con la identidad y el origen declarado.
    dead_letter = await _dead_letter(client, admin, sobre)
    assert dead_letter["reasonCode"] == "SOURCE_UNVERIFIED"
    assert dead_letter["sourceModule"] == "atencion-ciudadana"
    assert dead_letter["retryable"] is False
    detalle = (await client.get(f"/api/v1/dlq/{dead_letter['id']}", headers=admin)).json()
    assert detalle["details"][0]["code"] == codigo
    assert detalle["details"][0]["userId"] == user_id
    assert detalle["rawPayload"]["eventId"] == sobre["eventId"]


async def test_el_modulo_suplantado_ve_el_intento_en_su_dlq(worker, client, auth, make_envelope):
    sobre = make_envelope()

    await worker(sobre, user_id="amqp-obras")

    propias = (await client.get("/api/v1/dlq", headers=await auth("atencion-ciudadana"))).json()
    assert sobre["eventId"] in [d["eventId"] for d in propias["items"]]


async def test_el_rechazo_por_identidad_no_se_reintenta(worker, client, auth, make_envelope):
    sobre = make_envelope()
    await worker(sobre, user_id="amqp-obras")
    admin = await auth("core")
    dead_letter = await _dead_letter(client, admin, sobre)

    retry = await client.post(f"/api/v1/dlq/{dead_letter['id']}/retry", headers=admin)

    assert retry.status_code == 409
    assert (
        await client.get(f"/api/v1/events/{sobre['eventId']}", headers=admin)
    ).status_code == 404


async def test_el_rechazo_no_reserva_el_event_id(worker, client, auth, broker, make_envelope):
    """El publicador legitimo puede reenviar el mismo evento con su identidad."""
    sobre = make_envelope()
    await worker(sobre, user_id=None)

    await worker(sobre, user_id="amqp-atencion")

    evento = await client.get(f"/api/v1/events/{sobre['eventId']}", headers=await auth("core"))
    assert evento.status_code == 200
    assert len(_entregas(broker, sobre)) == 1


# ----------------------------------------------------------------------
# warn y off: aceptan (transicion acordada; DEF-19 sin mitigar)
# ----------------------------------------------------------------------
@pytest.mark.parametrize("modo", ["warn", "off"])
async def test_warn_y_off_aceptan_la_discrepancia(
    worker, client, auth, broker, make_envelope, modo
):
    sobre = make_envelope()

    await worker(sobre, user_id="amqp-obras", modo=modo)

    evento = await client.get(f"/api/v1/events/{sobre['eventId']}", headers=await auth("core"))
    assert evento.status_code == 200
    assert evento.json()["sourceModule"] == "atencion-ciudadana"
    assert len(_entregas(broker, sobre)) == 1
