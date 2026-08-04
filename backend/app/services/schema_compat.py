"""Validacion de payloads y clasificacion de compatibilidad entre versiones.

Funciones puras, sin base de datos: es el "validar contratos y detectar
incompatibilidades" del enunciado, aislado para poder razonarlo y testearlo solo.

Las dos direcciones de compatibilidad, en los terminos de esta plataforma:

* **BACKWARD** - el consumidor *nuevo* puede leer eventos escritos con el
  contrato *viejo*. Se rompe, por ejemplo, si la version nueva agrega un campo
  requerido: los eventos que ya estan en las colas no lo traen.
* **FORWARD** - el consumidor *viejo* puede leer eventos escritos con el
  contrato *nuevo*. Se rompe, por ejemplo, si la version nueva elimina un campo
  que el consumidor viejo daba por seguro.

Importa que sean dos preguntas separadas porque en la plataforma los 9 equipos
despliegan por su cuenta: en cualquier momento hay productores y consumidores en
versiones distintas.
"""

from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator
from jsonschema import SchemaError as JsonSchemaError
from jsonschema import ValidationError as JsonValidationError

from app.core.errors import ContractViolationError, ValidationError
from app.models.contracts import Compatibility

MAX_REPORTED_ERRORS = 20


def assert_valid_schema(schema: dict[str, Any]) -> None:
    """Verifica que el schema en si sea un JSON Schema draft 2020-12 valido."""
    if not isinstance(schema, dict):
        raise ValidationError("El JSON Schema debe ser un objeto.")
    try:
        Draft202012Validator.check_schema(schema)
    except JsonSchemaError as exc:
        raise ValidationError(
            f"El JSON Schema es invalido: {exc.message}", code="INVALID_JSON_SCHEMA"
        ) from exc


def validate_payload(schema: dict[str, Any], data: dict[str, Any]) -> None:
    """Valida el `data` del sobre contra el schema de su version.

    Levanta `ContractViolationError` con la lista de campos que fallaron, para
    que el productor sepa exactamente que corregir.
    """
    if not schema:
        return  # sin schema declarado no hay nada que exigir todavia

    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda err: list(err.absolute_path))
    if not errors:
        return

    details = [
        {
            "field": _path_of(error) or "(raiz)",
            "message": error.message,
            "constraint": error.validator,
        }
        for error in errors[:MAX_REPORTED_ERRORS]
    ]
    if len(errors) > MAX_REPORTED_ERRORS:
        details.append(
            {
                "field": "(...)",
                "message": f"y {len(errors) - MAX_REPORTED_ERRORS} error(es) mas",
                "constraint": "truncated",
            }
        )
    raise ContractViolationError(
        f"El payload no cumple el contrato declarado ({len(errors)} error(es)).",
        details=details,
    )


def _path_of(error: JsonValidationError) -> str:
    return ".".join(str(part) for part in error.absolute_path)


