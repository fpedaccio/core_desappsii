"""El sobre: lo unico que el Core valida siempre."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.services.envelope import EventEnvelope

VALID = {
    "eventId": "3f6c1b7e-9d24-4a1f-9f2a-2b0f0c7d5e11",
    "eventType": "ticketCreated",
    "occurredAt": "2026-09-08T10:00:00-03:00",
    "sourceModule": "atencion-ciudadana",
    "data": {"ticketId": "TK-1"},
}


def test_acepta_un_sobre_valido():
    envelope = EventEnvelope.model_validate(VALID)
    assert envelope.event_type == "ticketCreated"
    assert envelope.event_version == "1.0"  # default
    assert envelope.data == {"ticketId": "TK-1"}


@pytest.mark.parametrize(
    "occurred_at",
    ["2026-09-08T10:00:00-03:00", "2026-09-08T13:00:00Z", "2026-09-08T10:00:00+00:00"],
)
def test_acepta_fechas_con_offset(occurred_at):
    assert EventEnvelope.model_validate({**VALID, "occurredAt": occurred_at})


@pytest.mark.parametrize(
    "occurred_at", ["2026-09-08T10:00:00", "2026-09-08 10:00:00", "2026-09-08"]
)
def test_rechaza_fechas_sin_zona_horaria(occurred_at):
    """Sin offset no hay forma de ordenar hechos entre 9 modulos desplegados
    por separado, asi que se rechaza en vez de asumir la hora del servidor."""
    with pytest.raises(ValidationError) as exc:
        EventEnvelope.model_validate({**VALID, "occurredAt": occurred_at})
    assert "zona horaria" in str(exc.value)


def test_normaliza_a_utc_conservando_el_original():
    envelope = EventEnvelope.model_validate(VALID)
    assert envelope.occurred_at_utc.hour == 13  # 10:00 -03:00
    assert envelope.to_wire()["occurredAt"].endswith("-03:00")


def test_rechaza_campos_extra_en_el_sobre():
    """Todo lo propio de cada equipo va adentro de `data`."""
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate({**VALID, "prioridad": "ALTA"})


@pytest.mark.parametrize("field", ["eventId", "eventType", "occurredAt", "sourceModule"])
def test_exige_los_campos_minimos(field):
    payload = {k: v for k, v in VALID.items() if k != field}
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate(payload)


@pytest.mark.parametrize("value", ["", "   "])
def test_rechaza_tipo_y_modulo_vacios(value):
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate({**VALID, "eventType": value})
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate({**VALID, "sourceModule": value})


def test_rechaza_event_id_que_no_es_uuid():
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate({**VALID, "eventId": "no-es-un-uuid"})


def test_to_wire_usa_camel_case_y_omite_nulos():
    wire = EventEnvelope.model_validate(VALID).to_wire()
    assert "eventId" in wire and "event_id" not in wire
    assert "causationId" not in wire  # era None


def test_conserva_correlation_y_causation():
    correlation, causation = str(uuid.uuid4()), str(uuid.uuid4())
    envelope = EventEnvelope.model_validate(
        {**VALID, "correlationId": correlation, "causationId": causation}
    )
    assert str(envelope.correlation_id) == correlation
    assert str(envelope.causation_id) == causation
