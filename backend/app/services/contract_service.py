"""Catalogo de eventos: tipos, versiones de contrato y compatibilidad.

Es la pieza que convierte al Core en la fuente de verdad de la integracion: el
catalogo documentado que pide el enunciado se **genera** desde estas tablas, no
se escribe a mano, asi que nunca queda desactualizado respecto de lo que el hub
realmente valida.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog

from app.core.database import utcnow
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models.contracts import (
    Compatibility,
    EventContractVersion,
    EventType,
    EventTypeStatus,
)
from app.repositories.base import Page
from app.repositories.contract_repository import (
    ContractVersionRepository,
    EventTypeRepository,
)
from app.services.audit_service import AuditService
from app.services.schema_compat import assert_valid_schema, compare_schemas, validate_payload

logger = structlog.get_logger(__name__)


class ContractService:
    def __init__(
        self,
        *,
        event_type_repo: EventTypeRepository,
        version_repo: ContractVersionRepository,
        audit: AuditService,
    ) -> None:
        self.event_type_repo = event_type_repo
        self.version_repo = version_repo
        self.audit = audit

    # ------------------------------------------------------------------
    # Tipos de evento
    # ------------------------------------------------------------------
    async def search_types(self, **kwargs: Any) -> Page[EventType]:
        return await self.event_type_repo.search(**kwargs)

    async def get_type(self, event_type_id: uuid.UUID) -> EventType:
        event_type = await self.event_type_repo.get_with_versions(event_type_id)
        if event_type is None:
            raise NotFoundError(f"No existe el tipo de evento {event_type_id}.")
        return event_type

    async def get_type_by_name(self, name: str) -> EventType:
        event_type = await self.event_type_repo.get_by_name(name.strip())
        if event_type is None:
            raise NotFoundError(f"No existe el tipo de evento '{name}'.")
        return event_type

    async def create_type(
        self, *, name: str, owner_module: str, description: str = ""
    ) -> EventType:
        normalized = name.strip()
        if not normalized:
            raise ValidationError("El nombre del tipo de evento no puede estar vacio.")
        if await self.event_type_repo.get_by_name(normalized) is not None:
            raise ConflictError(f"Ya existe el tipo de evento '{normalized}'.")

        event_type = EventType(
            name=normalized,
            owner_module=owner_module.strip().lower(),
            description=description,
            status=EventTypeStatus.ACTIVE,
        )
        self.event_type_repo.add(event_type)
        await self.event_type_repo.flush()

        self.audit.record(
            action="EVENT_TYPE_CREATED",
            entity_type="EventType",
            entity_id=str(event_type.id),
            summary=f"Tipo de evento '{normalized}' registrado (propietario: {owner_module}).",
        )
        return event_type

    async def update_type(
        self,
        event_type_id: uuid.UUID,
        *,
        description: str | None = None,
        owner_module: str | None = None,
        status: EventTypeStatus | None = None,
    ) -> EventType:
        event_type = await self.get_type(event_type_id)
        if description is not None:
            event_type.description = description
        if owner_module is not None:
            event_type.owner_module = owner_module.strip().lower()
        if status is not None:
            event_type.status = status

        self.audit.record(
            action="EVENT_TYPE_UPDATED",
            entity_type="EventType",
            entity_id=str(event_type.id),
            summary=f"Tipo de evento '{event_type.name}' actualizado.",
        )
        return event_type

    # ------------------------------------------------------------------
    # Versiones de contrato
    # ------------------------------------------------------------------
    async def list_versions(self, event_type_id: uuid.UUID) -> list[EventContractVersion]:
        await self.get_type(event_type_id)
        return await self.version_repo.list_for_type(event_type_id)

    async def create_version(
        self,
        event_type_id: uuid.UUID,
        *,
        version: str,
        json_schema: dict[str, Any],
        example: dict[str, Any] | None = None,
        publish: bool = False,
    ) -> EventContractVersion:
        """Crea una version y la clasifica contra la anterior.

        La clasificacion se guarda con la version: cuando alguien pregunte por
        que un consumidor dejo de entender un evento, la respuesta esta escrita.
        """
        event_type = await self.get_type(event_type_id)
        normalized = version.strip()
        if not normalized:
            raise ValidationError("La version no puede estar vacia.")

        if await self.version_repo.get_version(event_type.id, normalized) is not None:
            raise ConflictError(
                f"El tipo '{event_type.name}' ya tiene la version '{normalized}'."
            )

        assert_valid_schema(json_schema)
        if example is not None:
            # Si el ejemplo no cumple su propio schema, el schema o el ejemplo
            # estan mal. Mejor enterarse ahora que cuando llegue un evento real.
            validate_payload(json_schema, example)

        previous = await self.version_repo.latest_published(event_type.id)
        compatibility: Compatibility | None = None
        notes: list[dict[str, str]] = []
        if previous is not None:
            compatibility, notes = compare_schemas(previous.json_schema, json_schema)

        contract_version = EventContractVersion(
            event_type_id=event_type.id,
            version=normalized,
            json_schema=json_schema,
            example=example,
            compatibility=compatibility,
            compatibility_notes=notes,
            published_at=utcnow() if publish else None,
        )
        self.version_repo.add(contract_version)
        await self.version_repo.flush()

        self.audit.record(
            action="CONTRACT_VERSION_CREATED",
            entity_type="EventContractVersion",
            entity_id=str(contract_version.id),
            summary=(
                f"Version {normalized} de '{event_type.name}' creada"
                + (f" (compatibilidad: {compatibility})" if compatibility else "")
                + ("y publicada." if publish else ".")
            ),
            changes={
                "compatibility": _value(compatibility) if compatibility else None,
                "notes": notes,
            },
        )
        logger.info(
            "contract_version_created",
            event_type=event_type.name,
            version=normalized,
            compatibility=str(compatibility) if compatibility else None,
            published=publish,
        )
        return contract_version

    async def publish_version(self, version_id: uuid.UUID) -> EventContractVersion:
        version = await self.version_repo.get_required(version_id)
        if version.published_at is not None:
            raise ConflictError(f"La version {version.version} ya esta publicada.")

        version.published_at = utcnow()
        self.audit.record(
            action="CONTRACT_VERSION_PUBLISHED",
            entity_type="EventContractVersion",
            entity_id=str(version.id),
            summary=f"Version {version.version} publicada.",
        )
        return version

    async def deprecate_version(self, version_id: uuid.UUID) -> EventContractVersion:
        """Marca la version como obsoleta sin borrarla.

        Se sigue aceptando en el hub: hay eventos en vuelo y en colas que la
        declaran. Deprecar avisa a los equipos, no rompe la integracion.
        """
        version = await self.version_repo.get_required(version_id)
        version.deprecated_at = utcnow()
        self.audit.record(
            action="CONTRACT_VERSION_DEPRECATED",
            entity_type="EventContractVersion",
            entity_id=str(version.id),
            summary=f"Version {version.version} marcada como obsoleta.",
        )
        return version

    async def check_compatibility(
        self, event_type_id: uuid.UUID, *, candidate_schema: dict[str, Any]
    ) -> dict[str, Any]:
        """Clasifica un schema candidato **sin persistir nada**.

        Sirve para que un equipo pruebe un cambio antes de publicarlo.
        """
        event_type = await self.get_type(event_type_id)
        assert_valid_schema(candidate_schema)

        previous = await self.version_repo.latest_published(event_type.id)
        if previous is None:
            return {
                "compatibility": Compatibility.FULL,
                "baseVersion": None,
                "notes": [],
                "summary": (
                    "No hay una version publicada previa: cualquier schema es "
                    "compatible por definicion."
                ),
            }

        compatibility, notes = compare_schemas(previous.json_schema, candidate_schema)
        breaking = [note for note in notes if note["breaks"] != "NONE"]
        return {
            "compatibility": compatibility,
            "baseVersion": previous.version,
            "notes": notes,
            "summary": _compatibility_summary(compatibility, len(breaking)),
        }

    async def validate_sample(
        self, *, event_type_name: str, version: str, data: dict[str, Any]
    ) -> None:
        """Valida un payload de prueba contra un contrato. Levanta si no cumple.

        Es el endpoint que usan los otros equipos para verificar que su evento va
        a pasar el hub, antes de publicarlo de verdad.
        """
        event_type = await self.get_type_by_name(event_type_name)
        contract_version = await self.version_repo.get_version(event_type.id, version.strip())
        if contract_version is None:
            available = ", ".join(v.version for v in event_type.versions) or "ninguna"
            raise NotFoundError(
                f"El tipo '{event_type_name}' no tiene la version '{version}'. "
                f"Versiones declaradas: {available}."
            )
        validate_payload(contract_version.json_schema, data)

    # ------------------------------------------------------------------
    # Documentacion generada
    # ------------------------------------------------------------------
    async def render_catalog_markdown(self) -> str:
        """Genera `docs/catalogo-eventos.md` desde el estado real del catalogo."""
        types = await self.event_type_repo.list_all_with_versions()

        lines = [
            "# Catalogo de eventos de la plataforma",
            "",
            "> Documento **generado** por el modulo Core "
            "(`GET /api/v1/event-types/catalog.md`). No editar a mano.",
            "",
            f"Tipos registrados: **{len(types)}**.",
            "",
            "## Indice por modulo propietario",
            "",
        ]

        by_module: dict[str, list[EventType]] = {}
        for event_type in types:
            by_module.setdefault(event_type.owner_module, []).append(event_type)

        for module in sorted(by_module):
            names = ", ".join(f"`{et.name}`" for et in by_module[module])
            lines.append(f"- **{module}** ({len(by_module[module])}): {names}")

        lines.extend(["", "---", ""])

        for module in sorted(by_module):
            lines.extend([f"## Modulo `{module}`", ""])
            for event_type in sorted(by_module[module], key=lambda et: et.name):
                lines.extend(
                    [
                        f"### `{event_type.name}`",
                        "",
                        event_type.description or "_Sin descripcion._",
                        "",
                        f"- Estado: `{_value(event_type.status)}`",
                        f"- Versiones: {len(event_type.versions)}",
                        "",
                    ]
                )
                for version in event_type.versions:
                    state = (
                        "obsoleta"
                        if version.deprecated_at
                        else ("publicada" if version.published_at else "borrador")
                    )
                    lines.append(f"#### Version `{version.version}` ({state})")
                    if version.compatibility:
                        lines.append(
                            f"\nCompatibilidad con la version anterior: "
                            f"**{_value(version.compatibility)}**"
                        )
                        for note in version.compatibility_notes or []:
                            if isinstance(note, dict) and note.get("breaks") != "NONE":
                                lines.append(
                                    f"- `{note.get('field')}` — {note.get('change')} "
                                    f"(rompe {note.get('breaks')}): {note.get('detail')}"
                                )
                    lines.extend(
                        [
                            "",
                            "```json",
                            _pretty(version.json_schema),
                            "```",
                            "",
                        ]
                    )
                    if version.example:
                        lines.extend(
                            ["Ejemplo de `data`:", "", "```json", _pretty(version.example), "```", ""]
                        )
        return "\n".join(lines)


def _compatibility_summary(compatibility: Compatibility, breaking_count: int) -> str:
    if compatibility == Compatibility.FULL:
        return "Compatible en ambas direcciones: se puede desplegar sin coordinar."
    if compatibility == Compatibility.BACKWARD:
        return (
            f"Compatible hacia atras ({breaking_count} cambio(s) rompen la lectura de "
            "eventos nuevos por consumidores viejos). Actualiza primero los consumidores."
        )
    if compatibility == Compatibility.FORWARD:
        return (
            f"Compatible hacia adelante ({breaking_count} cambio(s) rompen la lectura de "
            "eventos viejos por consumidores nuevos). Drena las colas antes de desplegar."
        )
    return (
        f"Cambio incompatible: {breaking_count} cambio(s) rompen las dos direcciones. "
        "Publicalo como un tipo de evento nuevo o coordina una ventana con los equipos."
    )


def _value(value: object) -> str:
    return str(getattr(value, "value", value))


def _pretty(payload: Any) -> str:
    import json

    return json.dumps(payload, indent=2, ensure_ascii=False)
