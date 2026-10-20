# ADR-002 · La política de reintentos es una Strategy inyectable

- **Estado:** aceptado
- **Fecha:** 2026-10-20
- **Patrón:** Strategy (GoF, comportamiento)
- **Componente:** `app/services/retry_policy.py`

## Contexto

La regla de cuánto esperar antes del próximo intento estaba escrita **dos
veces, idéntica**, en `event_hub_service.py` y en `delivery_service.py`:

```python
def _delay_for(attempt: int) -> int:
    delays = settings.retry_delays or [5]
    return delays[min(max(attempt, 1), len(delays)) - 1]
```

No es sólo repetición. Significa que cambiar la política **obliga a modificar
los dos servicios**, y que nada garantiza que sigan de acuerdo. Es una violación
del principio abierto/cerrado: para extender el comportamiento hay que editar
código existente y probado.

Y es una violación con fecha de vencimiento: el día que alguien quiera backoff
exponencial o agregar *jitter* para que los nueve módulos no reintenten todos en
el mismo instante, va a tener que escribirlo en los dos lados otra vez.

## Decisión

La política pasa a ser un objeto detrás de una interfaz.

```python
class RetryPolicy(ABC):
    @abstractmethod
    def delay_for(self, attempt: int) -> int: ...

    def exhausted(self, attempt: int, max_attempts: int) -> bool:
        return attempt >= max_attempts
```

`TieredBackoff` es la implementación actual: escalones fijos de `RETRY_DELAYS`,
que son los que hacen posible el backoff **sin ningún proceso durmiendo** —cada
escalón es una cola con su `x-message-ttl` y el que espera es el broker—. Los
dos servicios la reciben por constructor y no saben cómo calcula.

`exhausted` tiene implementación por defecto a propósito: el criterio de
agotamiento es común a todas las políticas y no hay razón para que cada una lo
reescriba.

## Consecuencias

**A favor.** Agregar una política es escribir una clase; ningún servicio se
toca. Y se puede inyectar una distinta en las pruebas sin alterar la
configuración global, que antes era la única forma de cambiarla.

**En contra.** Una indirección más entre el servicio y un cálculo de tres
líneas. Se justifica porque ese cálculo estaba duplicado y es el tipo de regla
que cambia.

**Lo verificado.** `test_la_politica_quedo_en_un_solo_lugar` recorre
`app/services/` y falla si `_delay_for` vuelve a aparecer fuera de
`retry_policy.py`: es una regresión de la violación, no un comentario.