# --------------------------------------------------------------------------
# Compatibilidad entre dos versiones
# --------------------------------------------------------------------------
def compare_schemas(
    old: dict[str, Any], new: dict[str, Any]
) -> tuple[Compatibility, list[dict[str, str]]]:
    """Clasifica el cambio de `old` a `new` y explica cada hallazgo.

    Devuelve el veredicto y una lista de notas, cada una con el campo afectado,
    que direccion rompe y por que.
    """
    notes: list[dict[str, str]] = []
    breaks_backward = False
    breaks_forward = False

    old_props: dict[str, Any] = old.get("properties", {}) or {}
    new_props: dict[str, Any] = new.get("properties", {}) or {}
    old_required = set(old.get("required", []) or [])
    new_required = set(new.get("required", []) or [])
    old_closed = old.get("additionalProperties") is False
    new_closed = new.get("additionalProperties") is False

    # --- campos requeridos ------------------------------------------------
    for field in sorted(new_required - old_required):
        breaks_backward = True
        notes.append(
            {
                "field": field,
                "change": "REQUIRED_ADDED",
                "breaks": "BACKWARD",
                "detail": (
                    "Se volvio obligatorio un campo que antes no lo era: los eventos "
                    "ya publicados no lo traen."
                ),
            }
        )

    for field in sorted(old_required - new_required):
        breaks_forward = True
        notes.append(
            {
                "field": field,
                "change": "REQUIRED_REMOVED",
                "breaks": "FORWARD",
                "detail": (
                    "Dejo de ser obligatorio un campo que los consumidores en la "
                    "version anterior esperan siempre presente."
                ),
            }
        )

    # --- campos agregados y eliminados ------------------------------------
    for field in sorted(set(new_props) - set(old_props)):
        if field in new_required:
            continue  # ya reportado arriba como REQUIRED_ADDED
        if old_closed:
            breaks_forward = True
            notes.append(
                {
                    "field": field,
                    "change": "PROPERTY_ADDED",
                    "breaks": "FORWARD",
                    "detail": (
                        "Se agrego un campo pero la version anterior declara "
                        "additionalProperties:false, asi que lo va a rechazar."
                    ),
                }
            )
        else:
            notes.append(
                {
                    "field": field,
                    "change": "PROPERTY_ADDED",
                    "breaks": "NONE",
                    "detail": "Campo opcional nuevo: compatible en ambas direcciones.",
                }
            )

    for field in sorted(set(old_props) - set(new_props)):
        if field in old_required:
            continue  # ya reportado como REQUIRED_REMOVED
        if new_closed:
            breaks_backward = True
            notes.append(
                {
                    "field": field,
                    "change": "PROPERTY_REMOVED",
                    "breaks": "BACKWARD",
                    "detail": (
                        "Se elimino un campo y la version nueva declara "
                        "additionalProperties:false, asi que rechaza los eventos "
                        "viejos que lo incluyen."
                    ),
                }
            )
        else:
            notes.append(
                {
                    "field": field,
                    "change": "PROPERTY_REMOVED",
                    "breaks": "NONE",
                    "detail": "Campo opcional eliminado: los consumidores lo ignoran.",
                }
            )

    # --- campos que existen en ambas versiones ----------------------------
    for field in sorted(set(old_props) & set(new_props)):
        old_field = old_props[field] or {}
        new_field = new_props[field] or {}

        old_types = _types_of(old_field)
        new_types = _types_of(new_field)
        if old_types and new_types and old_types != new_types:
            if not new_types <= old_types:
                breaks_forward = True
            if not old_types <= new_types:
                breaks_backward = True
            notes.append(
                {
                    "field": field,
                    "change": "TYPE_CHANGED",
                    "breaks": _breaks_label(
                        backward=not old_types <= new_types,
                        forward=not new_types <= old_types,
                    ),
                    "detail": (
                        f"El tipo paso de {sorted(old_types)} a {sorted(new_types)}."
                    ),
                }
            )

        old_enum = set(old_field.get("enum", []) or [])
        new_enum = set(new_field.get("enum", []) or [])
        if old_enum and new_enum and old_enum != new_enum:
            removed = old_enum - new_enum
            added = new_enum - old_enum
            if removed:
                breaks_backward = True
            if added:
                breaks_forward = True
            notes.append(
                {
                    "field": field,
                    "change": "ENUM_CHANGED",
                    "breaks": _breaks_label(backward=bool(removed), forward=bool(added)),
                    "detail": (
                        f"Valores quitados: {sorted(removed) or 'ninguno'}; "
                        f"agregados: {sorted(added) or 'ninguno'}."
                    ),
                }
            )

    verdict = _verdict(breaks_backward=breaks_backward, breaks_forward=breaks_forward)
    return verdict, notes


def _types_of(field_schema: dict[str, Any]) -> set[str]:
    declared = field_schema.get("type")
    if declared is None:
        return set()
    if isinstance(declared, str):
        return {declared}
    return set(declared)


def _breaks_label(*, backward: bool, forward: bool) -> str:
    if backward and forward:
        return "BOTH"
    if backward:
        return "BACKWARD"
    if forward:
        return "FORWARD"
    return "NONE"


def _verdict(*, breaks_backward: bool, breaks_forward: bool) -> Compatibility:
    if breaks_backward and breaks_forward:
        return Compatibility.BREAKING
    if breaks_backward:
        # Se preserva la lectura de datos nuevos por consumidores viejos.
        return Compatibility.FORWARD
    if breaks_forward:
        return Compatibility.BACKWARD
    return Compatibility.FULL
