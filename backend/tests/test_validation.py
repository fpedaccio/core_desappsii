"""Validacion del `data`: opcional, y solo si el tipo declaro un schema."""

from __future__ import annotations

import pytest

from app.core.errors import ContractViolationError, ValidationError
from app.services.validation import assert_valid_schema, validate_data

SCHEMA = {
    "type": "object",
    "properties": {
        "ticketId": {"type": "string"},
        "priority": {"type": "string", "enum": ["LOW", "HIGH"]},
    },
    "required": ["ticketId", "priority"],
}


def test_sin_schema_no_valida_nada():
    """Es el comportamiento de pasamanos puro: el `data` pasa sin que lo miren."""
    validate_data(None, {"cualquier": "cosa"})
    validate_data({}, {"cualquier": "cosa"})


def test_acepta_un_payload_que_cumple():
    validate_data(SCHEMA, {"ticketId": "TK-1", "priority": "HIGH"})


def test_reporta_el_campo_obligatorio_que_falta_por_nombre():
    """jsonschema reporta `required` en la raiz del objeto, no en el campo. Sin
    traducirlo, el equipo que publica recibe "(raiz)" y tiene que adivinar."""
    with pytest.raises(ContractViolationError) as exc:
        validate_data(SCHEMA, {"ticketId": "TK-1"})

    campos = [d["field"] for d in exc.value.details]
    assert campos == ["priority"]
    assert exc.value.details[0]["constraint"] == "required"


def test_no_duplica_cuando_faltan_varios_campos():
    """jsonschema emite un error por campo faltante y el traductor expande la
    lista completa en cada uno, asi que hay que deduplicar."""
    with pytest.raises(ContractViolationError) as exc:
        validate_data(SCHEMA, {})

    campos = [d["field"] for d in exc.value.details]
    assert sorted(campos) == ["priority", "ticketId"]
    assert len(campos) == len(set(campos))


def test_reporta_tipo_incorrecto():
    with pytest.raises(ContractViolationError) as exc:
        validate_data(SCHEMA, {"ticketId": 123, "priority": "HIGH"})
    detalle = next(d for d in exc.value.details if d["field"] == "ticketId")
    assert detalle["constraint"] == "type"


def test_reporta_valor_fuera_del_enum():
    with pytest.raises(ContractViolationError) as exc:
        validate_data(SCHEMA, {"ticketId": "TK-1", "priority": "URGENTISIMO"})
    assert any(d["constraint"] == "enum" for d in exc.value.details)


def test_reporta_campos_anidados_con_su_ruta():
    schema = {
        "type": "object",
        "properties": {
            "citizen": {"type": "object", "properties": {"email": {"type": "string"}}}
        },
    }
    with pytest.raises(ContractViolationError) as exc:
        validate_data(schema, {"citizen": {"email": 42}})
    assert exc.value.details[0]["field"] == "citizen.email"


def test_trunca_cuando_hay_demasiados_errores():
    schema = {
        "type": "object",
        "properties": {f"f{i}": {"type": "string"} for i in range(40)},
    }
    with pytest.raises(ContractViolationError) as exc:
        validate_data(schema, {f"f{i}": i for i in range(40)})
    assert len(exc.value.details) <= 21
    assert exc.value.details[-1]["constraint"] == "truncated"


def test_acepta_un_json_schema_valido():
    assert_valid_schema(SCHEMA)


@pytest.mark.parametrize(
    "schema", [{"type": "no-existe"}, {"required": "deberia-ser-lista"}, "no-es-un-objeto"]
)
def test_rechaza_un_json_schema_invalido(schema):
    """Se valida al declararlo: mejor fallar ahi que cuando llegue un evento."""
    with pytest.raises(ValidationError):
        assert_valid_schema(schema)
