"""Catalogos globales: barrios, zonas y listas de referencia.

Es el unico dato de negocio que administra el Core, y esta aca porque el
enunciado se lo asigna al modulo 9 (seccion 10: "barrios, zonas y catalogos
globales"). La razon practica es que si cada modulo mantiene su propia lista de
barrios, dos eventos que hablan del mismo lugar llegan con identificadores
distintos y no se pueden cruzar.

**Se lee por REST, no por eventos.** Un catalogo no es un hecho de negocio: es
configuracion que se consulta cuando hace falta. El enunciado habilita
explicitamente la integracion sincronica "cuando la respuesta sea necesaria
para continuar inmediatamente con una operacion, por ejemplo para validar una
identidad, **consultar una configuracion** o verificar una condicion
indispensable" (seccion 7). Este es ese caso, y asi el Core sigue sin publicar
eventos de negocio.

**Nada se borra.** Un barrio que deja de existir se desactiva. Hay eventos
historicos que lo referencian y el identificador no se puede reusar nunca.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

import structlog

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models.catalog import Barrio, ItemDeCatalogo, Zona
from app.repositories.catalog_repository import (
    BarrioRepository,
    ItemDeCatalogoRepository,
    ZonaRepository,
)

logger = structlog.get_logger(__name__)

_CODIGO = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

# `zonas` y `barrios` tienen sus propias rutas bajo /catalogos. Un catalogo
# generico con esos nombres no rompe nada, pero haria que `/catalogos/zonas`
# devuelva una cosa y `/catalogos/zonas/items` otra, que es confuso de leer.
CATALOGOS_RESERVADOS = {"zonas", "barrios"}


def normalizar_codigo(valor: str) -> str:
    """Un codigo es un slug: minusculas, numeros y guiones simples.

    Se **valida**, no se auto-corrige. Es un identificador estable que viaja en
    el `data` de los eventos: si el Core aceptara `Villa-Elisa` y guardara
    `villa-elisa`, el modulo que lo mando se quedaria con una cadena distinta de
    la que quedo registrada, y sus busquedas posteriores fallarian. Mejor un 422
    en el alta que una divergencia silenciosa.
    """
    codigo = (valor or "").strip()
    if not codigo:
        raise ValidationError("El codigo no puede quedar vacio.")
    if not _CODIGO.match(codigo):
        raise ValidationError(
            f"'{valor}' no es un codigo valido. Se esperan minusculas, numeros y "
            "guiones, por ejemplo 'villa-elisa'."
        )
    return codigo


class CatalogService:
    def __init__(
        self,
        *,
        zona_repo: ZonaRepository,
        barrio_repo: BarrioRepository,
        item_repo: ItemDeCatalogoRepository,
    ) -> None:
        self.zona_repo = zona_repo
        self.barrio_repo = barrio_repo
        self.item_repo = item_repo

    # ------------------------------------------------------------------
    # Zonas
    # ------------------------------------------------------------------
    async def listar_zonas(self, *, solo_activas: bool = False) -> list[Zona]:
        return await self.zona_repo.list_ordered(solo_activas=solo_activas)

    async def obtener_zona(self, codigo: str) -> Zona:
        zona = await self.zona_repo.get_by_codigo(codigo)
        if zona is None:
            raise NotFoundError(f"No existe la zona '{codigo}'.")
        return zona

    async def crear_zona(self, *, codigo: str, nombre: str, descripcion: str = "") -> Zona:
        codigo = normalizar_codigo(codigo)
        if await self.zona_repo.get_by_codigo(codigo) is not None:
            raise ConflictError(f"Ya existe una zona con el codigo '{codigo}'.")
        # `default=` de SQLAlchemy corre en el INSERT, no al construir: sin estos
        # valores explicitos la respuesta se arma antes del flush y sale con
        # `id` y `activo` en null.
        zona = Zona(
            id=uuid.uuid4(),
            codigo=codigo,
            nombre=nombre.strip(),
            descripcion=(descripcion or "").strip(),
            activo=True,
        )
        self.zona_repo.add(zona)
        logger.info("zona_creada", codigo=codigo)
        return zona

    async def actualizar_zona(
        self, codigo: str, *, nombre: str | None = None,
        descripcion: str | None = None, activo: bool | None = None,
    ) -> Zona:
        zona = await self.obtener_zona(codigo)
        if nombre is not None:
            zona.nombre = nombre.strip()
        if descripcion is not None:
            zona.descripcion = descripcion.strip()
        if activo is not None:
            zona.activo = activo
        logger.info("zona_actualizada", codigo=zona.codigo, activo=zona.activo)
        return zona

    # ------------------------------------------------------------------
    # Barrios
    # ------------------------------------------------------------------
    async def listar_barrios(
        self, *, zona: str | None = None, texto: str | None = None, solo_activos: bool = False
    ) -> list[Barrio]:
        return await self.barrio_repo.list_ordered(
            zona_codigo=zona, texto=texto, solo_activos=solo_activos
        )

    async def obtener_barrio(self, codigo: str) -> Barrio:
        barrio = await self.barrio_repo.get_by_codigo(codigo)
        if barrio is None:
            raise NotFoundError(f"No existe el barrio '{codigo}'.")
        return barrio

    async def crear_barrio(
        self, *, codigo: str, nombre: str, zona: str | None = None,
        metadatos: dict[str, Any] | None = None,
    ) -> Barrio:
        codigo = normalizar_codigo(codigo)
        if await self.barrio_repo.get_by_codigo(codigo) is not None:
            raise ConflictError(f"Ya existe un barrio con el codigo '{codigo}'.")
        zona_obj = await self.obtener_zona(zona) if zona else None
        barrio = Barrio(
            id=uuid.uuid4(),
            codigo=codigo,
            nombre=nombre.strip(),
            zona=zona_obj,
            metadatos=metadatos or {},
            activo=True,
        )
        self.barrio_repo.add(barrio)
        logger.info("barrio_creado", codigo=codigo, zona=zona)
        return barrio

    async def actualizar_barrio(
        self, codigo: str, *, nombre: str | None = None, zona: str | None = None,
        metadatos: dict[str, Any] | None = None, activo: bool | None = None,
    ) -> Barrio:
        barrio = await self.obtener_barrio(codigo)
        if nombre is not None:
            barrio.nombre = nombre.strip()
        if zona is not None:
            # Cadena vacia = sacarlo de la zona, sin borrar el barrio.
            barrio.zona = await self.obtener_zona(zona) if zona else None
        if metadatos is not None:
            barrio.metadatos = metadatos
        if activo is not None:
            barrio.activo = activo
        logger.info("barrio_actualizado", codigo=barrio.codigo, activo=barrio.activo)
        return barrio

    # ------------------------------------------------------------------
    # Catalogos genericos
    # ------------------------------------------------------------------
    async def listar_catalogos(self) -> list[str]:
        return await self.item_repo.list_catalogos()

    async def listar_items(
        self, catalogo: str, *, solo_activos: bool = False
    ) -> list[ItemDeCatalogo]:
        return await self.item_repo.list_items(catalogo, solo_activos=solo_activos)

    async def crear_item(
        self, *, catalogo: str, codigo: str, nombre: str, descripcion: str = "",
        orden: int = 0, metadatos: dict[str, Any] | None = None,
    ) -> ItemDeCatalogo:
        catalogo = normalizar_codigo(catalogo)
        if catalogo in CATALOGOS_RESERVADOS:
            raise ValidationError(
                f"'{catalogo}' es un catalogo reservado: tiene su propio endpoint "
                f"en /catalogos/{catalogo}. Elegi otro nombre."
            )
        codigo = normalizar_codigo(codigo)
        if await self.item_repo.get_by_codigo(catalogo, codigo) is not None:
            raise ConflictError(f"El catalogo '{catalogo}' ya tiene un item '{codigo}'.")
        item = ItemDeCatalogo(
            id=uuid.uuid4(),
            catalogo=catalogo, codigo=codigo, nombre=nombre.strip(),
            descripcion=(descripcion or "").strip(), orden=orden,
            metadatos=metadatos or {}, activo=True,
        )
        self.item_repo.add(item)
        logger.info("item_de_catalogo_creado", catalogo=catalogo, codigo=codigo)
        return item

    async def actualizar_item(
        self, catalogo: str, codigo: str, *, nombre: str | None = None,
        descripcion: str | None = None, orden: int | None = None,
        metadatos: dict[str, Any] | None = None, activo: bool | None = None,
    ) -> ItemDeCatalogo:
        item = await self.item_repo.get_by_codigo(catalogo, codigo)
        if item is None:
            raise NotFoundError(f"El catalogo '{catalogo}' no tiene un item '{codigo}'.")
        if nombre is not None:
            item.nombre = nombre.strip()
        if descripcion is not None:
            item.descripcion = descripcion.strip()
        if orden is not None:
            item.orden = orden
        if metadatos is not None:
            item.metadatos = metadatos
        if activo is not None:
            item.activo = activo
        return item
