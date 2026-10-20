# ADR-001 · El ciclo de vida de una entrega es una máquina de estados explícita

- **Estado:** aceptado
- **Fecha:** 2026-10-20
- **Patrón:** State (GoF, comportamiento)
- **Componente:** `app/models/events.py`, `app/services/delivery_service.py`

## Contexto

La entidad central del Core no es el evento: es la **entrega**. Un evento que
llega se copia en una entrega por cada módulo suscripto, y cada una tiene su
propia vida, sus propios reintentos y su propio desenlace. El mismo evento puede
estar entregado para Obras y muerto para Rentas.

Esa vida tiene reglas: una entrega muerta no se vuelve a intentar sola, una
descartada no revive, y una dead letter resuelta no se resuelve dos veces. Si
esas reglas viven como `if` sueltos en cada método que toca el estado, se
contradicen apenas aparece una transición nueva.

## Decisión

El estado es un valor explícito (`DeliveryStatus`, `DeadLetterStatus`) y **las
transiciones válidas se verifican antes de aplicarse**. Intentar una transición
que la máquina no permite es un conflicto con el estado actual, no un error del
cliente ni una falla del servidor: responde **409 Conflict**.

```
Delivery      PENDING ─────► DELIVERED
                 │
                 ├──────────► RETRYING ──► DELIVERED
                 │                 │
                 │                 └─────► DEAD
                 └──────────► DISCARDED

DeadLetter    OPEN ──► RETRIED
                └────► DISCARDED      (RETRIED y DISCARDED son terminales)
```

## Consecuencias

**A favor.** El estado alcanza para saber qué se puede hacer con una entrega:
no hay que reconstruirlo cruzando contadores y fechas. El dashboard filtra por
estado y la DLQ es, literalmente, las entregas en `DEAD`.

**En contra.** Agregar un estado obliga a revisar la tabla de transiciones. Es
el costo que se paga por que la regla esté en un solo lugar, y preferimos eso a
descubrir la contradicción en producción.

**Lo verificado.** `tests/test_patrones.py::test_una_transicion_invalida_responde_409`
provoca una dead letter real, la descarta y después intenta reintentarla: el
Core responde 409 con `code: CONFLICT`.
