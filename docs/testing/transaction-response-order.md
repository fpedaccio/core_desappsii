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

Validaci?n local completada sobre la candidata del commit
78a82085d68cc1de7254fc579e8b8a6c7ac67abe:

- E2E: 5 pruebas aprobadas, sin fallos ni omisiones, en 11,700 segundos.
  La consulta inmediata del evento rechazado funcion? sin agregar esperas.
- Backend: 196 tests aprobados en 314,88 segundos.
  Cobertura combinada informada: 89 %. pip check aprobado.
- Integraci?n con PostgreSQL y RabbitMQ reales:
  8 tests aprobados en 12,34 segundos; c?digo de salida 0.

Evidencias locales:
- deploy/.testing/evidence/e2e-20261029-172940-e1af79/
- deploy/.testing/evidence/transaction-regression-20261029-173329/
- deploy/.integration/evidence/

Se conservan tambi?n las ejecuciones fallidas y sus diagn?sticos.
Estos resultados no equivalen a una ejecuci?n aprobada en CI ni al cierre
de todos los criterios del TP.
La prueba E2E conserva la consulta inmediata: no acepta un 404 transitorio.
Las evidencias anteriores se conservan.
Esta correcci?n no resuelve la atomicidad entre PostgreSQL y RabbitMQ.

## Alcance

Cambio candidato local. Sin despliegue en AWS.
