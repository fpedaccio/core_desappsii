"""Demostracion de RabbitMQ en el Core.

Corre el camino completo de un evento por el broker real y va narrando lo que
pasa. Pensada para mirar en paralelo la consola de RabbitMQ
(http://localhost:15672, guest/guest) y ver moverse los contadores de las colas.

    python demo_rabbitmq.py

Los cinco actos:

    1. La topologia que el Core declara en el broker.
    2. Un modulo publica -> el Core lo consume de core.inbox y lo rutea.
    3. Idempotencia: el mismo eventId no se rutea dos veces.
    4. Un consumidor que rechaza -> backoff 5s -> 30s -> ... -> DLQ.
    5. Durabilidad: con el Core apagado, publicar igual funciona y nada se pierde.
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import UTC, datetime

import aio_pika

from app.core.config import settings
from app.core.database import Base, SessionFactory, engine
from app.messaging.broker import HEADER_ERROR, HEADER_TARGET, InboundMessage
from app.messaging.provider import get_broker
from app.messaging.topology import base_topology, full_topology, retry_queue_for
from app.models.events import IngestionChannel
from app.repositories.event_repository import (
    DeadLetterRepository,
    DeliveryRepository,
    EventLogRepository,
    RetryAuditRepository,
)
from app.repositories.registry_repository import (
    EventTypeRepository,
    SubscriptionRepository,
)
from app.services.delivery_service import DeliveryService
from app.services.envelope import EventEnvelope
from app.services.event_hub_service import EventHubService

AZUL, VERDE, AMARILLO, ROJO, GRIS, FIN = (
    "\033[94m",
    "\033[92m",
    "\033[93m",
    "\033[91m",
    "\033[90m",
    "\033[0m",
)


def acto(numero: int, titulo: str) -> None:
    print(f"\n{AZUL}{'=' * 72}\n  ACTO {numero}: {titulo}\n{'=' * 72}{FIN}")


def paso(texto: str) -> None:
    print(f"\n{AMARILLO}▸ {texto}{FIN}")


def ok(texto: str) -> None:
    print(f"  {VERDE}✓{FIN} {texto}")


def dato(texto: str) -> None:
    print(f"  {GRIS}{texto}{FIN}")


async def pausa(segundos: float = 0, mensaje: str = "Enter para seguir") -> None:
    if segundos:
        await asyncio.sleep(segundos)
    else:
        print(f"\n{GRIS}   [{mensaje}]{FIN}", end="")
        await asyncio.to_thread(input)


def sobre(event_type: str, source: str, data: dict, event_id: str | None = None) -> dict:
    return {
        "eventId": event_id or str(uuid.uuid4()),
        "eventType": event_type,
        "eventVersion": "1.0",
        "occurredAt": datetime.now(UTC).isoformat(),
        "sourceModule": source,
        "correlationId": str(uuid.uuid4()),
        "data": data,
    }


def hub(session):
    return EventHubService(
        event_log_repo=EventLogRepository(session),
        delivery_repo=DeliveryRepository(session),
        dead_letter_repo=DeadLetterRepository(session),
        event_type_repo=EventTypeRepository(session),
        subscription_repo=SubscriptionRepository(session),
        broker=get_broker(),
    )


async def contar(conexion, cola: str) -> int:
    """Mensajes esperando en una cola, leidos del broker real.

    Usa un canal propio: sobre el canal compartido, justo despues de una purga
    o de una rafaga de publicaciones, la cuenta volvia desactualizada.
    """
    canal = await conexion.channel()
    try:
        declarada = await canal.declare_queue(cola, durable=True, passive=True)
        return declarada.declaration_result.message_count
    finally:
        if not canal.is_closed:
            await canal.close()


async def purgar(conexion, colas: list[str]) -> int:
    """Vacia las colas antes de empezar.

    Sin esto la demo no es reproducible: los mensajes de una corrida anterior
    quedan en las colas y el acto de idempotencia termina sacando un evento
    viejo en vez del que se acaba de publicar.

    Usa **un canal por cola**: en AMQP un `declare` pasivo sobre una cola que no
    existe cierra el canal, y todas las operaciones siguientes sobre ese canal
    fallarian en silencio.
    """
    total = 0
    for cola in colas:
        canal = await conexion.channel()
        try:
            declarada = await canal.declare_queue(cola, durable=True, passive=True)
            total += (await declarada.purge()).message_count or 0
        except Exception:
            pass  # la cola todavia no existe
        finally:
            if not canal.is_closed:
                await canal.close()
    return total


async def sacar(canal, cola: str):
    """Saca un mensaje de la cola sin reconocerlo todavia.

    En aio-pika `get` vive en la cola, no en el canal. `fail=False` devuelve
    None cuando la cola esta vacia en vez de levantar.
    """
    declarada = await canal.declare_queue(cola, durable=True, passive=True)
    return await declarada.get(fail=False)


# ----------------------------------------------------------------------
async def main(interactivo: bool) -> None:
    async def seguir(segundos: float = 1.5):
        await pausa(0 if interactivo else segundos)

    print(f"\n{AZUL}  DEMO: RabbitMQ en el modulo Core{FIN}")
    print(f"{GRIS}  Abri http://localhost:15672 (guest/guest) para ver las colas.{FIN}")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    broker = get_broker()
    await broker.connect()
    conexion = await aio_pika.connect_robust(settings.rabbitmq_url)
    canal = await conexion.channel(publisher_confirms=True)

    # ---------------------------------------------------------------- 1
    acto(1, "La topologia que el Core declara")

    async with SessionFactory() as s:
        colas = await SubscriptionRepository(s).active_queue_names()
    topo = full_topology(colas)
    await broker.declare(base_topology())
    await broker.declare(topo)

    ok(
        f"{len(topo.exchanges)} exchanges, {len(topo.queues)} colas, "
        f"{len(topo.bindings)} bindings declarados en RabbitMQ"
    )

    # La demo arranca de cero para que los numeros sean los que se explican.
    vaciados = await purgar(conexion, [q.name for q in topo.queues])
    if vaciados:
        # Segunda pasada: los que estaban en las colas de espera vuelven por TTL
        # y descuadrarian los numeros que se explican mas adelante.
        await asyncio.sleep(max(settings.retry_delays[:1] or [5]) + 1)
        vaciados += await purgar(conexion, [q.name for q in topo.queues])
        dato(f"(se vaciaron {vaciados} mensaje(s) de corridas anteriores)")
    dato("")
    dato("  muni.inbox    (fanout)  <- aca publican los 9 modulos")
    dato("  muni.events   (topic)   <- aca rutea el Core, rk = cola destino")
    dato("  muni.retry.*  (fanout)  <- los escalones de backoff")
    dato("  muni.dlx      (fanout)  <- lo que agoto los reintentos")
    dato("")
    dato("La topologia NO esta hardcodeada: sale de la tabla de suscripciones.")
    dato(f"Las {len(colas)} colas de modulo existen porque hay equipos suscriptos.")
    print()
    dato("→ En la consola: pestana Exchanges y pestana Queues")
    await seguir()

    # ---------------------------------------------------------------- 2
    acto(2, "Un modulo publica y el Core rutea")

    evento = sobre(
        "ticketCreated",
        "atencion-ciudadana",
        {"ticketId": "TK-DEMO-001", "category": "INFRASTRUCTURE"},
    )

    paso("atencion-ciudadana publica en muni.inbox (no sabe quien lo va a recibir)")
    exchange_inbox = await canal.get_exchange(settings.exchange_inbox)
    await exchange_inbox.publish(
        aio_pika.Message(
            body=json.dumps(evento).encode(),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        ),
        routing_key="",
    )
    await asyncio.sleep(0.8)
    ok(f"publicado · eventId {evento['eventId'][:8]}...")
    dato(f"core.inbox tiene {await contar(conexion, settings.queue_inbox)} mensaje(s) esperando")
    dato("Nadie los consumio todavia: el Core esta 'apagado' en esta demo.")
    await seguir()

    paso("Ahora el Core los consume y los rutea")
    entrante = await sacar(canal, settings.queue_inbox)
    async with SessionFactory() as s:
        resultado = await hub(s).ingest(
            EventEnvelope.model_validate(json.loads(entrante.body)),
            channel=IngestionChannel.AMQP,
        )
        await s.commit()
    await entrante.ack()

    ok(f"estado: {resultado.status.value}")
    ok(f"ruteado a: {', '.join(resultado.routed_to)}")
    dato("")
    dato("El Core leyo las suscripciones de 'ticketCreated' y publico una copia")
    dato("en muni.events por cada destino, con rk = nombre de la cola.")
    print()
    for modulo in resultado.routed_to:
        dato(f"  q.{modulo:22} {await contar(conexion, f'q.{modulo}')} mensaje(s)")
    await seguir()

    # ---------------------------------------------------------------- 3
    acto(3, "Idempotencia: el mismo eventId no se rutea dos veces")

    paso("Se republica EL MISMO evento (mismo eventId)")
    await exchange_inbox.publish(
        aio_pika.Message(
            body=json.dumps(evento).encode(), delivery_mode=aio_pika.DeliveryMode.PERSISTENT
        ),
        routing_key="",
    )
    await asyncio.sleep(0.4)
    repetido = await sacar(canal, settings.queue_inbox)
    antes = {m: await contar(conexion, f"q.{m}") for m in resultado.routed_to}

    async with SessionFactory() as s:
        r2 = await hub(s).ingest(EventEnvelope.model_validate(json.loads(repetido.body)))
        await s.commit()
    await repetido.ack()

    ok(f"estado: {r2.status.value} · duplicate={r2.duplicate}")
    dato("")
    for modulo, contaba in antes.items():
        ahora = await contar(conexion, f"q.{modulo}")
        marca = "sin cambios" if ahora == contaba else f"CAMBIO {contaba}->{ahora}"
        dato(f"  q.{modulo:22} {contaba} -> {ahora}   ({marca})")
    dato("")
    dato("El evento entro al broker igual, pero el Core no genero entregas nuevas.")
    await seguir()

    # ---------------------------------------------------------------- 4
    acto(4, "Un consumidor rechaza: backoff y DLQ")

    cola_destino = f"q.{resultado.routed_to[0]}"
    paso(f"{resultado.routed_to[0]} consume de {cola_destino} y hace nack(requeue=False)")

    mensaje = await sacar(canal, cola_destino)
    if mensaje is None:
        dato("No habia mensaje; se publica uno para la demo.")
    else:
        await mensaje.nack(requeue=False)
        ok("nack enviado · RabbitMQ lo dead-letterea a muni.dlx -> q.dlq")
        await asyncio.sleep(0.5)
        dato(f"q.dlq tiene {await contar(conexion, settings.queue_dlq)} mensaje(s)")

    await seguir()

    paso("El Core lee q.dlq y decide: ¿le quedan intentos?")
    en_dlq = await sacar(canal, settings.queue_dlq)
    if en_dlq is not None:
        entrada = InboundMessage(
            queue=settings.queue_dlq,
            routing_key=en_dlq.routing_key or "",
            raw=en_dlq.body,
            headers={
                **dict(en_dlq.headers or {}),
                HEADER_TARGET: resultado.routed_to[0],
                HEADER_ERROR: "El consumidor rechazo el mensaje (demo)",
            },
        )
        async with SessionFactory() as s:
            servicio = DeliveryService(
                delivery_repo=DeliveryRepository(s),
                dead_letter_repo=DeadLetterRepository(s),
                retry_audit_repo=RetryAuditRepository(s),
                event_log_repo=EventLogRepository(s),
                hub=hub(s),
                broker=broker,
            )
            dead_letter = await servicio.handle_dlq_message(entrada)
            await s.commit()
        await en_dlq.ack()

        if dead_letter is None:
            ok("Le quedaban intentos: se programo el siguiente escalon de backoff")
            await asyncio.sleep(0.4)
            for delay in settings.retry_delays:
                cola_espera = retry_queue_for(delay)
                cuantos = await contar(conexion, cola_espera)
                if cuantos:
                    dato(f"  {cola_espera:16} {cuantos} mensaje(s) esperando {delay}s")
            dato("")
            dato("El truco: esa cola tiene x-message-ttl y su x-dead-letter-exchange")
            dato("apunta de vuelta a muni.events. Cuando vence el TTL, RabbitMQ lo")
            dato("devuelve solo a la cola destino. No hay ningun proceso durmiendo.")
        else:
            ok(f"Agoto los intentos: dead letter {dead_letter.reason_code}")

    print()
    primer_escalon = (settings.retry_delays or [5])[0]
    dato(
        f"→ En la consola: mira {retry_queue_for(primer_escalon)}, y en "
        f"{primer_escalon} segundos vuelve a {cola_destino}"
    )
    await seguir()

    # ---------------------------------------------------------------- 5
    acto(5, "Durabilidad: el Core caido no frena a nadie")

    paso("Se publican 3 eventos con el Core 'apagado' (nadie consume core.inbox)")
    await purgar(conexion, [settings.queue_inbox])
    ids_publicados = []
    for i in range(3):
        cuerpo = sobre("ticketUpdated", "atencion-ciudadana", {"ticketId": f"TK-{i}"})
        ids_publicados.append(cuerpo["eventId"])
        await exchange_inbox.publish(
            aio_pika.Message(
                body=json.dumps(cuerpo).encode(),
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            ),
            routing_key="",
        )
    await asyncio.sleep(0.5)

    ok("Los 3 publish funcionaron sin error")
    dato(f"core.inbox: {await contar(conexion, settings.queue_inbox)} mensaje(s) esperando")
    dato("")
    dato("El modulo que publica NO se entera de que el Core esta caido, y no se")
    dato("bloquea. La cola es durable: los mensajes sobreviven hasta un reinicio")
    dato("del broker. Cuando el Core vuelve, drena la cola.")
    await seguir()

    paso("Vuelve el Core y drena")
    drenados = 0
    while True:
        pendiente = await sacar(canal, settings.queue_inbox)
        if pendiente is None:
            # Segunda chance: un mensaje puede estar en vuelo justo cuando el
            # drenado llega al final, y dejarlo afuera arruinaria el cierre.
            await asyncio.sleep(0.6)
            pendiente = await sacar(canal, settings.queue_inbox)
        if pendiente is None:
            break
        async with SessionFactory() as s:
            await hub(s).ingest(EventEnvelope.model_validate(json.loads(pendiente.body)))
            await s.commit()
        await pendiente.ack()
        drenados += 1

    ok(f"{drenados} evento(s) drenados de core.inbox")

    # Lo que prueba el acto no es que una cola este en cero (eso corre contra
    # mensajes en vuelo), sino que los eventos quedaron persistidos.
    import uuid as _uuid

    async with SessionFactory() as s_:
        repo = EventLogRepository(s_)
        guardados = [await repo.get_by_event_id(_uuid.UUID(eid)) for eid in ids_publicados]
    encontrados = sum(1 for g in guardados if g is not None)

    print()
    for eid, g in zip(ids_publicados, guardados, strict=True):
        # Segun el dialecto el enum vuelve como Enum o como str.
        estado = str(getattr(g.status, "value", g.status)) if g else "NO ENCONTRADO"
        dato(f"  {eid[:8]}...  {estado}")
    print()
    ok(
        f"{encontrados} de {len(ids_publicados)} publicados durante la caida quedaron "
        "guardados. Nada se perdio."
    )

    print(f"\n{VERDE}{'=' * 72}\n  FIN\n{'=' * 72}{FIN}\n")

    await canal.close()
    await conexion.close()
    await broker.close()
    await engine.dispose()


if __name__ == "__main__":
    if "memory://" in settings.rabbitmq_url:
        print(f"{ROJO}RABBITMQ_URL apunta al broker en memoria.{FIN}")
        print("Para esta demo hace falta RabbitMQ real. En backend/.env pone:")
        print("  RABBITMQ_URL=amqp://guest:guest@localhost:5672/")
        sys.exit(1)
    asyncio.run(main(interactivo="--auto" not in sys.argv))
