"""Catalogos globales: barrios, zonas y listas de referencia.

El enunciado le asigna al Core "barrios, zonas y catalogos globales" (seccion
10, modulo 9). Es el unico dato de negocio que el Core administra, y existe por
una razon concreta: si cada modulo mantiene su propia lista de barrios, dos
modulos que hablan del mismo lugar van a usar identificadores distintos y los
eventos no se van a poder cruzar.

**Que es de quien.** El Core administra el catalogo *administrativo*: que
barrios existen y en que zona cae cada uno. Las zonas *operativas* de cada area
—los recorridos de recoleccion de Ambiente, por ejemplo— son de ese modulo y se
arman agrupando estos barrios. No son lo mismo y no las administramos nosotros.

**Dos identificadores, los dos estables.** `id` es un UUID y `codigo` es un
slug legible. Ninguno de los dos se reusa nunca: un barrio que deja de existir
se marca `activo = False` pero conserva su identidad, porque hay eventos
historicos que lo referencian.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy import Uuid as SAUuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, JSONType, TimestampMixin


class Zona(Base, TimestampMixin):
    """Una zona administrativa del municipio. Agrupa barrios."""

    __tablename__ = "zonas"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    codigo: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    nombre: Mapped[str] = mapped_column(String(160))
    descripcion: Mapped[str] = mapped_column(Text, default="")
    activo: Mapped[bool] = mapped_column(Boolean, default=True)

    barrios: Mapped[list[Barrio]] = relationship(
        back_populates="zona", lazy="selectin", order_by="Barrio.nombre"
    )


class Barrio(Base, TimestampMixin):
    """Un barrio. Es la unidad territorial que comparten todos los modulos."""

    __tablename__ = "barrios"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    codigo: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    nombre: Mapped[str] = mapped_column(String(160), index=True)
    zona_id: Mapped[uuid.UUID | None] = mapped_column(
        SAUuid, ForeignKey("zonas.id", ondelete="SET NULL"), default=None, index=True
    )
    # Lo que el Core no interpreta pero algun modulo puede necesitar: codigo
    # postal, limites, lo que sea. Se guarda tal cual y no se valida.
    metadatos: Mapped[dict] = mapped_column(JSONType, default=dict)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)

    zona: Mapped[Zona | None] = relationship(back_populates="barrios", lazy="selectin")


class ItemDeCatalogo(Base, TimestampMixin):
    """Una entrada de un catalogo global cualquiera.

    Los "catalogos globales" del enunciado son las listas de referencia que mas
    de un modulo necesita escribir igual: categorias de reclamo, tipos de
    documento, prioridades. En vez de una tabla por lista, una sola tabla con el
    nombre del catalogo adentro: son listas chicas, de lectura, y asi agregar
    una no es una migracion.
    """

    __tablename__ = "items_de_catalogo"
    __table_args__ = (UniqueConstraint("catalogo", "codigo", name="uq_catalogo_codigo"),)

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    catalogo: Mapped[str] = mapped_column(String(60), index=True)
    codigo: Mapped[str] = mapped_column(String(60))
    nombre: Mapped[str] = mapped_column(String(160))
    descripcion: Mapped[str] = mapped_column(Text, default="")
    # Para que todos los modulos muestren la lista en el mismo orden.
    orden: Mapped[int] = mapped_column(Integer, default=0)
    metadatos: Mapped[dict] = mapped_column(JSONType, default=dict)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
