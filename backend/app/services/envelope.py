"""El sobre comun de eventos.

Es el contrato que comparten los 9 modulos de la plataforma (seccion 8 del
enunciado). Se define una sola vez aca y lo usan tanto la ingesta HTTP como el
consumidor AMQP, para que no haya dos validaciones que puedan divergir.

Campos minimos exigidos por el enunciado:
    tipo de evento, identificador unico, fecha y hora, modulo de origen, datos.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

ENVELOPE_EXAMPLE: dict[str, Any] = {
    "eventId": "3f6c1b7e-9d24-4a1f-9f2a-2b0f0c7d5e11",
    "eventType": "ReclamoDerivado",
    "eventVersion": "1.0",
    "occurredAt": "2026-08-04T12:34:56.789-03:00",
    "sourceModule": "atencion-ciudadana",
    "correlationId": "8a1f0c22-5d3e-4b77-9c10-6e2b4a90f3d5",
    "data": {
        "reclamoId": "RC-2026-00184",
        "categoria": "INFRAESTRUCTURA",
        "areaDestino": "obras",
        "prioridad": "ALTA",
    },
}


class EventEnvelope(BaseModel):
    """Sobre de un evento de negocio.

    `occurredAt` **exige** zona horaria: un timestamp sin offset se rechaza en
    vez de asumirse en la hora local del servidor. Eso es lo que hace cumplible
    la regla 4 del enunciado ("fechas en formato estandar y con zona horaria
    definida") en una plataforma con 9 modulos desplegados por separado.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={"example": ENVELOPE_EXAMPLE},
        extra="forbid",
    )

    event_id: uuid.UUID = Field(alias="eventId", description="Identificador unico del evento")
    event_type: str = Field(alias="eventType", min_length=1, max_length=120)
    event_version: str = Field(default="1.0", alias="eventVersion", max_length=20)
    occurred_at: datetime = Field(
        alias="occurredAt", description="ISO-8601 con offset de zona horaria obligatorio"
    )
    source_module: str = Field(alias="sourceModule", min_length=1, max_length=60)
    correlation_id: uuid.UUID | None = Field(default=None, alias="correlationId")
    causation_id: uuid.UUID | None = Field(default=None, alias="causationId")
    data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("occurred_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError(
                "occurredAt debe incluir zona horaria (ej. 2026-08-04T12:34:56-03:00). "
                "Un timestamp sin offset es ambiguo entre modulos."
            )
        return value

    @field_validator("event_type", "source_module")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("El campo no puede quedar vacio.")
        return stripped

    @property
    def occurred_at_utc(self) -> datetime:
        """El instante normalizado a UTC, conservando el original en el sobre."""
        return self.occurred_at.astimezone(timezone.utc)

    def to_wire(self) -> dict[str, Any]:
        """Serializa a la forma canonica (camelCase) que viaja por la cola."""
        return self.model_dump(by_alias=True, mode="json", exclude_none=True)
