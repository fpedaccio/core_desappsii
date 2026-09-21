"""Modulo Core - pasamanos de eventos de la plataforma municipal.

El Core recibe todos los eventos asincronicos de los 9 modulos, los valida
estructuralmente, guarda evidencia y los entrega a quien este suscripto.

**Lo que el Core NO hace:** no administra usuarios ni ciudadanos, no valida
reglas de negocio de las areas y no interpreta el significado de los eventos.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.api.v1 import auth, dashboard, dlq, events, registry, users
from app.api.v1.schemas.dto import LivenessResponse, ReadinessResponse
from app.core.config import settings
from app.core.context import TRACE_HEADER, set_trace_id
from app.core.database import SessionFactory, engine
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.metrics import ACTIVE_USERS, metrics_middleware
from app.messaging.provider import connect_broker, get_broker
from app.messaging.topology import base_topology
from app.repositories.registry_repository import SubscriptionRepository, UserRepository

logger = structlog.get_logger(__name__)

VERSION = "2.0.0"

DESCRIPTION = """
Pasamanos de eventos de la plataforma municipal distribuida.

## Que hace

Recibe los eventos de los 9 modulos, los valida estructuralmente, guarda
evidencia y los entrega a quien este suscripto. Cada modulo entra con su
credencial y ve **solo su trafico**: lo que publico, lo que recibio y en que
estado quedo cada entrega.

## Que no hace

No administra usuarios ni ciudadanos, no valida reglas de negocio de las areas
y no interpreta el contenido de los eventos.

## Como empezar

1. `POST /api/v1/auth/login` con tu email y contrasena (dashboard), o
   `POST /api/v1/auth/module-token` con el secret del modulo (para publicar
   desde tu backend).
2. `POST /api/v1/subscriptions` para recibir los tipos que te interesan.
3. `POST /api/v1/events` para publicar (o publica en el exchange `muni.inbox`).
4. `GET /api/v1/dashboard` para ver tus estadisticas.

## Dos cosas a tener en cuenta

**`occurredAt` necesita offset de zona horaria.** Un timestamp sin offset se
rechaza: con 9 modulos desplegados por separado no habria forma de ordenar los
hechos.

**`eventId` es la clave de idempotencia.** Un UUID nuevo por evento. Si lo
reenvias, el Core responde `200` con `duplicate: true` y no genera efectos
nuevos.
"""


class TraceMiddleware(BaseHTTPMiddleware):
    """Propaga un `traceId` por request, en los logs y en la respuesta.

    Si el cliente manda `X-Trace-Id`, se respeta: asi se puede seguir una
    operacion que cruza varios modulos.
    """

    async def dispatch(self, request: Request, call_next):
        trace_id = set_trace_id(request.headers.get(TRACE_HEADER))
        response = await call_next(request)
        response.headers[TRACE_HEADER] = trace_id
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    logger.info("core_starting", version=VERSION, environment=settings.environment)

    # El broker puede no estar disponible: el Core arranca igual y sirve la API.
    # Los eventos esperan en core.inbox hasta que vuelva.
    connected = await connect_broker()
    if connected:
        broker = get_broker()
        try:
            # Primero la topologia base (exchanges, retry tiers, DLQ) y despues
            # las colas de los modulos suscriptos.
            await broker.declare(base_topology())
            async with SessionFactory() as session:
                queues = await SubscriptionRepository(session).active_queue_names()
            from app.messaging.topology import full_topology

            await broker.declare(full_topology(queues))
            logger.info("topology_ready", consumer_queues=len(queues))
        except Exception as exc:
            logger.warning("topology_declare_failed_on_startup", error=str(exc))

    yield

    await get_broker().close()
    await engine.dispose()
    logger.info("core_stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Municipalidad UADE - Core",
        description=DESCRIPTION,
        version=VERSION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_tags=[
            {
                "name": "Autenticacion",
                "description": (
                    "Login de personas al dashboard, y token de maquina para que "
                    "el backend de un modulo publique eventos."
                ),
            },
            {
                "name": "Cuentas del dashboard",
                "description": (
                    "Los integrantes de cada equipo. Cada equipo administra las suyas."
                ),
            },
            {
                "name": "Eventos",
                "description": "Publicar eventos y consultar la bitacora.",
            },
            {
                "name": "Registry",
                "description": (
                    "Modulos, tipos de evento, suscripciones y publicaciones. "
                    "Es donde cada equipo se autoadministra."
                ),
            },
            {
                "name": "DLQ y entregas",
                "description": "Lo que fallo y como recuperarlo.",
            },
            {
                "name": "Dashboard",
                "description": "Estadisticas por modulo y vista global del hub.",
            },
            {"name": "Salud", "description": "Probes de liveness y readiness."},
        ],
    )

    app.add_middleware(TraceMiddleware)
    app.middleware("http")(metrics_middleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[TRACE_HEADER],
    )

    register_exception_handlers(app)

    for router in (
        auth.router,
        users.router,
        events.router,
        registry.router,
        dlq.router,
        dashboard.router,
    ):
        app.include_router(router, prefix=settings.api_prefix)

    _register_health(app)
    _register_metrics(app)
    return app


def _register_health(app: FastAPI) -> None:
    @app.get(
        "/health/live",
        response_model=LivenessResponse,
        tags=["Salud"],
        summary="Liveness",
        description="El proceso esta vivo. No toca base ni broker.",
    )
    async def liveness() -> LivenessResponse:
        return LivenessResponse(
            module=settings.module_name,
            version=VERSION,
            environment=settings.environment,
        )

    @app.get(
        "/health/ready",
        response_model=ReadinessResponse,
        tags=["Salud"],
        summary="Readiness",
        description=(
            "Chequea base de datos y broker.\n\n"
            "`degraded` significa base arriba y broker caido: la API sigue "
            "respondiendo y los eventos esperan en `core.inbox` sin perderse. Es "
            "distinto de `down`, que es sin base de datos."
        ),
    )
    async def readiness() -> ReadinessResponse:
        from sqlalchemy import text

        database_ok = True
        database_error: str | None = None
        try:
            async with SessionFactory() as session:
                await session.execute(text("SELECT 1"))
        except Exception as exc:
            database_ok = False
            database_error = f"{type(exc).__name__}: {exc}"

        try:
            broker_ok = await get_broker().healthy()
        except Exception:
            broker_ok = False

        if not database_ok:
            state = "down"
        elif not broker_ok:
            state = "degraded"
        else:
            state = "up"

        return ReadinessResponse(
            status=state,
            checks={
                "database": {
                    "status": "up" if database_ok else "down",
                    "error": database_error,
                },
                "broker": {
                    "status": "up" if broker_ok else "down",
                    "detail": None
                    if broker_ok
                    else "Los eventos quedan encolados en core.inbox hasta que vuelva.",
                },
            },
        )

def _register_metrics(app: FastAPI) -> None:
    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        async with SessionFactory() as session:
            active_users = await UserRepository(session).count_active()

        ACTIVE_USERS.set(active_users)

        return Response(
            content=generate_latest(),
            media_type=CONTENT_TYPE_LATEST,
        )

app = create_app()
