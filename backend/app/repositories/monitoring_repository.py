"""Acceso a datos de monitoreo y auditoria."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, or_, select

from app.models.monitoring import AuditLog, HealthCheck, HealthStatus
from app.repositories.base import BaseRepository, Page


class HealthCheckRepository(BaseRepository[HealthCheck]):
    model = HealthCheck

    async def latest_per_module(self) -> list[HealthCheck]:
        """Ultimo sondeo de cada modulo, que es lo que muestra el dashboard."""
        newest = (
            select(
                HealthCheck.module_name,
                func.max(HealthCheck.checked_at).label("checked_at"),
            )
            .group_by(HealthCheck.module_name)
            .subquery()
        )
        stmt = select(HealthCheck).join(
            newest,
            (HealthCheck.module_name == newest.c.module_name)
            & (HealthCheck.checked_at == newest.c.checked_at),
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def history(
        self, module_name: str, *, since: datetime | None = None, limit: int = 100
    ) -> list[HealthCheck]:
        stmt = select(HealthCheck).where(HealthCheck.module_name == module_name)
        if since:
            stmt = stmt.where(HealthCheck.checked_at >= since)
        return list(
            (await self.session.execute(stmt.order_by(HealthCheck.checked_at.desc()).limit(limit)))
            .scalars()
            .all()
        )

    async def uptime_ratio(self, module_name: str, *, since: datetime) -> float:
        """Proporcion de sondeos exitosos en la ventana. 1.0 = siempre arriba."""
        total_stmt = (
            select(func.count())
            .select_from(HealthCheck)
            .where(HealthCheck.module_name == module_name, HealthCheck.checked_at >= since)
        )
        total = int((await self.session.execute(total_stmt)).scalar_one())
        if not total:
            return 0.0
        up_stmt = (
            select(func.count())
            .select_from(HealthCheck)
            .where(
                HealthCheck.module_name == module_name,
                HealthCheck.checked_at >= since,
                HealthCheck.status == HealthStatus.UP,
            )
        )
        up = int((await self.session.execute(up_stmt)).scalar_one())
        return round(up / total, 4)


class AuditLogRepository(BaseRepository[AuditLog]):
    model = AuditLog

    async def search(
        self,
        *,
        query: str | None = None,
        actor: str | None = None,
        action: str | None = None,
        entity_type: str | None = None,
        since: datetime | None = None,
        page: int = 1,
        size: int = 20,
    ) -> Page[AuditLog]:
        stmt = select(AuditLog)
        if query:
            pattern = f"%{query.strip()}%"
            stmt = stmt.where(
                or_(
                    AuditLog.summary.ilike(pattern),
                    AuditLog.actor.ilike(pattern),
                    AuditLog.entity_id.ilike(pattern),
                )
            )
        if actor:
            stmt = stmt.where(AuditLog.actor == actor)
        if action:
            stmt = stmt.where(AuditLog.action == action)
        if entity_type:
            stmt = stmt.where(AuditLog.entity_type == entity_type)
        if since:
            stmt = stmt.where(AuditLog.occurred_at >= since)
        return await self.paginate(
            stmt.order_by(AuditLog.occurred_at.desc()), page=page, size=size
        )
