"""Catalogos globales: dependencias municipales, barrios, zonas y catalogos genericos.

Estos son los datos de referencia que el Core provee a toda la plataforma, para
que los 9 modulos hablen del mismo barrio y de la misma area sin duplicar tablas.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy import Uuid as SAUuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, JSONType, TimestampMixin


class Dependencia(Base, TimestampMixin):
    """Area o dependencia municipal (Obras, Rentas, Transito, ...)."""

    __tablename__ = "dependencias"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    # Jerarquia: una dependencia puede depender de otra.
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        SAUuid, ForeignKey("dependencias.id", ondelete="SET NULL"), default=None
    )
    contact_email: Mapped[str | None] = mapped_column(String(255), default=None)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    parent: Mapped[Dependencia | None] = relationship(remote_side=[id])


class Zona(Base, TimestampMixin):
    """Zona operativa. Agrupa barrios para recorridos, cuadrillas y operativos."""

    __tablename__ = "zonas"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    barrios: Mapped[list[Barrio]] = relationship(back_populates="zona")


class Barrio(Base, TimestampMixin):
    __tablename__ = "barrios"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    zona_id: Mapped[uuid.UUID | None] = mapped_column(
        SAUuid, ForeignKey("zonas.id", ondelete="SET NULL"), default=None, index=True
    )
    postal_code: Mapped[str | None] = mapped_column(String(20), default=None)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    zona: Mapped[Zona | None] = relationship(back_populates="barrios", lazy="joined")


class CatalogType(Base, TimestampMixin):
    """Tipo de catalogo generico.

    Evita crear una tabla nueva cada vez que un modulo necesita una lista de
    referencia (categorias de reclamo, rubros comerciales, tipos de tributo...).
    """

    __tablename__ = "catalog_types"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    owner_module: Mapped[str] = mapped_column(String(60), default="core")

    items: Mapped[list[CatalogItem]] = relationship(
        back_populates="catalog_type", cascade="all, delete-orphan"
    )


class CatalogItem(Base, TimestampMixin):
    __tablename__ = "catalog_items"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    catalog_type_id: Mapped[uuid.UUID] = mapped_column(
        SAUuid, ForeignKey("catalog_types.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(80), index=True)
    label: Mapped[str] = mapped_column(String(200))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        SAUuid, ForeignKey("catalog_items.id", ondelete="SET NULL"), default=None
    )
    sort_order: Mapped[int] = mapped_column(default=0)
    # Atributos libres del item (ej. sla_horas, requiere_inspeccion).
    attributes: Mapped[dict] = mapped_column(JSONType, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    catalog_type: Mapped[CatalogType] = relationship(back_populates="items")

    # El code es unico dentro de su catalogo, no globalmente.
    __table_args__ = (
        UniqueConstraint("catalog_type_id", "code", name="uq_catalog_items_type_code"),
    )
