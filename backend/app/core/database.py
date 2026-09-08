"""Motor y sesiones de SQLAlchemy (capa de acceso a datos).

Los tipos se declaran de forma portable: `JSONType` usa JSONB en PostgreSQL
(produccion) y JSON en SQLite, para que la suite de tests corra sin necesidad
de tener un PostgreSQL levantado.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON

from app.core.config import settings

JSONType = JSON().with_variant(JSONB(), "postgresql")
"""Columna de documento libre: JSONB en Postgres, JSON en SQLite."""

TimestampTZ = DateTime(timezone=True)
"""Todas las fechas se guardan con zona horaria (regla 4 del enunciado)."""


def utcnow() -> datetime:
    return datetime.now(UTC)


NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(AsyncAttrs, DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        TimestampTZ, server_default=func.now(), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TimestampTZ,
        server_default=func.now(),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


engine = create_async_engine(
    settings.database_url,
    echo=settings.db_echo,
    pool_pre_ping=True,  # reconecta si la DB se reinicio (tolerancia a caidas)
    future=True,
)

SessionFactory = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Dependencia de FastAPI: una sesion (y una transaccion) por request."""
    async with SessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
