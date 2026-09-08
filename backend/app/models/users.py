"""Personas que entran al dashboard.

Cada integrante de un equipo tiene su propio login, atado a **un** modulo. No hay
roles ni permisos: lo que una persona puede ver y hacer sale de su modulo, y el
unico privilegio es el `is_admin` del modulo (el equipo 9, que ve el trafico de
todos en vez de solo el propio).

Es deliberadamente chico. El Core no es el proveedor de identidad de la
plataforma: no sabe de ciudadanos ni de usuarios finales del municipio, solo de
las personas que administran la integracion.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy import Uuid as SAUuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin, TimestampTZ


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(180))

    # A que equipo pertenece. Determina que datos ve.
    module_id: Mapped[uuid.UUID] = mapped_column(
        SAUuid, ForeignKey("modules.id", ondelete="CASCADE"), index=True
    )

    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(TimestampTZ, default=None)
    failed_login_attempts: Mapped[int] = mapped_column(default=0)

    module: Mapped[ModuleAccount] = relationship(  # noqa: F821
        back_populates="users", lazy="joined"
    )
