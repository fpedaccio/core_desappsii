"""Acceso a datos de notificaciones."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload

from app.models.notifications import (
    Channel,
    Notification,
    NotificationPreference,
    NotificationRule,
    NotificationStatus,
    NotificationTemplate,
)
from app.repositories.base import BaseRepository, Page
from app.repositories.event_repository import _enum_value


class NotificationTemplateRepository(BaseRepository[NotificationTemplate]):
    model = NotificationTemplate

    async def get_by_code(self, code: str) -> NotificationTemplate | None:
        return await self.find_one(code=code)

    async def search(
        self,
        *,
        query: str | None = None,
        channel: Channel | None = None,
        active: bool | None = None,
        page: int = 1,
        size: int = 20,
    ) -> Page[NotificationTemplate]:
        stmt = select(NotificationTemplate)
        if query:
            pattern = f"%{query.lower().strip()}%"
            stmt = stmt.where(
                or_(
                    NotificationTemplate.code.ilike(pattern),
                    NotificationTemplate.name.ilike(pattern),
                )
            )
        if channel:
            stmt = stmt.where(NotificationTemplate.channel == channel)
        if active is not None:
            stmt = stmt.where(NotificationTemplate.active.is_(active))
        return await self.paginate(
            stmt.order_by(NotificationTemplate.code), page=page, size=size
        )


class NotificationRuleRepository(BaseRepository[NotificationRule]):
    model = NotificationRule

    def _loaded(self):
        return select(NotificationRule).options(joinedload(NotificationRule.template))

    async def active_for_event_type(self, event_type: str) -> list[NotificationRule]:
        """Las reglas que deciden a quien se le notifica. Todo por configuracion."""
        stmt = (
            self._loaded()
            .where(
                NotificationRule.event_type == event_type,
                NotificationRule.active.is_(True),
            )
            .order_by(NotificationRule.priority)
        )
        return list((await self.session.execute(stmt)).scalars().unique().all())

    async def list_all(self) -> list[NotificationRule]:  # type: ignore[override]
        stmt = self._loaded().order_by(NotificationRule.event_type, NotificationRule.priority)
        return list((await self.session.execute(stmt)).scalars().unique().all())

    async def distinct_event_types(self) -> list[str]:
        """Los tipos de evento a los que el Core tiene que suscribirse para notificar."""
        stmt = (
            select(NotificationRule.event_type)
            .where(NotificationRule.active.is_(True))
            .distinct()
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def find_pair(self, event_type: str, template_id: uuid.UUID) -> NotificationRule | None:
        return await self.find_one(event_type=event_type, template_id=template_id)


class NotificationPreferenceRepository(BaseRepository[NotificationPreference]):
    model = NotificationPreference

    async def is_enabled(self, *, subject_ref: str, channel: Channel, event_type: str) -> bool:
        """Opt-out con precedencia: la preferencia especifica del tipo de evento
        pisa la general del canal. Sin preferencia registrada, se notifica."""
        stmt = select(NotificationPreference).where(
            NotificationPreference.subject_ref == subject_ref,
            NotificationPreference.channel == channel,
            or_(
                NotificationPreference.event_type == event_type,
                NotificationPreference.event_type.is_(None),
            ),
        )
        rows = list((await self.session.execute(stmt)).scalars().all())
        if not rows:
            return True
        specific = next((row for row in rows if row.event_type == event_type), None)
        return specific.enabled if specific else rows[0].enabled

    async def list_for_subject(self, subject_ref: str) -> list[NotificationPreference]:
        stmt = select(NotificationPreference).where(
            NotificationPreference.subject_ref == subject_ref
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def find_exact(
        self, *, subject_ref: str, channel: Channel, event_type: str | None
    ) -> NotificationPreference | None:
        stmt = select(NotificationPreference).where(
            NotificationPreference.subject_ref == subject_ref,
            NotificationPreference.channel == channel,
            NotificationPreference.event_type.is_(None)
            if event_type is None
            else NotificationPreference.event_type == event_type,
        )
        return (await self.session.execute(stmt)).scalars().first()


class NotificationRepository(BaseRepository[Notification]):
    model = Notification

    async def search(
        self,
        *,
        query: str | None = None,
        channel: Channel | None = None,
        status: NotificationStatus | None = None,
        event_type: str | None = None,
        recipient: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> Page[Notification]:
        stmt = select(Notification)
        if query:
            pattern = f"%{query.strip()}%"
            stmt = stmt.where(
                or_(
                    Notification.recipient.ilike(pattern),
                    Notification.subject.ilike(pattern),
                    Notification.template_code.ilike(pattern),
                )
            )
        if channel:
            stmt = stmt.where(Notification.channel == channel)
        if status:
            stmt = stmt.where(Notification.status == status)
        if event_type:
            stmt = stmt.where(Notification.event_type == event_type)
        if recipient:
            stmt = stmt.where(Notification.recipient == recipient)
        return await self.paginate(
            stmt.order_by(Notification.created_at.desc()), page=page, size=size
        )

    async def count_by_status(self, *, since: datetime | None = None) -> dict[str, int]:
        stmt = select(Notification.status, func.count()).group_by(Notification.status)
        if since:
            stmt = stmt.where(Notification.created_at >= since)
        rows = (await self.session.execute(stmt)).all()
        return {str(_enum_value(status)): int(count) for status, count in rows}

    async def count_by_channel(self, *, since: datetime | None = None) -> list[dict]:
        stmt = select(
            Notification.channel, Notification.status, func.count().label("total")
        ).group_by(Notification.channel, Notification.status)
        if since:
            stmt = stmt.where(Notification.created_at >= since)
        rows = (await self.session.execute(stmt)).all()
        return [
            {
                "channel": str(_enum_value(channel)),
                "status": str(_enum_value(status)),
                "total": int(total),
            }
            for channel, status, total in rows
        ]

    async def count_by_template(self, *, limit: int = 10) -> list[dict]:
        stmt = (
            select(Notification.template_code, func.count().label("total"))
            .group_by(Notification.template_code)
            .order_by(func.count().desc())
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).all()
        return [{"templateCode": code, "total": int(total)} for code, total in rows]

    async def list_inbox(self, recipient: str, *, unread_only: bool = False) -> list[Notification]:
        stmt = select(Notification).where(
            Notification.recipient == recipient, Notification.channel == Channel.IN_APP
        )
        if unread_only:
            stmt = stmt.where(Notification.read_at.is_(None))
        return list(
            (await self.session.execute(stmt.order_by(Notification.created_at.desc())))
            .scalars()
            .all()
        )
