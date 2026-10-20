"""Los patrones que sostienen el Core, fijados con pruebas.

No son pruebas de ceremonia: cada una falla si alguien deshace la decision de
diseno que documenta el ADR correspondiente.
"""

from __future__ import annotations

import pathlib

import pytest

from app.messaging.broker import Broker
from app.messaging.fake import FakeBroker
from app.messaging.rabbitmq import RabbitMQBroker
from app.services.retry_policy import RetryPolicy, TieredBackoff


# ----------------------------------------------------------------------
# Strategy — la politica de reintentos (ADR-002)
# ----------------------------------------------------------------------
def test_la_politica_escalona_y_repite_el_ultimo_tramo():
    """`maxAttempts` lo elige cada modulo y no conoce nuestros escalones.

    Pedir mas intentos que escalones no puede ser un error: se repite el ultimo.
    """
    politica = TieredBackoff([15, 60, 300, 900])
    assert [politica.delay_for(n) for n in range(1, 7)] == [15, 60, 300, 900, 900, 900]


def test_el_intento_cero_o_negativo_cae_en_el_primer_tramo():
    politica = TieredBackoff([15, 60])
    assert politica.delay_for(0) == 15
    assert politica.delay_for(-3) == 15


def test_se_puede_agregar_una_politica_sin_tocar_los_servicios():
    """Esto es lo que compra el patron: extender sin modificar (OCP).

    Antes la regla estaba escrita dentro de dos servicios; una politica nueva
    obligaba a editarlos. Ahora es una clase que nadie mas tiene que conocer.
    """

    class SinEspera(RetryPolicy):
        def delay_for(self, attempt: int) -> int:
            return 0

    inmediata = SinEspera()
    assert inmediata.delay_for(99) == 0
    # El criterio de agotamiento es comun y se hereda, no se reescribe.
    assert inmediata.exhausted(4, 4) is True
    assert inmediata.exhausted(2, 4) is False


def test_la_politica_quedo_en_un_solo_lugar():
    """Regresion de la violacion de OCP que motivo el refactor.

    `_delay_for` estaba duplicada identica en event_hub_service y en
    delivery_service. Si vuelve a aparecer fuera de retry_policy.py, el patron
    se deshizo.
    """
    servicios = pathlib.Path(__file__).parents[1] / "app" / "services"
    culpables = [
        f.name
        for f in servicios.glob("*.py")
        if f.name != "retry_policy.py" and "def _delay_for" in f.read_text()
    ]
    assert culpables == [], f"la politica volvio a duplicarse en: {culpables}"


def test_los_servicios_reciben_la_politica_y_no_la_construyen(client, auth):
    """Se puede inyectar otra sin tocar el servicio."""
    from app.services.delivery_service import DeliveryService
    from app.services.event_hub_service import EventHubService

    for servicio in (DeliveryService, EventHubService):
        assert "retry_policy" in servicio.__init__.__annotations__


# ----------------------------------------------------------------------
# Adapter — el broker (ADR-003)
# ----------------------------------------------------------------------
def test_las_dos_implementaciones_cumplen_el_mismo_contrato():
    for implementacion in (RabbitMQBroker, FakeBroker):
        assert issubclass(implementacion, Broker)
    faltantes = {
        nombre
        for nombre in Broker.__abstractmethods__
        if not hasattr(FakeBroker, nombre) or not hasattr(RabbitMQBroker, nombre)
    }
    assert faltantes == set()


def test_ningun_servicio_conoce_aio_pika():
    """Lo que compra el Adapter: la logica no depende de la libreria.

    Si un servicio importara aio_pika, el hub dejaria de poder correr contra el
    broker en memoria y los tests necesitarian RabbitMQ.
    """
    app_dir = pathlib.Path(__file__).parents[1] / "app"
    permitidos = {"rabbitmq.py", "logging.py"}
    culpables = [
        str(f.relative_to(app_dir))
        for f in app_dir.rglob("*.py")
        if f.name not in permitidos and "aio_pika" in f.read_text()
    ]
    assert culpables == [], f"la libreria se filtro fuera del adaptador: {culpables}"


# ----------------------------------------------------------------------
# State — el ciclo de vida de una dead letter (ADR-001)
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_una_transicion_invalida_responde_409(client, auth, make_envelope, broker):
    """Bonus de la actividad: la transicion invalida es un conflicto, no un 500.

    Una dead letter abierta se puede reintentar o descartar. Una ya resuelta,
    no: el segundo intento choca con el estado actual.
    """
    admin = await auth("core")

    # Provocar una dead letter real: un evento cuyo `data` no cumple el schema.
    await client.put(
        "/api/v1/event-types/ticketCreated/schema",
        json={"jsonSchema": {"type": "object", "required": ["ticketId"]}},
        headers=admin,
    )
    ac = await auth("atencion-ciudadana")
    await client.post(
        "/api/v1/events",
        json=make_envelope(eventType="ticketCreated", sourceModule="atencion-ciudadana", data={}),
        headers=ac,
    )

    pendientes = (await client.get("/api/v1/dlq?status=OPEN", headers=admin)).json()
    assert pendientes["items"], "se esperaba una dead letter abierta"
    dead_letter_id = pendientes["items"][0]["id"]

    primero = await client.post(
        f"/api/v1/dlq/{dead_letter_id}/discard",
        json={"reason": "duplicado de otro reclamo"},
        headers=admin,
    )
    assert primero.status_code == 200

    segundo = await client.post(f"/api/v1/dlq/{dead_letter_id}/retry", headers=admin)
    assert segundo.status_code == 409
    assert segundo.json()["code"] == "CONFLICT"
