"""Validacion de la estructura de un evento.

Dos niveles, y conviene tenerlos separados en la cabeza:

1. **El sobre** lo valida `EventEnvelope` (pydantic): que `eventId` sea un UUID,
   que `occurredAt` traiga offset de zona horaria, que haya `eventType` y
   `sourceModule`. Sin eso el hub no puede ni deduplicar ni rutear, asi que no
   es opcional.

2. **El `data`** se valida aca, contra el JSON Schema que el tipo de evento
   haya declarado. Es **opcional**: un tipo sin schema pasa sin que le miren el
   payload.

Lo que no se valida en ningun caso es la *semantica* del evento. Que un reclamo
critico deba escalarse o que una habilitacion vencida no permita operar son
reglas de las areas, no del pasamanos.
"""

from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator
from jsonschema import SchemaError as JsonSchemaError

from app.core.errors import ContractViolationError, ValidationError

MAX_REPORTED_ERRORS = 20


def assert_valid_schema(schema: dict[str, Any]) -> None:
    """Verifica que el schema en si sea un JSON Schema valido, al declararlo."""
    if not isinstance(schema, dict):
        raise ValidationError("El JSON Schema debe ser un objeto.")
    try:
        Draft202012Validator.check_schema(schema)
    except JsonSchemaError as exc:
        raise ValidationError(
            f"El JSON Schema es invalido: {exc.message}", code="INVALID_JSON_SCHEMA"
        ) from exc


def validate_data(schema: dict[str, Any] | None, data: dict[str, Any]) -> None:
    """Valida el `data` del sobre. Sin schema declarado no hace nada.

    Levanta `ContractViolationError` con la lista de campos que fallaron, para
    que el equipo que publica sepa exactamente que corregir.
    """
    if not schema:
        return

    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda err: list(err.absolute_path))
    if not errors:
        return

    # jsonschema emite un error `required` por cada campo faltante y `_describe`
    # expande la lista completa en cada uno, asi que hay que deduplicar.
    details: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for error in errors:
        for detail in _describe(error):
            key = (detail["field"], detail["constraint"])
            if key in seen:
                continue
            seen.add(key)
            details.append(detail)
        if len(details) >= MAX_REPORTED_ERRORS:
            break
    details = details[:MAX_REPORTED_ERRORS]
    if len(errors) > MAX_REPORTED_ERRORS:
        details.append(
            {
                "field": "(...)",
                "message": f"y {len(errors) - MAX_REPORTED_ERRORS} error(es) mas",
                "constraint": "truncated",
            }
        )

    raise ContractViolationError(
        f"El `data` no cumple el schema declarado para este tipo de evento "
        f"({len(errors)} error(es)).",
        details=details,
    )


def _describe(error) -> list[dict[str, str]]:
    """Traduce un error de jsonschema a uno o mas detalles con el campo culpable.

    El caso de `required` necesita trato especial: jsonschema lo reporta en la
    raiz del objeto, no en el campo que falta, asi que sin esto el equipo que
    publica recibe "(raiz)" y tiene que adivinar cual era. Se expande a un
    detalle por campo faltante, con su nombre.
    """
    base_path = ".".join(str(part) for part in error.absolute_path)

    if error.validator == "required" and isinstance(error.instance, dict):
        missing = [field for field in (error.validator_value or []) if field not in error.instance]
        if missing:
            return [
                {
                    "field": f"{base_path}.{field}" if base_path else field,
                    "message": "Es un campo obligatorio y no vino en el `data`.",
                    "constraint": "required",
                }
                for field in missing
            ]

    return [
        {
            "field": base_path or "(raiz)",
            "message": error.message,
            "constraint": str(error.validator),
        }
    ]
