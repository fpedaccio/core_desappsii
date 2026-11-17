"""Registry: modulos, tipos de evento, suscripciones y publicaciones.

Es donde cada equipo se autoadministra: se suscribe a lo que quiere recibir y
declara lo que publica. Un modulo solo puede tocar lo suyo; el admin puede
hacerlo por cualquiera.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Header, Query, Response, status

from app.api.deps import AdminDep, AuthDep, CallerDep, RegistryDep, StatsDep
from app.api.v1.schemas.common import MessageResponse, PageResponse, problem_responses
from app.api.v1.schemas.dto import (
    EventTypeCreate,
    EventTypeMapEntry,
    EventTypeResponse,
    ModuleCreate,
    ModuleResponse,
    ModuleUpdate,
    PublicationCreate,
    PublicationResponse,
    SchemaUpdate,
    SecretResponse,
    SubscriptionCreate,
    SubscriptionResponse,
    TopologyResponse,
)
from app.core.etag import event_type_etag

router = APIRouter(tags=["Registry"], responses=problem_responses(401))

ETAG_HEADER_DOC = {
    "ETag": {
        "description": (
            "ETag fuerte entre comillas que identifica la version actual del tipo "
            "de evento. Enviarlo en `If-Match` al actualizar el schema."
        ),
        "schema": {"type": "string"},
    }
}

PRECONDITION_FAILED_DOC = {
    412: {
        "description": (
            "If-Match desactualizado: el tipo cambio despues de leerlo. No se aplico "
            "nada; hay que volver a pedirlo y reintentar con el ETag nuevo."
        ),
        "content": {
            "application/problem+json": {
                "schema": {"$ref": "#/components/schemas/ProblemDetails"}
            }
        },
    }
}


# ----------------------------------------------------------------------
# Modulos
# ----------------------------------------------------------------------
@router.get(
    "/modules",
    response_model=list[ModuleResponse],
    summary="Listar modulos",
    description=(
        "Los modulos registrados en la plataforma, con su cola y su cantidad de "
        "suscripciones. Este directorio es visible para cualquier modulo "
        "autenticado (sin exponer secrets) para facilitar el descubrimiento "
        "de integraciones."
    ),
)
async def list_modules(caller: CallerDep, registry: RegistryDep) -> list[ModuleResponse]:
    return [ModuleResponse.of(m) for m in await registry.list_modules()]


@router.post(
    "/modules",
    response_model=SecretResponse,
    status_code=status.HTTP_201_CREATED,
    responses=problem_responses(403, 409),
    summary="Dar de alta un modulo",
    description=(
        "Solo el administrador. Devuelve el **secret de maquina** en claro una "
        "sola vez: es el que usa el backend del equipo para publicar eventos.\n\n"
        "Para que las personas del equipo puedan entrar al dashboard hace falta "
        "crearles una cuenta con `POST /api/v1/users`."
    ),
)
async def create_module(
    payload: ModuleCreate, admin: AdminDep, registry: RegistryDep, auth: AuthDep
) -> SecretResponse:
    module = await registry.register_module(
        name=payload.name,
        display_name=payload.display_name,
        team=payload.team,
        description=payload.description,
        contact_email=payload.contact_email,
    )
    secret = auth.rotate_module_secret(module)
    return SecretResponse(module=module.name, secret=secret)


@router.patch(
    "/modules/{module_name}",
    response_model=ModuleResponse,
    responses=problem_responses(403, 404),
    summary="Editar un modulo",
    description=(
        "Solo el administrador. Dar de baja un modulo (`active: false`) deja de "
        "entregarle eventos nuevos sin borrar sus suscripciones y bloquea en el "
        "acto nuevas emisiones en `/auth/login` y `/auth/module-token`. Los JWT "
        "ya emitidos son stateless y mantienen validez residual hasta vencer "
        "su `exp`."
    ),
)
async def update_module(
    module_name: str, payload: ModuleUpdate, admin: AdminDep, registry: RegistryDep
) -> ModuleResponse:
    module = await registry.update_module(
        module_name,
        display_name=payload.display_name,
        team=payload.team,
        description=payload.description,
        contact_email=payload.contact_email,
        active=payload.active,
    )
    return ModuleResponse.of(module)


@router.post(
    "/modules/{module_name}/rotate-secret",
    response_model=SecretResponse,
    responses=problem_responses(403, 404),
    summary="Rotar el secret de maquina de un modulo",
    description=(
        "Solo el administrador. El secret anterior deja de emitir tokens nuevos "
        "en `/auth/module-token` en el acto, asi que el equipo tiene que "
        "actualizar la config de su backend. Los JWT que se hubieran emitido "
        "antes de rotar son stateless y siguen siendo validos hasta agotar su "
        "ventana (`expiresIn`).\n\n"
        "**No afecta el acceso de las personas al dashboard**: para eso estan sus "
        "cuentas."
    ),
)
async def rotate_secret(
    module_name: str, admin: AdminDep, registry: RegistryDep, auth: AuthDep
) -> SecretResponse:
    module = await registry.get_module_by_name(module_name)
    secret = auth.rotate_module_secret(module)
    return SecretResponse(module=module.name, secret=secret)


# ----------------------------------------------------------------------
# Tipos de evento
# ----------------------------------------------------------------------
@router.get(
    "/event-types",
    response_model=PageResponse[EventTypeResponse],
    summary="Listar tipos de evento",
    description=(
        "Catalogo compartido de todos los tipos de evento que circulan por el "
        "hub, visible para cualquier modulo autenticado. Los marcados `discovered` "
        "aparecieron solos al ser publicados sin que nadie los declarara."
    ),
)
async def list_event_types(
    caller: CallerDep,
    registry: RegistryDep,
    query: str | None = Query(default=None),
    owner_module: str | None = Query(default=None, alias="ownerModule"),
    discovered: bool | None = Query(
        default=None, description="true = solo los que se auto-registraron"
    ),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
) -> PageResponse[EventTypeResponse]:
    result = await registry.search_event_types(
        query=query, owner_module=owner_module, discovered=discovered, page=page, size=size
    )
    return PageResponse.build(result, EventTypeResponse.of)


@router.get(
    "/event-types/map",
    response_model=list[EventTypeMapEntry],
    summary="El mapa de integracion",
    description=(
        "Por cada tipo de evento: quien lo declara como publicado, quien esta "
        "suscripto y cuantos llegaron. Es la vista que muestra los agujeros de la "
        "integracion: publicado por alguien y consumido por nadie, o al reves."
    ),
)
async def event_type_map(caller: CallerDep, stats: StatsDep) -> list[EventTypeMapEntry]:
    return [EventTypeMapEntry(**row) for row in await stats.event_type_map()]


@router.get(
    "/event-types/{name}",
    response_model=EventTypeResponse,
    responses={
        200: {"headers": ETAG_HEADER_DOC},
        **problem_responses(404),
    },
    summary="Ver un tipo de evento",
    description=(
        "Devuelve el encabezado `ETag` con la version editable del tipo. Para cambiar "
        "el schema sin pisar a otro, mandalo en `If-Match` del PUT."
    ),
)
async def get_event_type(
    name: str, response: Response, caller: CallerDep, registry: RegistryDep
) -> EventTypeResponse:
    event_type = await registry.get_event_type(name)
    response.headers["ETag"] = event_type_etag(event_type)
    return EventTypeResponse.of(event_type)


@router.post(
    "/event-types",
    response_model=EventTypeResponse,
    status_code=status.HTTP_201_CREATED,
    responses=problem_responses(403),
    summary="Declarar un tipo de evento",
    description=(
        "Registra un tipo con su descripcion y, opcionalmente, su JSON Schema.\n\n"
        "**Operacion idempotente:** si el modulo dueño vuelve a declarar un tipo "
        "que ya existe, actualiza su definicion y responde `201` conservando el "
        "mismo `id`.\n\n"
        "**El schema es opcional.** Sin schema el evento pasa sin que le miren el "
        "`data` (pasamanos puro). Con schema se valida la estructura del payload y "
        "lo que no cumple va a la DLQ con el detalle del campo.\n\n"
        "Si el tipo ya existia porque se auto-registro al aparecer por el hub, se "
        "le completan los datos y se le quita la marca `discovered`.\n\n"
        "**El tipo tiene dueño.** Un modulo declara a su propio nombre: mandar "
        "`ownerModule` de otro equipo, o redeclarar un tipo ajeno, responde 403. "
        "Pasarle un tipo a otro equipo lo hace el administrador."
    ),
)
async def declare_event_type(
    payload: EventTypeCreate, caller: CallerDep, registry: RegistryDep
) -> EventTypeResponse:
    event_type = await registry.declare_event_type(
        name=payload.name,
        owner_module=payload.owner_module or caller.module,
        description=payload.description,
        json_schema=payload.json_schema,
        actor_module=caller.module,
        actor_is_admin=caller.is_admin,
    )
    return EventTypeResponse.of(event_type)


@router.put(
    "/event-types/{name}/schema",
    response_model=EventTypeResponse,
    summary="Activar o quitar la validacion de estructura",
    description=(
        "Define el JSON Schema con el que se valida el `data` de este tipo. "
        "Mandar `null` desactiva la validacion y el evento vuelve a pasar sin mirar.\n\n"
        "**Solo el dueño del tipo** (o el administrador): el schema decide que se "
        "acepta y que se va a la DLQ para todos los que publican ese evento.\n\n"
        "**Concurrencia:** mandar `If-Match` con el `ETag` del GET. Si otro cambio el "
        "tipo en el medio, responde 412 y no aplica nada. La respuesta trae el `ETag` nuevo.\n\n"
        "**Sin `If-Match` no hay proteccion contra actualizaciones concurrentes:** el "
        "cambio se aplica igual, por compatibilidad con los clientes actuales, y gana la "
        "ultima escritura."
    ),
    responses={
        200: {"headers": ETAG_HEADER_DOC},
        **problem_responses(403, 404),
        **PRECONDITION_FAILED_DOC,
    },
)
async def set_schema(
    name: str,
    payload: SchemaUpdate,
    response: Response,
    caller: CallerDep,
    registry: RegistryDep,
    if_match: str | None = Header(
        default=None,
        alias="If-Match",
        description="ETag obtenido en GET /event-types/{name}.",
    ),
) -> EventTypeResponse:
    event_type = await registry.set_schema(
        name,
        json_schema=payload.json_schema,
        actor_module=caller.module,
        actor_is_admin=caller.is_admin,
        if_match=if_match,
    )
    response.headers["ETag"] = event_type_etag(event_type)
    return EventTypeResponse.of(event_type)


# ----------------------------------------------------------------------
# Suscripciones
# ----------------------------------------------------------------------
@router.get(
    "/subscriptions",
    response_model=list[SubscriptionResponse],
    summary="Listar suscripciones",
    description="Un modulo ve las suyas; el administrador ve todas.",
)
async def list_subscriptions(
    caller: CallerDep, registry: RegistryDep
) -> list[SubscriptionResponse]:
    subscriptions = (
        await registry.list_subscriptions()
        if caller.is_admin
        else await registry.list_subscriptions_for(caller.module)
    )
    return [SubscriptionResponse.of(s) for s in subscriptions]


@router.post(
    "/subscriptions",
    response_model=SubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
    responses=problem_responses(403),
    summary="Suscribirse a un tipo de evento",
    description=(
        "El modulo autenticado empieza a recibir ese tipo en su cola. La cola y su "
        "binding se declaran en el broker en el acto.\n\n"
        "**Operacion idempotente:** volver a suscribirse al mismo `eventType` "
        "actualiza la suscripcion existente y responde `201` con el mismo `id`.\n\n"
        "Se puede suscribir a un tipo que todavia nadie publico: cuando llegue el "
        "primero, ya tiene destino."
    ),
)
async def subscribe(
    payload: SubscriptionCreate, caller: CallerDep, registry: RegistryDep
) -> SubscriptionResponse:
    subscription = await registry.subscribe(
        module_name=payload.module or caller.module,
        event_type_name=payload.event_type,
        max_attempts=payload.max_attempts,
        actor_module=caller.module,
        actor_is_admin=caller.is_admin,
    )
    return SubscriptionResponse.of(subscription)


@router.post(
    "/subscriptions/{subscription_id}/toggle",
    response_model=SubscriptionResponse,
    responses=problem_responses(403, 404),
    summary="Pausar o reactivar una suscripcion",
    description=(
        "Pausar deja de entregar sin borrar la suscripcion. Util cuando un modulo "
        "se va a desplegar y no quiere acumular fallos."
    ),
)
async def toggle_subscription(
    subscription_id: uuid.UUID,
    caller: CallerDep,
    registry: RegistryDep,
    active: bool = Query(description="true reactiva, false pausa"),
) -> SubscriptionResponse:
    subscription = await registry.set_subscription_active(
        subscription_id,
        active=active,
        actor_module=caller.module,
        actor_is_admin=caller.is_admin,
    )
    return SubscriptionResponse.of(subscription)


@router.delete(
    "/subscriptions/{subscription_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=problem_responses(403, 404),
    summary="Cancelar una suscripcion",
)
async def unsubscribe(subscription_id: uuid.UUID, caller: CallerDep, registry: RegistryDep) -> None:
    await registry.unsubscribe(
        subscription_id, actor_module=caller.module, actor_is_admin=caller.is_admin
    )


# ----------------------------------------------------------------------
# Publicaciones
# ----------------------------------------------------------------------
@router.get(
    "/publications",
    response_model=list[PublicationResponse],
    summary="Listar publicaciones declaradas",
    description=(
        "Catalogo compartido de las declaraciones de publicacion de todos los "
        "modulos, visible para cualquier modulo autenticado."
    ),
)
async def list_publications(caller: CallerDep, registry: RegistryDep) -> list[PublicationResponse]:
    return [PublicationResponse.of(p) for p in await registry.list_publications()]


@router.post(
    "/publications",
    response_model=PublicationResponse,
    status_code=status.HTTP_201_CREATED,
    responses=problem_responses(403),
    summary="Declarar que publicas un tipo de evento",
    description=(
        "Es **documentacion, no un permiso**: publicar un evento no declarado "
        "funciona igual. Existe para que el mapa de integracion pueda mostrar quien "
        "manda que, y para detectar los eventos que nadie consume.\n\n"
        "**Operacion idempotente:** redeclarar la misma publicacion responde `201` "
        "conservando el mismo `id`."
    ),
)
async def declare_publication(
    payload: PublicationCreate, caller: CallerDep, registry: RegistryDep
) -> PublicationResponse:
    publication = await registry.declare_publication(
        module_name=payload.module or caller.module,
        event_type_name=payload.event_type,
        actor_module=caller.module,
        actor_is_admin=caller.is_admin,
    )
    return PublicationResponse.of(publication)


@router.delete(
    "/publications/{publication_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=problem_responses(403, 404),
    summary="Quitar una publicacion declarada",
)
async def remove_publication(
    publication_id: uuid.UUID, caller: CallerDep, registry: RegistryDep
) -> None:
    await registry.remove_publication(
        publication_id, actor_module=caller.module, actor_is_admin=caller.is_admin
    )


# ----------------------------------------------------------------------
# Topologia
# ----------------------------------------------------------------------
@router.get(
    "/topology",
    response_model=TopologyResponse,
    summary="Ver la topologia de mensajeria",
    description=(
        "Los exchanges, colas y bindings que corresponden al estado actual del "
        "registry. Se deriva de las suscripciones: no hay nada escrito a mano."
    ),
)
async def get_topology(caller: CallerDep, registry: RegistryDep) -> TopologyResponse:
    return TopologyResponse.of(await registry.planned_topology())


@router.post(
    "/topology/apply",
    response_model=MessageResponse,
    responses=problem_responses(403),
    summary="Aplicar la topologia en el broker",
    description=(
        "Solo el administrador. Es idempotente. Sirve cuando el broker estuvo caido "
        "mientras se creaban suscripciones."
    ),
)
async def apply_topology(admin: AdminDep, registry: RegistryDep) -> MessageResponse:
    topology = await registry.apply_topology()
    return MessageResponse(
        message=(
            f"Topologia aplicada: {len(topology.exchanges)} exchange(s), "
            f"{len(topology.queues)} cola(s), {len(topology.bindings)} binding(s)."
        )
    )
