# ADR-003 · El broker vive detrás de un Adapter

- **Estado:** aceptado
- **Fecha:** 2026-10-20
- **Patrón:** Adapter (GoF, estructural / de integración)
- **Componente:** `app/messaging/broker.py`, `rabbitmq.py`, `fake.py`

## Contexto

El Core es un pasamanos de eventos: la mensajería no es un detalle, es el
trabajo. Pero `aio-pika` tiene su propio modelo —conexiones robustas, canales,
`IncomingMessage`, `ack`/`nack`— y si ese vocabulario entra en los servicios,
la lógica del hub queda atada a una librería.

El problema concreto: sin broker levantado no se podría probar nada. El pipeline
de ingesta (idempotencia, validación, evidencia, ruteo) es lo más importante que
tiene el módulo, y necesitábamos poder ejercitarlo en cada corrida de la suite.

## Decisión

Un contrato propio, `Broker`, con siete operaciones en el vocabulario del Core
(`publish`, `consume`, `declare`, `healthy`...) y **dos implementaciones**:

- `RabbitMQBroker` adapta `aio-pika`.
- `FakeBroker` es un broker en memoria que rutea de verdad: exchanges, colas,
  bindings y comodines de topic.

Los cuatro servicios reciben un `Broker`, no una conexión.

## Consecuencias

**A favor.** La suite corre completa sin RabbitMQ y el hub se prueba de punta a
punta en cada commit. Cambiar a Kafka sería escribir un tercer adaptador, no
tocar los servicios.

**En contra.** El contrato es el mínimo común: cosas específicas de RabbitMQ
—prioridades de mensaje, confirmaciones de publicación— no se pueden usar sin
antes agregarlas a la interfaz. Lo aceptamos: hasta hoy no hizo falta ninguna.

Y hay un riesgo que el patrón no cubre solo: `FakeBroker` podría divergir de
RabbitMQ y dar falsa confianza. Por eso el camino AMQP real se verifica aparte,
contra un broker de verdad, antes de cada entrega.

**Lo verificado.** `test_ningun_servicio_conoce_aio_pika` recorre `app/` y falla
si la librería aparece fuera del adaptador. Hoy sólo está en `rabbitmq.py` y en
`core/logging.py`, que filtra sus logs.
