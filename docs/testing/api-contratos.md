# API y contratos: colección, contraste y CI (T6)

Candidata: backend `16d1633c496fce0505b218249f56fca3ee7d0d4e`
([fpedaccio/core_desappsii#15](https://github.com/fpedaccio/core_desappsii/pull/15)),
frontend fijado `d00f07b71aaa61d27adcb179ec5a3180e9e78874`. Fecha: 02/11/2026.

Los resultados sobre `7b35db2` se conservan sin cambios en
[api-contratos-7b35db2.md](api-contratos-7b35db2.md).

## Revalidación sobre la integración `342b0b1`

Revisión integrada de trabajo de T8: rama `devops/t8-integracion-pr19-22`,
commit `342b0b1059e3f81c0c5520c01723d0c81c92d853`. Es `16d1633` con los PR
#19, #20, #21 (DEF-18) y #22 (DEF-19). No es la versión final etiquetada. Las
secciones siguientes, con sus corridas, corresponden a `16d1633` y se
conservan.

### Qué cambió en la colección

- **DEF-18 (#21) cambia el OpenAPI.** Agrega el parámetro `If-Match` y el 412
  en `PUT /event-types/{name}/schema`, y el ETag en las respuestas. La
  colección se regeneró: si no, el workflow de contratos falla a propósito,
  porque la colección versionada ya no coincide con el contrato en ejecución.
- **7 casos nuevos para DEF-18 (175 en total):**
  - ET-14: `GET` devuelve un ETag fuerte.
  - ET-15: `PUT` con `If-Match` vigente aplica y devuelve un ETag nuevo.
  - ET-16: con `If-Match` desactualizado responde 412 `PRECONDITION_FAILED`.
  - ET-17: verifica que el 412 no aplicó nada.
  - ET-18: un módulo ajeno recibe 403 y no 412, aunque su `If-Match` sea
    vigente.
  - ET-19: un ETag débil `W/` nunca coincide.
  - ET-20: `If-Match: *` aplica.

  ET-06 queda como el caso sin `If-Match`, que se acepta por compatibilidad.
- **`escenarios_amqp.py` declara el modo de DEF-19**
  (`CORE_EXPECT_SOURCE_CHECK`) y puede enviar `user_id`. En `enforce` no
  aplica: la regresión de ese modo es `escenarios_def19.py`.

### Resultados

| Ejecución | Entorno | Resultado |
| --- | --- | --- |
| Colección | Nativo: PostgreSQL 17.10, RabbitMQ 4.3.4, worker en `warn` | 175 de 175 (184 requests, 650 aserciones), 56 de 56 operaciones |
| Escenarios AMQP, `warn`, con `user_id` | Mismo stack | 11 de 11. AMQP-06 aceptado: en `warn` DEF-19 no está mitigado, y el worker registró `amqp_source_unverified_accepted` |
| DEF-19, `enforce`, usuarios RabbitMQ restringidos | Mismo stack, worker reiniciado en `enforce` | 8 de 8 en dos corridas (ver [def19-identidad-amqp.md](def19-identidad-amqp.md)) |
| Colección y AMQP en Docker, 3 corridas consecutivas | Workflow "Core API contracts", stack limpio con `testing_up.py`, worker en `warn` ([run 41560420733](https://github.com/fpedaccio/core_desappsii/actions/runs/41560420733), commit `ec6e618`) | 175 de 175 y 11 de 11 en las tres corridas. Backend CI y los 6 E2E de navegador también pasaron sobre ese commit |

### Contraste con el OpenAPI de `342b0b1` y alineación del contrato

En `342b0b1` las dos categorías daban lo mismo que en `16d1633` (13 operaciones
con el 422 documentado como `HTTPValidationError` y 33 con status reales sin
declarar), más el 412 sin schema y el header `ETag` sin declarar en DEF-18.

En esta revisión se alineó el OpenAPI generado por FastAPI y el endpoint
`/api/v1/auth/me` con el comportamiento real:

- **`ProblemDetails` unificado en todo el OpenAPI:** se definió `ProblemDetails`
  en `backend/app/api/v1/schemas/common.py` con los miembros exactos que emite
  `errors.py` (`type`, `title`, `status`, `detail`, `instance` opcional, `code`,
  `message`, `details`, `traceId`) y se reemplazó en `create_app()` el `422` por
  defecto (`HTTPValidationError`) por `application/problem+json` con
  `ProblemDetails` (**0 divergencias en las 13 operaciones 422**).
- **`POST /api/v1/events` (`200` y `422` dual):** el `200` (evento duplicado)
  declara `IngestResponse` (validado en `EV-02`), y el `422` diferencia las dos
  respuestas reales según la causa: `application/problem+json`
  (`ProblemDetails`) cuando el sobre es inválido y no se persiste, y
  `application/json` (`IngestResponse` con `status: REJECTED` y
  `rejectionCode: SCHEMA_VIOLATION`) cuando `data` incumple el JSON Schema del
  tipo, se persiste y se registra en la DLQ.
- **Códigos y cabeceras declarados en las 33 operaciones:** se declararon los
  status `401`, `403`, `404` y `409` en los routers correspondientes (**0
  estados observados sin documentar**), se asoció `ProblemDetails` al `412` de
  `PUT /event-types/{name}/schema` y a los `429`/`503` de `/auth/login` y
  `/auth/module-token`, y se documentaron los encabezados de respuesta `ETag`
  (en el `200` de `GET /event-types/{name}` y `PUT /event-types/{name}/schema`)
  y `Retry-After` (en `429` y `503` del limitador de autenticación).
- **`GET /api/v1/auth/me` con `id` de usuario (`AUTH-07`, `AUTH-08`):**
  `MeResponse` expone `id` obtenido del claim `sub` (`user:<uuid>`) cuando
  `kind == "user"`, y `null` cuando `kind == "module"`.
- **Decisiones de contrato explicitadas en el OpenAPI:** se documentó la
  ventana de validez residual de los JWT stateless (`expiresIn` de 15 min) tras
  rotar el secret o desactivar un módulo/cuenta (mientras las nuevas emisiones
  y entregas se bloquean en el acto), el carácter idempotente con respuesta
  `201` al redeclarar tipos, publicaciones o suscripciones existentes, y la
  visibilidad compartida del catálogo de integración (`GET /modules`,
  `/event-types`, `/publications`) entre módulos autenticados.

## Revisión probada

La rama `qa/t6-candidata-16d1633` agrega a `16d1633` solo `docs/testing/`, el
workflow `api-contracts.yml`, `sonar.yml` y `sonar-project.properties`. No cambia
nada de `backend/`, `deploy/` ni el pin del frontend (`git diff 16d1633` vacío
sobre esas rutas). En CI el bootstrap informó `backend_ref` = `5a2ae5d` (el
commit de la rama), `backend_dirty: false`, frontend `d00f07b` y estado limpio.

## Qué se entrega

| Archivo | Contenido |
| --- | --- |
| `docs/testing/api/core-api.postman_collection.json` | Colección Postman v2.1: 168 casos en 12 carpetas que cubren las 56 operaciones. Crea su fixture (`qa-t6-<run>-a/b/c`), valida status, cuerpo contra el OpenAPI, Problem Details en los errores y reglas de alcance; al final desactiva la fixture |
| `docs/testing/api/core-local.postman_environment.json` | Entorno sin valores sensibles (`adminPassword` vacío, tipo secret) |
| `docs/testing/api/casos.json` | Id, operación, identidad y status esperado de cada caso |
| `docs/testing/api/generar_coleccion.py` | Genera los tres archivos anteriores desde el OpenAPI de la candidata |
| `docs/testing/api/contrastar_contrato.py` | Contrasta una corrida de newman con el OpenAPI en dos categorías (ver abajo). Lee el JSON privado, no copia cuerpos ni credenciales |
| `docs/testing/api/escenarios_amqp.py` | 11 escenarios de ingesta por AMQP y reintentos de la DLQ con su propia fixture |
| `.github/workflows/api-contracts.yml` | Ejecución en CI sobre Docker (ver abajo) |

Los status esperados salen del código y del contrato de la candidata. Respecto
de `7b35db2` cambiaron por decisión de contrato, no para hacer pasar casos:

- Los errores son Problem Details (RFC 9457) con `application/problem+json`.
  La colección valida `type`, `title`, `status`, `detail` y las extensiones
  `code`, `message`, `details` y `traceId`.
- El módulo involucrado puede reintentar su dead letter (commit `c109297`).
  DLQ-05 ahora espera 404 para un módulo ajeno, y DLQ-20 el reintento del
  origen.

Casos agregados para cerrar los cuatro huecos de la revisión anterior:

- USR-15: edición exitosa de una cuenta.
- AUTH-15: 403 al rotar el secret de otro módulo.
- AUTH-16: 422 de `module-token` sin secret.
- DLQ-16 a DLQ-19: reintento en lote exitoso, después de que el dueño corrige
  la causa.

También se agregó DLQ-15: 409 al reintentar una dead letter ya descartada.

## Ejecuciones sobre `16d1633`

| Ejecución | Entorno | Colección | AMQP y DLQ |
| --- | --- | --- | --- |
| CI en Docker, corrida 1 | `testing_up.py`: PostgreSQL, RabbitMQ, seed, API, worker y frontend en contenedores, estado limpio | 168 de 168 (177 requests, 622 aserciones) | 11 de 11 |
| CI en Docker, corrida 2 | Mismo stack, fixture nueva | 168 de 168 | 11 de 11 |
| CI en Docker, corrida 3 | Mismo stack, fixture nueva | 168 de 168 | 11 de 11 |
| Nativa (evidencia adicional) | Mismos procesos sin contenedores: PostgreSQL 17.10 con rol `core_app`, RabbitMQ 4.3.4 en vhost exclusivo | 168 de 168 | 11 de 11 |

Ejecución de CI:
[actions/runs/41535930793](https://github.com/fpedaccio/core_desappsii/actions/runs/41535930793)
(workflow "Core API contracts", commit `5a2ae5d`). Las tres corridas
consecutivas son la prueba de estabilidad de esta suite. Las tres corridas
anteriores del workflow fallaron por la configuración del propio workflow, no
por la API:

- `f0e7522` usó un nombre de proyecto Compose que `testing_up.py` rechaza.
- `241295a` y `def81f8` tuvieron un falso positivo del control de
  credenciales: `CORS_ORIGINS` aparece en las URLs de newman. En `241295a` la
  colección y AMQP pasaron 3 de 3; se revisó su artifact y solo contiene URLs
  de `localhost`, sin secretos.

### Cómo funciona el workflow

1. Levanta el stack limpio con `deploy/testing_up.py` y verifica revisión,
   estado limpio, API y worker.
2. Exporta el OpenAPI de la API en ejecución y regenera la colección. Si no
   coincide con la versionada, falla: la colección no puede quedar
   desactualizada respecto del contrato.
3. Corre tres veces la colección y los escenarios AMQP, cada vez con su
   fixture. Los escenarios corren dentro del contenedor de la API, porque
   RabbitMQ no publica puertos al runner. El paso falla si falla cualquier
   aserción.
4. Revisa que la evidencia no contenga las contraseñas del `.env`, claves PEM
   ni JWT. Si las contiene, el job falla y el artifact no se publica.
5. Publica solo la salida de consola de newman, el contraste, la salida AMQP,
   el OpenAPI y `bootstrap-result.json`. El JSON de newman, que tiene tokens y
   secrets, queda en `deploy/.testing/api-private/` del runner y se descarta.

## Contraste con el OpenAPI de `16d1633`

El contraste se repitió sobre la candidata vigente, que ya trae Problem
Details y los cambios de autenticación. Las observaciones C-01 a C-04 de
`7b35db2` no se trasladan tal cual: estas son las diferencias vigentes.

### 1. Respuestas documentadas que no coinciden con la implementación

| Operacion | Status | Diferencia | Casos |
| --- | --- | --- | --- |
| `DELETE /api/v1/users/{user_id}` | 422 | Content-Type `application/problem+json`; declarado `application/json`; `detail` no cumple `type` | USR-14 |
| `GET /api/v1/dashboard` | 422 | Content-Type `application/problem+json`; declarado `application/json`; `detail` no cumple `type` | DSH-06, DSH-07 |
| `GET /api/v1/event-types` | 422 | Content-Type `application/problem+json`; declarado `application/json`; `detail` no cumple `type` | ET-11, ET-12 |
| `GET /api/v1/events` | 422 | Content-Type `application/problem+json`; declarado `application/json`; `detail` no cumple `type` | EV-19 |
| `POST /api/v1/auth/login` | 422 | Content-Type `application/problem+json`; declarado `application/json`; `detail` no cumple `type` | AUTH-02, AUTH-03 |
| `POST /api/v1/auth/module-token` | 422 | Content-Type `application/problem+json`; declarado `application/json`; `detail` no cumple `type` | AUTH-16 |
| `POST /api/v1/dlq/retry-bulk` | 422 | Content-Type `application/problem+json`; declarado `application/json`; `detail` no cumple `type` | DLQ-07 |
| `POST /api/v1/dlq/{dead_letter_id}/discard` | 422 | Content-Type `application/problem+json`; declarado `application/json`; `detail` no cumple `type` | DLQ-08 |
| `POST /api/v1/event-types` | 422 | Content-Type `application/problem+json`; declarado `application/json`; `detail` no cumple `type` | ET-07 |
| `POST /api/v1/modules` | 422 | Content-Type `application/problem+json`; declarado `application/json`; `detail` no cumple `type` | MOD-04 |
| `POST /api/v1/subscriptions` | 422 | Content-Type `application/problem+json`; declarado `application/json`; `detail` no cumple `type` | SUB-03, SUB-04 |
| `POST /api/v1/subscriptions/{subscription_id}/toggle` | 422 | Content-Type `application/problem+json`; declarado `application/json`; `detail` no cumple `type` | SUB-07 |
| `POST /api/v1/users` | 422 | Content-Type `application/problem+json`; declarado `application/json`; `detail` no cumple `type` | USR-03, USR-04 |

Todos los 422 llegan como Problem Details (`application/problem+json`, con
`detail` de texto), mientras que el OpenAPI declara `HTTPValidationError`
(`application/json`, con `detail` como lista de errores). Un cliente generado
desde el contrato no puede leer el 422. Las respuestas 2xx cumplen su schema
en todas las operaciones.

### 2. Respuestas reales que faltan en el OpenAPI

| Operacion | Status observados sin declarar |
| --- | --- |
| `DELETE /api/v1/publications/{publication_id}` | 403, 404 |
| `DELETE /api/v1/subscriptions/{subscription_id}` | 403, 404 |
| `DELETE /api/v1/users/{user_id}` | 409 |
| `GET /api/v1/auth/me` | 401 |
| `GET /api/v1/catalogos/barrios/{codigo}` | 404 |
| `GET /api/v1/catalogos/zonas` | 401 |
| `GET /api/v1/dashboard/global` | 403 |
| `GET /api/v1/dashboard/modules/{module_name}` | 403 |
| `GET /api/v1/dlq/{dead_letter_id}` | 404 |
| `GET /api/v1/dlq/{dead_letter_id}/audit` | 404 |
| `GET /api/v1/event-types/{name}` | 404 |
| `GET /api/v1/events/{event_id}` | 404 |
| `PATCH /api/v1/catalogos/{catalogo}/items/{codigo}` | 404 |
| `PATCH /api/v1/modules/{module_name}` | 403, 404 |
| `PATCH /api/v1/users/{user_id}` | 403, 404 |
| `POST /api/v1/auth/login` | 401, 403 |
| `POST /api/v1/auth/module-token` | 401, 403 |
| `POST /api/v1/catalogos/barrios` | 403, 404 |
| `POST /api/v1/catalogos/zonas` | 403, 409 |
| `POST /api/v1/catalogos/{catalogo}/items` | 403 |
| `POST /api/v1/deliveries/process-due-retries` | 403 |
| `POST /api/v1/dlq/retry-bulk` | 403 |
| `POST /api/v1/dlq/{dead_letter_id}/retry` | 404, 409 |
| `POST /api/v1/event-types` | 403 |
| `POST /api/v1/events` | 403 |
| `POST /api/v1/modules` | 403, 409 |
| `POST /api/v1/modules/{module_name}/rotate-secret` | 403 |
| `POST /api/v1/publications` | 403 |
| `POST /api/v1/subscriptions` | 403 |
| `POST /api/v1/subscriptions/{subscription_id}/toggle` | 403 |
| `POST /api/v1/topology/apply` | 403 |
| `POST /api/v1/users` | 403, 409 |
| `PUT /api/v1/event-types/{name}/schema` | 403 |

`POST /events` tampoco declara cuerpo para el 200 (duplicado) ni para el 422,
que tiene dos formas: Problem Details si el sobre es inválido (no se
persiste), o `IngestResponse` con `REJECTED` si el `data` no cumple el schema
(se persiste y va a la DLQ). Los 429 y el 503 del limitador están declarados,
pero sin schema; el 429 tampoco documenta `Retry-After`.

### 3. Comportamientos que requieren una decisión de contrato

| Comportamiento | Evidencia | Decisión pendiente |
| --- | --- | --- |
| Un JWT emitido antes de rotar el secret o de desactivar el módulo sigue válido hasta vencer (`expiresIn` 899 s) | AUTH-14, CLN-06 | Si HU-01 exige invalidar tokens ya emitidos |
| Por AMQP no se contrasta `sourceModule` con la identidad de la conexión | AMQP-06 (ver "Observación de seguridad") | Mecanismo de identidad y autorización por AMQP |
| Redeclarar un tipo, una publicación o una suscripción responde 201 con el mismo id | ET-02, PUB-02, SUB-02 | Si debe responder 200 al confirmar algo existente |
| `GET /modules`, `/publications` y `/event-types` listan todo a cualquier módulo | MOD-01, PUB-04, ET-10 | Que el criterio de aislamiento lo declare explícito |
| `/auth/me` no devuelve el id de la cuenta | AUTH-08 | Agregarlo, porque el perfil del frontend lo necesita para cambiar la contraseña |

Para corregir el contrato hay que declarar Problem Details en los errores y
agregar los status faltantes, y después repetir esta colección. Ningún
resultado esperado se cambió para que coincida con el OpenAPI.

## D-01 y DEF-10

En `7b35db2` la colección encontró D-01: `GET /dlq/{id}/audit` no filtraba por
módulo, y un id inexistente respondía 200. Antes y después:

| Revisión | DLQ-13 (ajeno consulta la auditoría) | DLQ-14 (id inexistente) |
| --- | --- | --- |
| `7b35db2` | 200 con actor y motivo: FAIL (corrida 5) | 200 vacío: FAIL |
| `7b35db2` + PR #14 | 404: PASS (corrida 6) | 404: PASS |
| `16d1633` | 404: PASS (CI, 3 corridas) | 404: PASS |

D-01 corresponde a **DEF-10**, que en la candidata se corrigió con el PR #11:
`_visible_dead_letter` en `backend/app/api/v1/dlq.py` aplica la misma regla al
detalle, la auditoría y el reintento. No es un defecto abierto de `16d1633` y
el código del #14 no hace falta. Del #14 se aprovechó el único test que la
candidata no tenía, el 404 de la auditoría de un id inexistente, en la rama
`test/mutacion-16d1633`.

## Ingesta por AMQP y reintentos de la DLQ

Corrida 1 de CI. Las corridas 2 y 3 dieron el mismo resultado con fixtures
propias:

| Caso | Escenario | Esperado | Observado | Resultado |
| --- | --- | --- | --- | --- |
| AMQP-01 | Evento valido publicado en muni.inbox se persiste por el canal AMQP | ingestionChannel AMQP, una entrega a B | `('AMQP', ['qa-amqp-e90c54-b'])` | PASS |
| AMQP-02 | B recibe el mensaje con las cabeceras del Core | x-core-event-id = eventId, target B, attempt 1, mismo data | `{'x-core-event-id': 'efc99d06-61fd-48e3-93c8-4afac21ffa52', 'x-core-target-module': 'qa-amqp-e90c54-b', 'x-core-attempt': 1}` | PASS |
| AMQP-03 | Reenvio del mismo eventId por AMQP no genera efectos | 1 evento del tipo, 0 mensajes nuevos en la cola de B | `eventos=1, cola B=0` | PASS |
| AMQP-04 | Mensaje que no es JSON queda como MALFORMED_MESSAGE | una dead letter MALFORMED_MESSAGE mas | `antes=0, despues=1` | PASS |
| AMQP-05 | data invalido por AMQP queda REJECTED y en la DLQ | REJECTED, SCHEMA_VIOLATION, sin entregas, cola B vacia | `('REJECTED', 'SCHEMA_VIOLATION', 0, 0)` | PASS |
| AMQP-06 | OBSERVACION: por AMQP se acepta un sourceModule cualquiera | aceptado (comportamiento actual: no se contrasta con el usuario de la conexion) | `('qa-amqp-e90c54-b', 'ROUTED')` | PASS |
| DLQ-R1 | Tras corregir el schema, el reintento reprocesa y entrega | success, evento con entrega a B, B recibe el evento, auditoria MANUAL SUCCESS | `(200, True, 1, True, [('MANUAL', 'SUCCESS')])` | PASS |
| DLQ-R2 | Rechazo del consumidor: reintento con backoff y cabeceras | intentos 1 y 2 del mismo eventId; el 2 trae x-core-last-error | `[(1, True, False), (2, True, True)]` | PASS |
| DLQ-R3 | Agotados los intentos se abre una dead letter DELIVERY_FAILED | dead letter para B; entrega con 2 intentos | `(('qa-amqp-e90c54-b', 2), [('DEAD', 2)])` | PASS |
| DLQ-R4 | Una vez abierta la dead letter no hay mas reentregas | cola B vacia | `cola B=0` | PASS |
| DLQ-R5 | Reintento manual de DELIVERY_FAILED republica con contador reiniciado | success; B recibe el mismo eventId con attempt 1; dead letter RETRIED | `(True, True, 1, 'RETRIED')` | PASS |

## Observación de seguridad: `sourceModule` por AMQP

**Estado: pendiente de evaluación de seguridad.** No se da por aceptada ni se
cambia el código hasta acordar el mecanismo de identidad.

- **Escenario.** Un módulo con credencial AMQP válida publica en `muni.inbox`
  un sobre con `sourceModule` de otro módulo, por ejemplo `rentas`.
- **Permisos necesarios.** Una credencial AMQP con permiso de escritura en
  `muni.inbox`. Según el esquema de producción, cada uno de los 9 módulos tiene
  la suya (`write` solo sobre `muni.inbox`). No hace falta configurar colas ni
  permisos de lectura ajenos.
- **Resultado observado.** En AMQP-06, en CI y en la corrida nativa, el Core
  acepta el evento, lo persiste con el `sourceModule` declarado (`ROUTED`) y lo
  entrega a los suscriptores de ese tipo. Por HTTP, el mismo intento da 403
  (EV-06).
- **Por qué pasa.** RabbitMQ valida la propiedad `user_id` solo cuando el
  mensaje la trae, y el worker no la compara con `sourceModule`.
- **Impacto posible.** Un módulo podría suplantar a otro: eventos falsos que
  disparen efectos en los consumidores y una atribución equivocada en el
  historial, el dashboard y la DLQ.
- **Opciones a evaluar.**
  - Exigir `user_id` y compararlo con `sourceModule`, primero en modo
    advertencia y después como rechazo, con aviso a los 9 equipos.
  - Mapear el usuario de la conexión al módulo en el worker.

## Evidencia privada y compartible

- **Privado, nunca en Git ni en adjuntos:** el JSON crudo de newman, porque
  contiene tokens, secrets y contraseñas sintéticas. Localmente queda en
  `deploy/.testing/t6/`, ignorado por Git, y en CI queda en el runner sin
  publicarse.
- **Compartible para G4/T7:** la salida de consola de newman, el contraste, la
  salida AMQP, el OpenAPI exportado y `bootstrap-result.json` (artifact
  `api-contracts-41535930793-1`), además de los comandos de "Reproducir" y la
  revisión exacta.

## Inventario de endpoints

Acceso según el código de `16d1633`. "Status observados" corresponde a la
corrida nativa, con la misma colección que en CI.

| # | Operación | Acceso (según código) | Status en OpenAPI | Status observados | Casos |
| --- | --- | --- | --- | --- | --- |
| 1 | `POST /auth/login` | Pública, límite 10/60 s por identidad (compartido en PostgreSQL) | 200, 422, 429, 503 | 200, 401, 403, 422, 429 (sin declarar: 401, 403) | P01, P09, AUTH-01 y 8 más |
| 2 | `POST /auth/module-token` | Pública, límite 10/60 s por identidad (compartido en PostgreSQL) | 200, 422, 429, 503 | 200, 401, 403, 422 (sin declarar: 401, 403) | P05, P06, P07 y 6 más |
| 3 | `GET /auth/me` | Autenticado | 200 | 200, 401 (sin declarar: 401) | AUTH-06, AUTH-07, AUTH-08 y 4 más |
| 4 | `GET /users` | Autenticado; ve su módulo (admin: todos) | 200 | 200 | USR-01 |
| 5 | `POST /users` | Mismo módulo o admin | 201, 422 | 201, 403, 409, 422 (sin declarar: 403, 409) | P08, USR-02, USR-03 y 3 más |
| 6 | `PATCH /users/{user_id}` | Mismo módulo o admin | 200, 422 | 200, 403, 404 (sin declarar: 403, 404) | USR-07, USR-08, USR-15 |
| 7 | `DELETE /users/{user_id}` | Mismo módulo o admin; no la última cuenta activa | 204, 422 | 204, 409, 422 (sin declarar: 409) | USR-12, USR-13, USR-14 |
| 8 | `PUT /users/{user_id}/password` | Mismo módulo o admin | 200, 422 | 200 | USR-09 |
| 9 | `GET /catalogos/zonas` | Autenticado | 200, 422 | 200, 401 (sin declarar: 401) | CAT-01, CAT-13 |
| 10 | `POST /catalogos/zonas` | Admin | 201, 422 | 201, 403, 409 (sin declarar: 403, 409) | CAT-06, CAT-07, CAT-08 |
| 11 | `PATCH /catalogos/zonas/{codigo}` | Admin | 200, 422 | 200 | CAT-09 |
| 12 | `GET /catalogos/barrios` | Autenticado | 200, 422 | 200 | CAT-02, CAT-04 |
| 13 | `POST /catalogos/barrios` | Admin | 201, 422 | 201, 403, 404 (sin declarar: 403, 404) | CAT-14, CAT-15, CAT-16 |
| 14 | `GET /catalogos/barrios/{codigo}` | Autenticado | 200, 422 | 200, 404 (sin declarar: 404) | CAT-03, CAT-05 |
| 15 | `PATCH /catalogos/barrios/{codigo}` | Admin | 200, 422 | 200 | CAT-17 |
| 16 | `GET /catalogos` | Autenticado | 200 | 200 | CAT-10 |
| 17 | `GET /catalogos/{catalogo}/items` | Autenticado | 200, 422 | 200 | CAT-11 |
| 18 | `POST /catalogos/{catalogo}/items` | Admin | 201, 422 | 201, 403 (sin declarar: 403) | CAT-12, CAT-18 |
| 19 | `PATCH /catalogos/{catalogo}/items/{codigo}` | Admin | 200, 422 | 200, 404 (sin declarar: 404) | CAT-19, CAT-20 |
| 20 | `POST /events` | Autenticado; sourceModule = propio (admin: cualquiera) | 200, 202, 422 | 200, 202, 403, 422 (sin declarar: 403) | EV-01, EV-02, EV-06 y 7 más |
| 21 | `GET /events` | Autenticado; origen o destino (admin: todo) | 200, 422 | 200, 422 | EV-16, EV-17, EV-18, EV-19 |
| 22 | `GET /events/{event_id}` | Autenticado; origen o destino, si no 404 | 200, 422 | 200, 404 (sin declarar: 404) | EV-03, EV-04, EV-05 y 3 más |
| 23 | `GET /events/journey/{correlation_id}` | Autenticado; filtra a origen o destino | 200, 422 | 200 | EV-20, EV-24 |
| 24 | `GET /events-meta/envelope-schema` | Pública | 200 | 200 | EV-21 |
| 25 | `GET /modules` | Autenticado (lista todos) | 200 | 200 | MOD-01 |
| 26 | `POST /modules` | Admin | 201, 422 | 201, 403, 409, 422 (sin declarar: 403, 409) | P02, P03, P04 y 3 más |
| 27 | `PATCH /modules/{module_name}` | Admin | 200, 422 | 200, 403, 404 (sin declarar: 403, 404) | MOD-05, MOD-06, MOD-07 y 3 más |
| 28 | `POST /modules/{module_name}/rotate-secret` | Admin | 200, 422 | 200, 403 (sin declarar: 403) | AUTH-11, AUTH-15 |
| 29 | `GET /event-types` | Autenticado | 200, 422 | 200, 422 | ET-10, ET-11, ET-12 |
| 30 | `POST /event-types` | Autenticado; dueño del tipo o admin | 201, 422 | 201, 403, 422 (sin declarar: 403) | ET-01, ET-02, ET-03 y 2 más |
| 31 | `GET /event-types/map` | Autenticado | 200 | 200 | ET-13 |
| 32 | `GET /event-types/{name}` | Autenticado | 200, 422 | 200, 404 (sin declarar: 404) | ET-08, ET-09, EV-15 |
| 33 | `PUT /event-types/{name}/schema` | Dueño del tipo o admin | 200, 422 | 200, 403 (sin declarar: 403) | ET-05, ET-06, DLQ-16, DLQ-19 |
| 34 | `GET /subscriptions` | Autenticado; ve las suyas (admin: todas) | 200 | 200 | SUB-10 |
| 35 | `POST /subscriptions` | Propio módulo o admin | 201, 422 | 201, 403, 422 (sin declarar: 403) | SUB-01, SUB-02, SUB-03 y 3 más |
| 36 | `POST /subscriptions/{subscription_id}/toggle` | Propio módulo o admin | 200, 422 | 200, 403, 422 (sin declarar: 403) | SUB-06, SUB-07, SUB-08, SUB-09 |
| 37 | `DELETE /subscriptions/{subscription_id}` | Propio módulo o admin | 204, 422 | 204, 403, 404 (sin declarar: 403, 404) | SUB-12, SUB-13, SUB-14 |
| 38 | `GET /publications` | Autenticado (lista todas) | 200 | 200 | PUB-04 |
| 39 | `POST /publications` | Propio módulo o admin | 201, 422 | 201, 403 (sin declarar: 403) | PUB-01, PUB-02, PUB-03, PUB-08 |
| 40 | `DELETE /publications/{publication_id}` | Propio módulo o admin | 204, 422 | 204, 403, 404 (sin declarar: 403, 404) | PUB-05, PUB-06, PUB-07 |
| 41 | `GET /topology` | Autenticado | 200 | 200 | TOP-01 |
| 42 | `POST /topology/apply` | Admin | 200 | 403 (sin declarar: 403) | TOP-02 |
| 43 | `GET /dlq` | Autenticado; origen o destino (admin: todo) | 200, 422 | 200 | DLQ-01, DLQ-02 |
| 44 | `GET /dlq/{dead_letter_id}` | Autenticado; origen o destino, si no 404 | 200, 422 | 200, 404 (sin declarar: 404) | DLQ-03, DLQ-04 |
| 45 | `POST /dlq/{dead_letter_id}/retry` | Admin o módulo involucrado; ajeno 404 | 200, 422 | 200, 404, 409 (sin declarar: 404, 409) | DLQ-05, DLQ-20, DLQ-15 |
| 46 | `POST /dlq/retry-bulk` | Admin | 200, 422 | 200, 403, 422 (sin declarar: 403) | DLQ-06, DLQ-07, DLQ-17 |
| 47 | `POST /dlq/{dead_letter_id}/discard` | Admin | 200, 422 | 200, 422 | DLQ-08, DLQ-09 |
| 48 | `GET /dlq/{dead_letter_id}/audit` | Autenticado; origen o destino, si no 404 (DEF-10) | 200, 422 | 200, 404 (sin declarar: 404) | DLQ-10, DLQ-13, DLQ-14 |
| 49 | `GET /deliveries` | Autenticado; solo entregas propias (admin: todas) | 200, 422 | 200 | EV-22, EV-23 |
| 50 | `POST /deliveries/process-due-retries` | Admin | 200 | 200, 403 (sin declarar: 403) | DLQ-11, DLQ-12 |
| 51 | `GET /dashboard` | Autenticado; tablero propio | 200, 422 | 200, 422 | DSH-01, DSH-06, DSH-07 |
| 52 | `GET /dashboard/modules/{module_name}` | Propio módulo o admin | 200, 422 | 200, 403 (sin declarar: 403) | DSH-02, DSH-03 |
| 53 | `GET /dashboard/global` | Admin | 200, 422 | 200, 403 (sin declarar: 403) | DSH-04, DSH-05 |
| 54 | `GET /dashboard/integration-alerts` | Autenticado | 200 | 200 | DSH-08 |
| 55 | `GET /health/live` | Pública | 200 | 200 | SAL-01 |
| 56 | `GET /health/ready` | Pública | 200 | 200 | SAL-02 |

## Reproducir

En CI: el workflow "Core API contracts" corre en cada push y pull request, y
también se puede lanzar a mano (`workflow_dispatch`).

Localmente, con el stack levantado por `testing_up.py` (Docker) en el puerto
`18083`:

```bash
set -a; . deploy/.testing/.env; set +a
npx --yes newman@6.2.2 run docs/testing/api/core-api.postman_collection.json \
  -e docs/testing/api/core-local.postman_environment.json \
  --env-var rootUrl=http://localhost:18083 \
  --env-var "adminPassword=$SEED_INITIAL_PASSWORD" \
  --reporters cli,json --reporter-json-export deploy/.testing/t6/newman.json
python3 docs/testing/api/contrastar_contrato.py deploy/.testing/openapi-qa.json deploy/.testing/t6/newman.json
docker exec -i -e CORE_ADMIN_PASSWORD="$SEED_INITIAL_PASSWORD" -e CORE_ROOT_URL=http://127.0.0.1:8000 \
  muni-core-testing-api-1 sh -c 'CORE_AMQP_URL="$RABBITMQ_URL" python -' < docs/testing/api/escenarios_amqp.py
```

En Windows/PowerShell, leer la contraseña igual que en
[api-contratos-7b35db2.md](api-contratos-7b35db2.md), sección "Reproducir".
Para regenerar la colección cuando cambie el contrato:
`python3 docs/testing/api/generar_coleccion.py deploy/.testing/openapi-qa.json`.
