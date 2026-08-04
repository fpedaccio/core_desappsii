"""Punto de entrada del backend del modulo Core.

Arranque tolerante a fallas: si el broker no esta disponible, la aplicacion
levanta igual en modo degradado. La API responde, `/health/ready` informa
`degraded` y los eventos esperan en `core.inbox` hasta que el broker vuelva. Es
la regla 7 del enunciado aplicada al propio Core.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import (
    auth,
    catalogs,
    contracts,
    dlq,
    events,
    monitoring,
    notifications,
    registry,
    users,
)
from app.core.config import settings
from app.core.context import TRACE_HEADER, set_actor, set_trace_id
from app.core.database import SessionFactory
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.messaging.provider import connect_broker, get_broker

logger = structlog.get_logger(__name__)

DESCRIPTION = """
Modulo **Core** de la plataforma municipal distribuida (TPO Desarrollo de
Aplicaciones II - UADE). Provee los servicios tecnicos comunes a los 9 modulos:

* **Identidad y acceso.** Proveedor de identidad de la plataforma. Emite JWT
  RS256 y publica su clave en `/.well-known/jwks.json`, para que los otros
  modulos validen tokens *sin llamar al Core*.
* **Catalogos globales.** Dependencias municipales, barrios, zonas y catalogos
  genericos reutilizables.
* **HUB de eventos.** Recibe todos los eventos de negocio, valida el sobre y el
  contrato, guarda evidencia y los rutea a las suscripciones activas.
* **Catalogo de contratos.** Tipos de evento versionados con JSON Schema, con
  clasificacion automatica de compatibilidad (BACKWARD / FORWARD / FULL / BREAKING).
* **Trazabilidad y DLQ.** Bitacora de eventos, entregas, reintentos con backoff y
  Dead Letter Queue con reintento manual auditado.
* **Notificaciones.** Plantillas y reglas configurables por evento.
* **Monitoreo.** Salud de los modulos, tablero tecnico y de comunicaciones.

> El Core **no implementa reglas de negocio de las demas areas**. Valida el sobre
> y el contrato; nunca interpreta el contenido de `data`.

### Como se conecta un modulo

1. Pedir una cuenta de servicio (`POST /api/v1/api-clients`, lo hace un admin).
2. Autenticarse con `POST /api/v1/auth/token` (client_credentials).
3. Registrar sus tipos de evento y contratos (`POST /api/v1/event-types`).
4. Declararse productor y/o suscribirse (`POST /api/v1/registry/...`).
5. Publicar en el exchange `muni.inbox`, o por HTTP con `POST /api/v1/events`.

El contrato del sobre esta en `GET /api/v1/events-meta/envelope-schema`.
"""

TAGS_METADATA = [
    {"name": "Autenticacion", "description": "Login, tokens de servicio y JWKS."},
    {"name": "Usuarios y accesos", "description": "Usuarios, roles, permisos y clientes."},
    {"name": "Catalogos globales", "description": "Dependencias, barrios, zonas y catalogos."},
    {"name": "Catalogo de eventos", "description": "Tipos de evento, contratos y compatibilidad."},
    {"name": "Registry de integracion", "description": "Modulos, productores, suscripciones."},
    {"name": "Hub de eventos", "description": "Ingesta de eventos y trazabilidad."},
    {"name": "Dead Letter Queue", "description": "Entregas fallidas, reintentos y descartes."},
    {"name": "Notificaciones", "description": "Plantillas, reglas, preferencias e historial."},
    {"name": "Monitoreo", "description": "Health checks, tableros y auditoria."},
]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    logger.info("core_starting", environment=settings.environment)

    connected = await connect_broker()
    if connected:
        await _bootstrap_messaging()

    yield

    await get_broker().close()
    logger.info("core_stopped")


async def _bootstrap_messaging() -> None:
    """Declara la topologia y sincroniza las suscripciones propias del Core.

    Best-effort: un fallo aca deja la aplicacion andando y se puede reintentar
    desde `POST /api/v1/registry/topology/apply`.
    """
    from app.services.registry_service import build_registry_service

    try:
        async with SessionFactory() as session:
            service = build_registry_service(session, get_broker())
            await service.ensure_core_module()
            await service.sync_core_subscriptions()
            await service.apply_topology(raise_on_error=False)
            await session.commit()
    except Exception as exc:
        logger.warning("messaging_bootstrap_failed", error=str(exc))


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        description=DESCRIPTION,
        version="1.0.0",
        openapi_tags=TAGS_METADATA,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        contact={"name": "Equipo 9 - Core", "email": "core@muni.uade.edu.ar"},
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[TRACE_HEADER],
    )

    @app.middleware("http")
    async def trace_middleware(request: Request, call_next):
        """Propaga el traceId de punta a punta.

        Si el cliente manda `X-Trace-Id` se respeta, asi una journey iniciada en
        otro modulo se sigue con el mismo identificador. Si no, se genera uno.
        """
        trace_id = set_trace_id(request.headers.get(TRACE_HEADER))
        set_actor(None)
        try:
            response = await call_next(request)
        except Exception:
            # El handler global ya loguea; aca solo se garantiza que el cliente
            # reciba el traceId con el que buscar en los logs.
            logger.exception("request_failed", path=request.url.path)
            response = JSONResponse(
                status_code=500,
                content={
                    "code": "INTERNAL_ERROR",
                    "message": "Ocurrio un error inesperado.",
                    "details": [],
                    "traceId": trace_id,
                },
            )
        response.headers[TRACE_HEADER] = trace_id
        return response

    register_exception_handlers(app)

    prefix = settings.api_prefix
    app.include_router(auth.router, prefix=prefix)
    app.include_router(auth.jwks_router)  # sin prefijo: es una ruta well-known
    app.include_router(users.router, prefix=prefix)
    app.include_router(users.roles_router, prefix=prefix)
    app.include_router(users.permissions_router, prefix=prefix)
    app.include_router(users.clients_router, prefix=prefix)
    app.include_router(catalogs.router, prefix=prefix)
    app.include_router(contracts.router, prefix=prefix)
    app.include_router(registry.router, prefix=prefix)
    app.include_router(events.router, prefix=prefix)
    app.include_router(events.meta_router, prefix=prefix)
    app.include_router(dlq.router, prefix=prefix)
    app.include_router(dlq.deliveries_router, prefix=prefix)
    app.include_router(notifications.router, prefix=prefix)
    app.include_router(monitoring.router, prefix=prefix)
    app.include_router(monitoring.audit_router, prefix=prefix)
    app.include_router(monitoring.health_router)  # sin prefijo: lo usa el deploy

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {
            "module": settings.module_name,
            "name": settings.app_name,
            "docs": "/docs",
            "health": "/health/live",
            "jwks": "/.well-known/jwks.json",
        }

    return app


app = create_app()
