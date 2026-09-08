"""Registry: modulos, tipos de evento, suscripciones y publicaciones.

Es donde cada equipo se autoadministra: se suscribe a lo que quiere recibir y
declara lo que publica. Un modulo solo puede tocar lo suyo; el admin puede
hacerlo por cualquiera.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import AdminDep, AuthDep, CallerDep, RegistryDep, StatsDep
from app.api.v1.schemas.common import MessageResponse, PageResponse
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

router = APIRouter(tags=["Registry"])


# ----------------------------------------------------------------------
# Modulos
# ----------------------------------------------------------------------
@router.get(
    "/modules",
    response_model=list[ModuleResponse],
    summary="Listar modulos",
    description="Los 9 modulos de la plataforma, con su cola y su cantidad de suscripciones.",
)
async def list_modules(caller: CallerDep, registry: RegistryDep) -> list[ModuleResponse]:
    return [ModuleResponse.of(m) for m in await registry.list_modules()]


@router.post(
    "/modules",
    response_model=SecretResponse,
    status_code=status.HTTP_201_CREATED,
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
    summary="Editar un modulo",
    description=(
        "Solo el administrador. Dar de baja un modulo deja de entregarle eventos "
        "sin borrar sus suscripciones: quedan declaradas para cuando vuelva."
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
    summary="Rotar el secret de maquina de un modulo",
    description=(
        "Solo el administrador. El secret anterior deja de servir en el acto, asi "
        "que el equipo tiene que actualizar la config de su backend.\n\n"
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
        "Todos los tipos que circulan por el hub. Los marcados `discovered` "
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
    summary="Ver un tipo de evento",
)
async def get_event_type(name: str, caller: CallerDep, registry: RegistryDep) -> EventTypeResponse:
    return EventTypeResponse.of(await registry.get_event_type(name))


@router.post(
    "/event-types",
    response_model=EventTypeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Declarar un tipo de evento",
    description=(
        "Registra un tipo con su descripcion y, opcionalmente, su JSON Schema.\n\n"
        "**El schema es opcional.** Sin schema el evento pasa sin que le miren el "
        "`data` (pasamanos puro). Con schema se valida la estructura del payload y "
        "lo que no cumple va a la DLQ con el detalle del campo.\n\n"
        "Si el tipo ya existia porque se auto-registro al aparecer por el hub, se "
        "le completan los datos y se le quita la marca `discovered`."
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
    )
    return EventTypeResponse.of(event_type)


@router.put(
    "/event-types/{name}/schema",
    response_model=EventTypeResponse,
    summary="Activar o quitar la validacion de estructura",
    description=(
        "Define el JSON Schema con el que se valida el `data` de este tipo. "
        "Mandar `null` desactiva la validacion y el evento vuelve a pasar sin mirar."
    ),
)
async def set_schema(
    name: str, payload: SchemaUpdate, caller: CallerDep, registry: RegistryDep
) -> EventTypeResponse:
    return EventTypeResponse.of(await registry.set_schema(name, json_schema=payload.json_schema))


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
    summary="Suscribirse a un tipo de evento",
    description=(
        "El modulo autenticado empieza a recibir ese tipo en su cola. La cola y su "
        "binding se declaran en el broker en el acto.\n\n"
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
)
async def list_publications(caller: CallerDep, registry: RegistryDep) -> list[PublicationResponse]:
    return [PublicationResponse.of(p) for p in await registry.list_publications()]


@router.post(
    "/publications",
    response_model=PublicationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Declarar que publicas un tipo de evento",
    description=(
        "Es **documentacion, no un permiso**: publicar un evento no declarado "
        "funciona igual. Existe para que el mapa de integracion pueda mostrar quien "
        "manda que, y para detectar los eventos que nadie consume."
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
