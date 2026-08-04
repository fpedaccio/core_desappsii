"""Registro de auditoria de acciones administrativas."""

from __future__ import annotations

from typing import Any

from app.core.context import get_actor, get_trace_id
from app.core.database import utcnow
from app.models.monitoring import AuditLog
from app.repositories.monitoring_repository import AuditLogRepository


class AuditService:
    """Deja constancia de quien hizo que. Lo consulta el rol AUDITOR.

    El actor se toma del contexto de la request, para que ningun llamador pueda
    "olvidarse" de informarlo o falsearlo.
    """

    def __init__(self, audit_repo: AuditLogRepository) -> None:
        self.audit_repo = audit_repo

    def record(
        self,
        *,
        action: str,
        entity_type: str,
        entity_id: str | None = None,
        summary: str = "",
        changes: dict[str, Any] | None = None,
        actor: str | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            actor=actor or get_actor() or "system",
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            summary=summary[:255],
            changes=changes,
            trace_id=get_trace_id(),
            occurred_at=utcnow(),
        )
        return self.audit_repo.add(entry)
