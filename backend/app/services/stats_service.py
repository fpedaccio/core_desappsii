"""Estadisticas del dashboard.

Dos vistas, con la misma forma de datos:

* **La de un modulo** (`scope = "obras"`): solo su trafico. Lo que publico, lo
  que le entregaron, sus suscripciones y sus fallas.
* **La global** (`scope = None`, solo para el equipo 9): el mapa completo, con
  la matriz de quien manda a quien y las alertas de integracion.

El scope lo aplican los repositorios, no la capa HTTP: asi no hay forma de
pedir datos de otro modulo cambiando un query param.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.core.database import utcnow
from app.messaging.broker import Broker
from app.repositories.event_repository import (
    DeadLetterRepository,
    DeliveryRepository,
    EventLogRepository,
)
from app.repositories.registry_repository import (
    EventTypeRepository,
    ModuleRepository,
    PublicationRepository,
    SubscriptionRepository,
)


class StatsService:
    def __init__(
        self,
        *,
        event_log_repo: EventLogRepository,
        delivery_repo: DeliveryRepository,
        dead_letter_repo: DeadLetterRepository,
        module_repo: ModuleRepository,
        event_type_repo: EventTypeRepository,
        subscription_repo: SubscriptionRepository,
        publication_repo: PublicationRepository,
        broker: Broker,
    ) -> None:
        self.event_log_repo = event_log_repo
        self.delivery_repo = delivery_repo
        self.dead_letter_repo = dead_letter_repo
        self.module_repo = module_repo
        self.event_type_repo = event_type_repo
        self.subscription_repo = subscription_repo
        self.publication_repo = publication_repo
        self.broker = broker

    # ------------------------------------------------------------------
    async def module_dashboard(self, module_name: str, *, window_hours: int = 24) -> dict[str, Any]:
        """El tablero que ve un equipo cuando entra."""
        since = utcnow() - timedelta(hours=window_hours)
        module = await self.module_repo.get_by_name(module_name)
        subscriptions = await self.subscription_repo.list_for_module(module.id) if module else []
        publications = await self.publication_repo.list_for_module(module.id) if module else []

        received_by_status = await self.delivery_repo.count_by_status(target_module=module_name)

        return {
            "module": module_name,
            "windowHours": window_hours,
            "generatedAt": utcnow(),
            "published": {
                "total": await self.event_log_repo.count_published(module_name),
                "inWindow": await self.event_log_repo.count_published(module_name, since=since),
                "topTypes": await self.event_log_repo.top_types(
                    module_scope=module_name, since=since
                ),
            },
            "received": {
                "byStatus": received_by_status,
                "total": sum(received_by_status.values()),
                "delivered": received_by_status.get("DELIVERED", 0),
                "pendingRetry": received_by_status.get("RETRYING", 0),
                "dead": received_by_status.get("DEAD", 0),
            },
            "deadLetters": {
                "open": await self.dead_letter_repo.count_open(module_scope=module_name),
                "byReason": await self.dead_letter_repo.count_by_reason(module_scope=module_name),
            },
            "subscriptions": {
                "total": len(subscriptions),
                "active": sum(1 for s in subscriptions if s.active),
                "eventTypes": sorted(s.event_type.name for s in subscriptions if s.active),
            },
            "publications": {
                "declared": sorted(p.event_type.name for p in publications if p.active),
            },
            "volumeByHour": await self.event_log_repo.hourly_volume(
                module_scope=module_name, since=since
            ),
            "processing": await self.event_log_repo.processing_stats(
                module_scope=module_name, since=since
            ),
        }

    # ------------------------------------------------------------------
    async def global_dashboard(self, *, window_hours: int = 24) -> dict[str, Any]:
        """El tablero del equipo 9: el hub completo."""
        since = utcnow() - timedelta(hours=window_hours)
        last_hour = utcnow() - timedelta(hours=1)

        events_by_status = await self.event_log_repo.count_by_status(since=since)
        events_last_hour = await self.event_log_repo.count_since(last_hour)
        modules = await self.module_repo.list_ordered()

        return {
            "windowHours": window_hours,
            "generatedAt": utcnow(),
            "events": {
                "byStatus": events_by_status,
                "total": sum(events_by_status.values()),
                "lastHour": events_last_hour,
                "perMinuteLastHour": round(events_last_hour / 60, 2),
                "topTypes": await self.event_log_repo.top_types(since=since),
                "bySourceModule": await self.event_log_repo.by_source_module(since=since),
                "processing": await self.event_log_repo.processing_stats(since=since),
            },
            "deliveries": {
                "byStatus": await self.delivery_repo.count_by_status(),
                "byModule": await self.delivery_repo.count_by_module_and_status(),
            },
            "deadLetters": {
                "open": await self.dead_letter_repo.count_open(),
                "byStatus": await self.dead_letter_repo.count_by_status(),
                "byReason": await self.dead_letter_repo.count_by_reason(),
            },
            "modules": [
                {
                    "name": m.name,
                    "displayName": m.display_name,
                    "team": m.team,
                    "active": m.active,
                    "isAdmin": m.is_admin,
                    "subscriptions": sum(1 for s in m.subscriptions if s.active),
                    "lastLoginAt": m.last_login_at,
                    "lastPublishAt": m.last_publish_at,
                }
                for m in modules
            ],
            "volumeByHour": await self.event_log_repo.hourly_volume(since=since),
            "broker": {"connected": await self._broker_healthy()},
            "integrationAlerts": await self.integration_alerts(),
        }

    # ------------------------------------------------------------------
    async def integration_alerts(self) -> list[dict[str, Any]]:
        """Las desalineaciones entre equipos, detectadas de los datos reales.

        Esto es lo que hace util al pasamanos: no valida reglas de negocio, pero
        **si** ve el mapa completo de quien manda que y quien escucha que. Los
        nombres que no coinciden entre equipos aparecen aca solos, en vez de
        descubrirse el dia de la integracion.
        """
        alerts: list[dict[str, Any]] = []
        event_types = await self.event_type_repo.list_ordered()
        subscriber_counts = await self.subscription_repo.counts_by_event_type()

        producers_by_type: dict[str, list[str]] = {}
        for publication in await self.publication_repo.list_all():
            if publication.active:
                name = publication.event_type.name
                producers_by_type.setdefault(name, []).append(publication.module.name)
        producer_counts = {name: len(mods) for name, mods in producers_by_type.items()}

        consumers_by_type: dict[str, list[str]] = {}
        for sub in await self.subscription_repo.list_all():
            if sub.active:
                consumers_by_type.setdefault(sub.event_type.name, []).append(sub.module.name)

        for event_type in event_types:
            subscribers = subscriber_counts.get(event_type.name, 0)

            # Alguien publica algo que nadie escucha. Casi siempre es un nombre
            # desalineado o una suscripcion que falta.
            if event_type.total_received > 0 and subscribers == 0:
                alerts.append(
                    {
                        "severity": "warning",
                        "kind": "NO_SUBSCRIBERS",
                        "eventType": event_type.name,
                        "detail": (
                            f"Se recibieron {event_type.total_received} evento(s) de "
                            f"'{event_type.name}' y ningun modulo esta suscripto. "
                            "Puede faltar la suscripcion, o el nombre no coincide con "
                            "el que espera el consumidor."
                        ),
                    }
                )

            # Apareció por el hub sin que nadie lo declarara.
            if event_type.discovered and event_type.total_received > 0:
                alerts.append(
                    {
                        "severity": "info",
                        "kind": "UNDECLARED_TYPE",
                        "eventType": event_type.name,
                        "detail": (
                            f"'{event_type.name}' se auto-registro al aparecer por el "
                            f"hub (origen: {event_type.owner_module or 'desconocido'}). "
                            "Nadie lo habia declarado."
                        ),
                    }
                )

            # Alguien espera algo que nunca llego, y hay alguien que se
            # comprometio a publicarlo. Sin productor declarado no es una
            # alerta: es simplemente un tipo que todavia no se usa, y en un
            # sistema recien arrancado eso serian todos.
            if (
                subscribers > 0
                and event_type.total_received == 0
                and producer_counts.get(event_type.name, 0) > 0
            ):
                alerts.append(
                    {
                        "severity": "info",
                        "kind": "NEVER_RECEIVED",
                        "eventType": event_type.name,
                        "detail": (
                            f"{subscribers} modulo(s) esperan '{event_type.name}' y "
                            f"{producer_counts[event_type.name]} lo declara(n) como "
                            "publicado, pero todavia no llego ninguno."
                        ),
                    }
                )

            # El espejo del anterior: hay quien espera y no hay quien mande.
            # Es el caso que se rompe en silencio -nadie reclama un evento que
            # nunca vio llegar- y el que queda cuando un equipo corrige el
            # nombre de su evento y el consumidor se queda en el viejo.
            if (
                subscribers > 0
                and event_type.total_received == 0
                and producer_counts.get(event_type.name, 0) == 0
            ):
                alerts.append(
                    {
                        "severity": "warning",
                        "kind": "NO_PRODUCER_DECLARED",
                        "eventType": event_type.name,
                        "detail": (
                            f"{subscribers} modulo(s) esperan '{event_type.name}' y "
                            "ningun modulo declara publicarlo. Puede ser un nombre "
                            "desalineado, o un productor que todavia no lo declaro."
                        ),
                    }
                )

            # Declarado como publicado y sin ningun consumidor: el agujero se
            # ve antes de que llegue el primer evento, que es cuando conviene.
            if (
                producer_counts.get(event_type.name, 0) > 0
                and subscribers == 0
                and event_type.total_received == 0
            ):
                alerts.append(
                    {
                        "severity": "warning",
                        "kind": "NO_CONSUMER_DECLARED",
                        "eventType": event_type.name,
                        "detail": (
                            f"'{event_type.name}' lo publica "
                            f"{producer_counts[event_type.name]} modulo(s) y no hay "
                            "ningun suscriptor. Cuando se publique, no va a llegar a "
                            "nadie."
                        ),
                    }
                )

        # Nombres sospechosamente parecidos: el sintoma tipico de un typo.
        alerts.extend(
            _similar_name_alerts(
                [et.name for et in event_types], producers_by_type, consumers_by_type
            )
        )

        # Primero lo que hay que accionar.
        order = {"warning": 0, "info": 1}
        alerts.sort(key=lambda a: (order.get(a["severity"], 2), a["kind"], a["eventType"]))
        return alerts

    # ------------------------------------------------------------------
    async def event_type_map(self) -> list[dict[str, Any]]:
        """El mapa completo: por cada tipo, quien lo publica y quien lo consume."""
        event_types = await self.event_type_repo.list_ordered()
        subscriptions = await self.subscription_repo.list_all()
        publications = await self.publication_repo.list_all()

        consumers: dict[str, list[str]] = {}
        for sub in subscriptions:
            if sub.active:
                consumers.setdefault(sub.event_type.name, []).append(sub.module.name)

        producers: dict[str, list[str]] = {}
        for pub in publications:
            if pub.active:
                producers.setdefault(pub.event_type.name, []).append(pub.module.name)

        return [
            {
                "eventType": et.name,
                "description": et.description,
                "ownerModule": et.owner_module,
                "discovered": et.discovered,
                "validates": et.json_schema is not None,
                "totalReceived": et.total_received,
                "firstSeenAt": et.first_seen_at,
                "lastSeenAt": et.last_seen_at,
                "publishedBy": sorted(producers.get(et.name, [])),
                "consumedBy": sorted(consumers.get(et.name, [])),
            }
            for et in event_types
        ]

    async def _broker_healthy(self) -> bool:
        try:
            return await self.broker.healthy()
        except Exception:
            return False


def _lado(nombre: str, publica: list[str], consume: list[str]) -> str:
    """Resume un lado del par: `nombre (publica: X · consume: Y)`."""
    pub = ", ".join(publica) if publica else "nadie"
    con = ", ".join(consume) if consume else "nadie"
    return f"'{nombre}' (publica: {pub} · consume: {con})"


def _similar_name_alerts(
    names: list[str],
    producers_by_type: dict[str, list[str]],
    consumers_by_type: dict[str, list[str]],
) -> list[dict[str, Any]]:
    """Detecta pares de nombres casi iguales.

    Con 9 equipos nombrando eventos por su cuenta, los typos y las variantes
    (`debtOverdue` vs `overdueDebt`, `streetClosureEnded` vs `streetClousureEnded`)
    son la falla de integracion mas comun y la mas dificil de ver a ojo.

    No alcanza con decir "estos dos se parecen": para accionarlo hay que saber
    quien publica y quien consume cada lado. Sin eso, el equipo tiene que salir
    a cruzar el mapa a mano. Por eso cada alerta viaja con las dos puntas y, si
    el dato alcanza, con cual nombre conviene quedarse.
    """
    alerts: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for index, left in enumerate(names):
        for right in names[index + 1 :]:
            if (left, right) in seen:
                continue
            if not _is_near_duplicate(left, right):
                continue
            seen.add((left, right))

            pub_left = sorted(producers_by_type.get(left, []))
            con_left = sorted(consumers_by_type.get(left, []))
            pub_right = sorted(producers_by_type.get(right, []))
            con_right = sorted(consumers_by_type.get(right, []))

            detail = (
                f"Nombres sospechosamente parecidos. {_lado(left, pub_left, con_left)} "
                f"y {_lado(right, pub_right, con_right)}. Si son el mismo evento, el "
                "que publica con un nombre no le llega al que consume con el otro."
            )
            # Una recomendacion solo cuando el dato la sostiene: el nombre que
            # nadie usa todavia se puede abandonar sin romper nada.
            left_vacio = not pub_left and not con_left
            right_vacio = not pub_right and not con_right
            if left_vacio != right_vacio:
                sobra, queda = (left, right) if left_vacio else (right, left)
                detail += (
                    f" Sugerencia: '{sobra}' no lo usa nadie, asi que conviene "
                    f"unificar en '{queda}'."
                )

            alerts.append(
                {
                    "severity": "warning",
                    "kind": "SIMILAR_NAMES",
                    "eventType": left,
                    "detail": detail,
                    "counterpart": right,
                    "publishedBy": pub_left,
                    "consumedBy": con_left,
                    "counterpartPublishedBy": pub_right,
                    "counterpartConsumedBy": con_right,
                }
            )
    return alerts


def _is_near_duplicate(left: str, right: str) -> bool:
    if left == right:
        return False
    lower_left, lower_right = left.lower(), right.lower()

    # Mismas palabras en otro orden: debtOverdue vs overdueDebt.
    # El camelCase se parte sobre el nombre original: pasarlo a minuscula antes
    # borraria los limites de palabra y no detectaria nada.
    if sorted(_split_camel(left)) == sorted(_split_camel(right)):
        return True

    # Distancia de edicion 1 o 2 sobre nombres largos: casi siempre un typo.
    if abs(len(lower_left) - len(lower_right)) <= 2 and min(len(left), len(right)) >= 8:
        return _edit_distance_at_most(lower_left, lower_right, 2)
    return False


def _split_camel(name: str) -> list[str]:
    words: list[str] = []
    current = ""
    for char in name:
        if char.isupper() and current:
            words.append(current.lower())
            current = char
        else:
            current += char
    if current:
        words.append(current.lower())
    return [w for w in words if w]


def _edit_distance_at_most(left: str, right: str, limit: int) -> bool:
    """Damerau-Levenshtein con corte temprano: solo importa si es <= limit.

    Cuenta la transposicion de dos caracteres adyacentes como **una** edicion,
    no dos. Importa para el caso de uso: los typos de los equipos son casi
    siempre letras invertidas (`envirometnal` por `environmental`,
    `Clousure` por `Closure`), y con Levenshtein puro cada intercambio sale 2,
    asi que un typo de dos letras se escapaba del umbral.
    """
    if abs(len(left) - len(right)) > limit:
        return False

    rows = len(left) + 1
    cols = len(right) + 1
    distance = [[0] * cols for _ in range(rows)]
    for i in range(rows):
        distance[i][0] = i
    for j in range(cols):
        distance[0][j] = j

    for i in range(1, rows):
        for j in range(1, cols):
            cost = 0 if left[i - 1] == right[j - 1] else 1
            distance[i][j] = min(
                distance[i - 1][j] + 1,  # borrar
                distance[i][j - 1] + 1,  # insertar
                distance[i - 1][j - 1] + cost,  # sustituir
            )
            # Transposicion de dos caracteres adyacentes.
            if i > 1 and j > 1 and left[i - 1] == right[j - 2] and left[i - 2] == right[j - 1]:
                distance[i][j] = min(distance[i][j], distance[i - 2][j - 2] + 1)

        if min(distance[i]) > limit:
            return False

    return distance[-1][-1] <= limit
