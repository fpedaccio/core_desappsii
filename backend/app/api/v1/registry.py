"""Endpoints del registry de integracion y de la topologia de mensajeria."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status

from app.api.deps import RegistryDep, require_permissions
from app.api.v1.schemas.integration import (
    ModuleCreate,
    ModuleResponse,
    ModuleUpdate,
    ProducerCreate,
    ProducerResponse,
    SubscriptionCreate,
    SubscriptionResponse,
    SubscriptionUpdate,
    TopologyResponse,
)
from app.core import permissions as perms

router = APIRouter(prefix="/registry", tags=["Registry de integracion"])


# ----------------------------------------------------------------------
# Modulos
# ----------------------------------------------------------------------
@router.get(
    "/modules",
    response_model=list[ModuleResponse],
    dependencies=[Depends(require_permissions(perms.REGISTRY_READ))],
    summary="Listar modulos registrados",
)
async def list_modules(service: RegistryDep) -> list[ModuleResponse]:
    return [ModuleResponse.of(module) for module in await service.list_modules()]


@router.post(
    "/modules",
    response_model=ModuleResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(perms.REGISTRY_WRITE))],
    summary="Registrar un modulo",
    description=(
        "Da de alta uno de los 9 modulos de la plataforma. El `name` es el "
        "identificador tecnico que despues viaja como `sourceModule` en sus eventos, "
        "y determina su cola destino (`q.<name>` por defecto)."
    ),
)
async def register_module(payload: ModuleCreate, service: RegistryDep) -> ModuleResponse:
    module = await service.register_module(
        name=payload.name,
        display_name=payload.display_name,
        description=payload.description,
        team=payload.team,
        base_url=payload.base_url,
        health_url=payload.health_url,
        contact_email=payload.contact_email,
        queue_name=payload.queue_name,
    )
    return ModuleResponse.of(module)


@router.patch(
    "/modules/{module_id}",
    response_model=ModuleResponse,
    dependencies=[Depends(require_permissions(perms.REGISTRY_WRITE))],
    summary="Editar un modulo",
    description=(
        "Desactivar un modulo hace que el hub deje de entregarle eventos, sin borrar "
        "sus suscripciones ni su cola: cuando vuelva, se reactiva y sigue."
    ),
)
async def update_module(
    module_id: uuid.UUID, payload: ModuleUpdate, service: RegistryDep
) -> ModuleResponse:
    module = await service.update_module(
        module_id,
        display_name=payload.display_name,
        description=payload.description,
        team=payload.team,
        base_url=payload.base_url,
        health_url=payload.health_url,
        contact_email=payload.contact_email,
        active=payload.active,
    )
    return ModuleResponse.of(module)


# ----------------------------------------------------------------------
# Productores
# ----------------------------------------------------------------------
@router.get(
    "/producers",
    response_model=list[ProducerResponse],
    dependencies=[Depends(require_permissions(perms.REGISTRY_READ))],
    summary="Listar productores declarados",
)
async def list_producers(service: RegistryDep) -> list[ProducerResponse]:
    return [ProducerResponse.of(producer) for producer in await service.list_producers()]


@router.post(
    "/producers",
    response_model=ProducerResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(perms.REGISTRY_WRITE))],
    summary="Declarar que un modulo publica un tipo de evento",
)
async def declare_producer(payload: ProducerCreate, service: RegistryDep) -> ProducerResponse:
    producer = await service.declare_producer(
        module_name=payload.module_name, event_type_name=payload.event_type
    )
    return ProducerResponse.of(producer)


@router.delete(
    "/producers/{producer_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permissions(perms.REGISTRY_WRITE))],
    summary="Quitar una declaracion de productor",
)
async def remove_producer(producer_id: uuid.UUID, service: RegistryDep) -> None:
    await service.remove_producer(producer_id)


# ----------------------------------------------------------------------
# Suscripciones
# ----------------------------------------------------------------------
@router.get(
    "/subscriptions",
    response_model=list[SubscriptionResponse],
    dependencies=[Depends(require_permissions(perms.REGISTRY_READ))],
    summary="Listar suscripciones",
    description="Es la tabla que gobierna el ruteo del hub.",
)
async def list_subscriptions(service: RegistryDep) -> list[SubscriptionResponse]:
    return [SubscriptionResponse.of(sub) for sub in await service.list_subscriptions()]


@router.post(
    "/subscriptions",
    response_model=SubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(perms.REGISTRY_WRITE))],
    summary="Suscribir un modulo a un tipo de evento",
    description=(
        "Al crear la suscripcion el Core declara la cola y su binding en el acto, "
        "para que exista antes de que llegue el primer evento del tipo. Si el broker "
        "no responde, la suscripcion queda igual registrada y la topologia se aplica "
        "en el proximo arranque o desde `POST /registry/topology/apply`."
    ),
)
async def subscribe(payload: SubscriptionCreate, service: RegistryDep) -> SubscriptionResponse:
    subscription = await service.subscribe(
        module_name=payload.module_name,
        event_type_name=payload.event_type,
        queue_name=payload.queue_name,
        max_attempts=payload.max_attempts,
    )
    return SubscriptionResponse.of(subscription)


@router.patch(
    "/subscriptions/{subscription_id}",
    response_model=SubscriptionResponse,
    dependencies=[Depends(require_permissions(perms.REGISTRY_WRITE))],
    summary="Editar una suscripcion",
)
async def update_subscription(
    subscription_id: uuid.UUID, payload: SubscriptionUpdate, service: RegistryDep
) -> SubscriptionResponse:
    subscription = await service.update_subscription(
        subscription_id,
        active=payload.active,
        max_attempts=payload.max_attempts,
        queue_name=payload.queue_name,
    )
    return SubscriptionResponse.of(subscription)


@router.delete(
    "/subscriptions/{subscription_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permissions(perms.REGISTRY_WRITE))],
    summary="Eliminar una suscripcion",
)
async def unsubscribe(subscription_id: uuid.UUID, service: RegistryDep) -> None:
    await service.unsubscribe(subscription_id)


# ----------------------------------------------------------------------
# Topologia
# ----------------------------------------------------------------------
@router.get(
    "/topology",
    response_model=TopologyResponse,
    dependencies=[Depends(require_permissions(perms.REGISTRY_READ))],
    summary="Ver la topologia que corresponde al registry",
    description=(
        "Exchanges, colas y bindings derivados de las suscripciones activas, sin "
        "tocar el broker. Incluye las colas de reintento por escalon y la DLQ."
    ),
)
async def get_topology(service: RegistryDep) -> TopologyResponse:
    topology = await service.planned_topology()
    return TopologyResponse.of(topology, applied=False)


@router.post(
    "/topology/apply",
    response_model=TopologyResponse,
    dependencies=[Depends(require_permissions(perms.TOPOLOGY_APPLY))],
    summary="Declarar la topologia en el broker",
    description=(
        "Idempotente: se puede reaplicar cuantas veces sea necesario. Es lo que se "
        "corre cuando el broker vuelve despues de una caida."
    ),
)
async def apply_topology(service: RegistryDep) -> TopologyResponse:
    topology = await service.apply_topology()
    return TopologyResponse.of(topology, applied=True)


@router.post(
    "/core-subscriptions/sync",
    response_model=list[str],
    dependencies=[Depends(require_permissions(perms.REGISTRY_WRITE))],
    summary="Sincronizar las suscripciones propias del Core",
    description=(
        "Suscribe al Core a los eventos de identidad (para provisionar cuentas) y a "
        "los tipos que tengan una regla de notificacion configurada. Devuelve los "
        "tipos que se agregaron en esta corrida."
    ),
)
async def sync_core_subscriptions(service: RegistryDep) -> list[str]:
    return await service.sync_core_subscriptions()
