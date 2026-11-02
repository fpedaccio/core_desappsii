"""ETag e If-Match para actualizaciones concurrentes (RFC 9110, secciones 8.8.3 y 13.1.1).

El ETag se calcula con el estado *editable* del recurso, no con sus contadores:
`totalReceived` o `lastSeenAt` cambian con cada evento que llega y harian fallar
con 412 a un cliente que no piso nada. Es un validador fuerte (sin `W/`).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.models.registry import EventType


def strong_etag(state: dict[str, Any]) -> str:
    """Un ETag fuerte y estable para un estado serializable."""
    canonical = json.dumps(
        state, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )
    return '"' + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32] + '"'


def event_type_etag(event_type: EventType) -> str:
    """Lo que cambia un PUT/POST sobre el tipo; no los contadores de trafico."""
    return strong_etag(
        {
            "name": event_type.name,
            "ownerModule": event_type.owner_module,
            "description": event_type.description,
            "discovered": event_type.discovered,
            "jsonSchema": event_type.json_schema,
        }
    )


def if_match_satisfied(if_match: str, current_etag: str) -> bool:
    """Evalua If-Match con comparacion fuerte.

    `*` vale si el recurso existe (aca siempre: si no existe ya se respondio 404).
    Un ETag debil (`W/"..."`) nunca coincide con comparacion fuerte.
    """
    candidates = [c.strip() for c in if_match.split(",") if c.strip()]
    if "*" in candidates:
        return True
    return any(not c.startswith("W/") and c == current_etag for c in candidates)
