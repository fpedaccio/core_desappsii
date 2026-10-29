# Confirmaci?n de la transacci?n antes de responder

## Hallazgo local del 29 de octubre de 2026

La prueba E2E de rechazo por schema recibi? HTTP 422.
La consulta inmediata del mismo eventId devolvi? 404; al repetirla
medio segundo despu?s devolvi? 200.

La consulta directa confirm? que el evento estaba REJECTED, pertenec?a
al productor esperado, era visible para ?l y ten?a una ?nica entrada
SCHEMA_VIOLATION en la DLQ.

## Causa identificada y correcci?n candidata

get_session confirma la transacci?n despu?s de yield.
SessionDep utilizaba el alcance request predeterminado de FastAPI,
que ejecuta esa salida despu?s de enviar la respuesta.

Se cambia ?nicamente el alcance de SessionDep a function para completar
el commit antes de enviar la respuesta. Se mantiene el rollback existente.

## Validaci?n

Pendiente de ejecutar sobre la imagen reconstruida.
La prueba E2E conserva la consulta inmediata: no acepta un 404 transitorio.
Las evidencias anteriores se conservan.
Esta correcci?n no resuelve la atomicidad entre PostgreSQL y RabbitMQ.

## Alcance

Cambio candidato local. Sin despliegue en AWS.
