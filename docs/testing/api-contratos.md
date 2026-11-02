# API y contratos: inventario, colección y contraste (T6)

Fecha de ejecución: 02/11/2026. Candidata de QA: backend
`7b35db216519bedcdf891aa762b2afc64ce3b019` (rama `devops/log-redaction-20261031`),
`git worktree` limpio en detached HEAD, sin cambios en el código. OpenAPI `2.0.0` exportado del
servidor en ejecución: idéntico al que genera el código (45 rutas, 56 operaciones).

Alcance: la parte **API/contratos** de T6. La parte de calidad y mutación está
en [calidad-mutacion.md](calidad-mutacion.md).

## Qué se entrega

| Archivo | Contenido |
| --- | --- |
| `docs/testing/api/core-api.postman_collection.json` | Colección Postman v2.1: 158 casos en 12 carpetas. Crea su propia fixture, valida status, cuerpo contra el schema del OpenAPI y reglas de alcance; al final desactiva la fixture |
| `docs/testing/api/core-local.postman_environment.json` | Entorno sin valores sensibles: `rootUrl`, `adminEmail` y `adminPassword` vacío (tipo secret) |
| `docs/testing/api/casos.json` | Id, carpeta, operación, identidad y status esperado de cada caso |
| `docs/testing/api/generar_coleccion.py` | Genera los tres archivos anteriores desde el OpenAPI de la candidata |
| `docs/testing/api/contrastar_contrato.py` | Cruza un reporte JSON de newman con el OpenAPI: resultado por caso, cobertura de operaciones y status no declarados. No copia cuerpos ni credenciales |

Los status esperados salen del código de la candidata (dependencias de auth,
guardas de servicios, validaciones de Pydantic) y de las descripciones del
OpenAPI, no de una corrida previa. Cuando el resultado no coincidió, el caso
quedó fallando y se registró como defecto (D-01); no se cambió el esperado.

## Entorno de ejecución y límites

- macOS sin Docker: no se pudo levantar el entorno E2E oficial (`e2e_up.py`,
  PostgreSQL + RabbitMQ en contenedores). Se ejecutó la misma revisión con
  `uvicorn` sobre **SQLite** (`SEED_ON_STARTUP=true`, `RUN_WORKER=false`) y el
  **RabbitMQ 4.3.4 local** del equipo (vhost `/`); `/health/ready` informó base
  y broker `up`.
- Contraseña del seed generada al azar para esta corrida, guardada solo en
  `deploy/.testing/t6/.env` (ignorado por Git) y pasada a newman como variable.
- Solo ingreso HTTP. La ingesta por AMQP (`muni.inbox`), los reintentos por
  `DELIVERY_FAILED` y el reintento exitoso desde la DLQ quedan fuera: necesitan
  un consumidor que falle a propósito.
- Las fechas de algunas respuestas salieron sin offset (`createdAt` de la
  auditoría). Puede ser propio de SQLite: no se registra como defecto hasta
  repetirlo sobre PostgreSQL.
- Falta repetir la colección sobre el entorno E2E oficial (ver "Reproducir").

## Resultados

| Corrida | Base | Casos PASS | Requests | Aserciones | Operaciones ejercidas |
| --- | --- | --- | --- | --- | --- |
| 1 | Con seed | — | 153 | 466 de 467 | 52 de 56 |
| 2 | Misma base | 144 de 144 | 153 | 466 de 466 | 52 de 56 |
| 3 | Misma base | 155 de 155 | 164 | 496 de 496 | 56 de 56 |
| 4 | **Base vacía** | 155 de 155 | 164 | 496 de 496 | 56 de 56 |
| 5 | Misma base que 4 | 156 de 158 | 167 | 501 de 505 | 56 de 56 |
| 6 | Misma base, código con la corrección de D-01 (`51a71dc`) | 158 de 158 | 167 | 505 de 505 | 56 de 56 |

- Corrida 1: la única falla fue EV-12. El caso esperaba el cuerpo de error común
  y el Core devuelve a propósito el resultado de ingesta (ver C-03). Se corrigió
  la aserción del caso, no la API.
- Corridas 3 y 4: se agregaron casos para las cuatro operaciones que faltaban.
  La 4 parte de una base vacía y confirma que la colección no depende de datos
  previos ni de corridas anteriores.
- Corrida 5: agrega EV-24, DLQ-13 y DLQ-14. DLQ-13 y DLQ-14 fallan por el
  defecto D-01. Sobre la candidata `7b35db2`, la colección termina con código 1.
- Corrida 6: la misma colección contra la rama `fix/dlq-audit-scope`
  ([fpedaccio/core_desappsii#14](https://github.com/fpedaccio/core_desappsii/pull/14)).
  DLQ-13 y DLQ-14 pasan con 404 y el resto no cambia. Se conserva la corrida 5
  como evidencia del defecto.

Cada corrida usa un sufijo distinto (`qa-t6-<run>-a/b/c`), así que se puede
repetir sobre la misma base.

### Evidencia de broker para idempotencia

Se consultó la API de administración de RabbitMQ después de las corridas 3, 4
y 5. En esas cinco corridas, la cola del destinatario `q.qa-t6-<run>-b` tiene **exactamente 1
mensaje**, aunque A envió el evento válido, su reenvío con el mismo `eventId`
(EV-02, `200 duplicate:true`) y un evento rechazado por schema (EV-12). La cola
de C tiene 0, porque se desuscribió antes de publicar, y A no tiene cola porque
no se suscribió a nada. Por API, EV-03 y EV-22 muestran una sola entrega.

## Hallazgos

### Defecto

**D-01: la auditoría de la DLQ no respeta el alcance por módulo.**
`GET /dlq/{id}/audit` no aplica el alcance que sí aplican `GET /dlq` y
`GET /dlq/{id}`.
- Pasos: C (sin relación con el evento) consulta la auditoría de una dead letter
  de A.
- Esperado: 404, como DLQ-03 para el detalle.
- Obtenido: 200 con los registros. Incluyen `actor` (email de quien actuó),
  `error` (motivo del descarte), resultado y fecha.
- Además, con un id inexistente responde 200 vacío en lugar de 404 (DLQ-14).
- Casos: DLQ-13 y DLQ-14, corrida 5.
- Código: `backend/app/api/v1/dlq.py`, `dead_letter_audit`. Busca por id sin
  cargar la dead letter ni comparar `caller.scope`.
- Severidad propuesta: baja-media. Hay que conocer el UUID, que no se puede
  adivinar, pero rompe una regla de aislamiento y expone emails.
- Corrección propuesta:
  [fpedaccio/core_desappsii#14](https://github.com/fpedaccio/core_desappsii/pull/14).
  Agrega dos tests que fallan sin el cambio y pasan con él (suite completa: 230
  passed), y la corrida 6 de la colección. Falta integrarla a la candidata (T8).

### Diferencias entre el contrato y la API

| Id | Hallazgo | Evidencia |
| --- | --- | --- |
| C-01 | El OpenAPI no declara 401, 403, 404 ni 409 en ninguna operación. Tampoco existe un schema de error común en `components`. En la corrida 5, 31 de las 56 operaciones devolvieron status que su contrato no lista | Columna "Status observados" del inventario |
| C-02 | El 422 se declara como `HTTPValidationError` (`{detail: [...]}`), pero el cuerpo real es `{code: "VALIDATION_ERROR", message, details: [{field, message, type}], traceId}`. Un cliente generado desde el OpenAPI no lo puede leer | AUTH-02 y todos los casos 422 |
| C-03 | `POST /events` tiene dos cuerpos distintos para el 422. Si el sobre es inválido, devuelve el error común y **no persiste** (EV-07, EV-08). Si el `data` no cumple el schema, devuelve `IngestResponse` con `status: REJECTED`, **persiste y va a la DLQ** (EV-12, EV-13, DLQ-01). La descripción del 422 dice "El evento queda en la DLQ" para los dos casos, y eso no vale para el sobre inválido. El 200 (duplicado) y el 422 no tienen schema | EV-07, EV-08, EV-12, EV-13, DLQ-01 |
| C-04 | El 429 de `login` y `module-token` no tiene schema ni documenta el header `Retry-After`, que la API sí envía | RL-02 |

### Observaciones para acordar con el criterio de cada HU

- **JWT ya emitidos.** Rotar el secret de un módulo (AUTH-11 a AUTH-14) o
  desactivarlo (CLN-01 a CLN-06) impide pedir tokens nuevos (401/403). El JWT
  ya emitido sigue siendo válido hasta que vence (`expiresIn` 899 s). Si HU-01
  exige invalidar tokens ya emitidos, hoy no se cumple. Si no lo exige, queda
  documentado como comportamiento.
- **Redeclarar responde 201.** Redeclarar un tipo, una publicación o una
  suscripción existente responde 201 con el mismo id (ET-02, PUB-02, SUB-02).
  Es idempotente, pero el status no distingue entre crear y confirmar.
- **Cambiar la propia contraseña.** `GET /auth/me` no devuelve el id de la
  cuenta (schema `MeResponse`, AUTH-08). Para usar `PUT /users/{id}/password`
  sobre la propia cuenta, el cliente tiene que buscarse en `GET /users` por
  email. Conviene agregar el id a `/auth/me`, porque el perfil del frontend lo
  necesita.
- **Listados globales.** `GET /modules`, `GET /publications` y
  `GET /event-types` muestran todo a cualquier módulo autenticado. Es el
  diseño declarado (mapa de integración); conviene que el criterio de
  aislamiento lo deje explícito.

## Inventario de endpoints

Acceso según el código de la candidata. "Status observados" corresponde a la
corrida 5.

| # | Operación | Acceso (según código) | Status en OpenAPI | Status observados | Casos |
| --- | --- | --- | --- | --- | --- |
| 1 | `POST /auth/login` | Pública, límite 10/60 s por identidad | 200, 422, 429 | 200, 401, 403, 422, 429 (sin declarar: 401, 403) | P01, P09, AUTH-01 y 8 más |
| 2 | `POST /auth/module-token` | Pública, límite 10/60 s por identidad | 200, 422, 429 | 200, 401, 403 (sin declarar: 401, 403) | P05, P06, P07 y 5 más |
| 3 | `GET /auth/me` | Autenticado | 200 | 200, 401 (sin declarar: 401) | AUTH-06, AUTH-07, AUTH-08 y 4 más |
| 4 | `GET /users` | Autenticado; ve su módulo (admin: todos) | 200 | 200 | USR-01 |
| 5 | `POST /users` | Mismo módulo o admin | 201, 422 | 201, 403, 409, 422 (sin declarar: 403, 409) | P08, USR-02, USR-03 y 3 más |
| 6 | `PATCH /users/{user_id}` | Mismo módulo o admin | 200, 422 | 403, 404 (sin declarar: 403, 404) | USR-07, USR-08 |
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
| 20 | `POST /events` | Autenticado; sourceModule = propio (admin: cualquiera) | 200, 202, 422 | 200, 202, 403, 422 (sin declarar: 403) | EV-01, EV-02, EV-06 y 6 más |
| 21 | `GET /events` | Autenticado; origen o destino (admin: todo) | 200, 422 | 200, 422 | EV-16, EV-17, EV-18, EV-19 |
| 22 | `GET /events/{event_id}` | Autenticado; origen o destino, si no 404 | 200, 422 | 200, 404 (sin declarar: 404) | EV-03, EV-04, EV-05 y 2 más |
| 23 | `GET /events/journey/{correlation_id}` | Autenticado; filtra a origen o destino | 200, 422 | 200 | EV-20, EV-24 |
| 24 | `GET /events-meta/envelope-schema` | Pública | 200 | 200 | EV-21 |
| 25 | `GET /modules` | Autenticado (lista todos) | 200 | 200 | MOD-01 |
| 26 | `POST /modules` | Admin | 201, 422 | 201, 403, 409, 422 (sin declarar: 403, 409) | P02, P03, P04 y 3 más |
| 27 | `PATCH /modules/{module_name}` | Admin | 200, 422 | 200, 403, 404 (sin declarar: 403, 404) | MOD-05, MOD-06, MOD-07 y 3 más |
| 28 | `POST /modules/{module_name}/rotate-secret` | Admin | 200, 422 | 200 | AUTH-11 |
| 29 | `GET /event-types` | Autenticado | 200, 422 | 200, 422 | ET-10, ET-11, ET-12 |
| 30 | `POST /event-types` | Autenticado; dueño del tipo o admin | 201, 422 | 201, 403, 422 (sin declarar: 403) | ET-01, ET-02, ET-03 y 2 más |
| 31 | `GET /event-types/map` | Autenticado | 200 | 200 | ET-13 |
| 32 | `GET /event-types/{name}` | Autenticado | 200, 422 | 200, 404 (sin declarar: 404) | ET-08, ET-09, EV-15 |
| 33 | `PUT /event-types/{name}/schema` | Dueño del tipo o admin | 200, 422 | 200, 403 (sin declarar: 403) | ET-05, ET-06 |
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
| 45 | `POST /dlq/{dead_letter_id}/retry` | Admin | 200, 422 | 403 (sin declarar: 403) | DLQ-05 |
| 46 | `POST /dlq/retry-bulk` | Admin | 200, 422 | 403, 422 (sin declarar: 403) | DLQ-06, DLQ-07 |
| 47 | `POST /dlq/{dead_letter_id}/discard` | Admin | 200, 422 | 200, 422 | DLQ-08, DLQ-09 |
| 48 | `GET /dlq/{dead_letter_id}/audit` | Autenticado; **sin filtro de alcance (D-01)** | 200, 422 | 200 | DLQ-10, DLQ-13, DLQ-14 |
| 49 | `GET /deliveries` | Autenticado; solo entregas propias (admin: todas) | 200, 422 | 200 | EV-22, EV-23 |
| 50 | `POST /deliveries/process-due-retries` | Admin | 200 | 200, 403 (sin declarar: 403) | DLQ-11, DLQ-12 |
| 51 | `GET /dashboard` | Autenticado; tablero propio | 200, 422 | 200, 422 | DSH-01, DSH-06, DSH-07 |
| 52 | `GET /dashboard/modules/{module_name}` | Propio módulo o admin | 200, 422 | 200, 403 (sin declarar: 403) | DSH-02, DSH-03 |
| 53 | `GET /dashboard/global` | Admin | 200, 422 | 200, 403 (sin declarar: 403) | DSH-04, DSH-05 |
| 54 | `GET /dashboard/integration-alerts` | Autenticado | 200 | 200 | DSH-08 |
| 55 | `GET /health/live` | Pública | 200 | 200 | SAL-01 |
| 56 | `GET /health/ready` | Pública | 200 | 200 | SAL-02 |

Huecos de cobertura que quedan: `PATCH /users/{user_id}` solo tiene casos
negativos (403, 404), `POST /modules/{module_name}/rotate-secret` solo el
positivo, `POST /auth/module-token` no tiene un caso 422, y el reintento desde
la DLQ (individual y en lote) solo tiene casos de permiso y validación: el
reintento exitoso queda pendiente (ver límites).

## Reproducir

Requisitos: Node 18 o superior (para `npx newman`) y la API de la candidata
levantada. Ningún comando imprime la contraseña.

En el entorno E2E oficial (Windows/Docker, guía de QA, sección 3), usar el
puerto del frontend `http://localhost:18083`, que reenvía `/api/v1` y `/health`
(es por donde `deploy/testing_up.py` consulta `/health/ready`):

```powershell
$linea = Get-Content deploy/.testing/.env | Where-Object { $_ -like 'SEED_INITIAL_PASSWORD=*' }
$env:CORE_ADMIN_PASSWORD = $linea.Substring('SEED_INITIAL_PASSWORD='.Length)
Remove-Variable linea
npx --yes newman@6.2.2 run docs/testing/api/core-api.postman_collection.json `
  -e docs/testing/api/core-local.postman_environment.json `
  --env-var rootUrl=http://localhost:18083 `
  --env-var "adminPassword=$env:CORE_ADMIN_PASSWORD" `
  --reporters cli,json --reporter-json-export deploy/.testing/t6/newman.json
Remove-Item Env:CORE_ADMIN_PASSWORD
py -3 docs/testing/api/contrastar_contrato.py deploy/.testing/openapi-qa.json deploy/.testing/t6/newman.json
```

En macOS o Linux, con la API en `http://127.0.0.1:18090` como en esta corrida:

```bash
set -a; . deploy/.testing/t6/.env; set +a
npx --yes newman@6.2.2 run docs/testing/api/core-api.postman_collection.json \
  -e docs/testing/api/core-local.postman_environment.json \
  --env-var "adminPassword=$SEED_INITIAL_PASSWORD" \
  --reporters cli,json --reporter-json-export deploy/.testing/t6/newman.json
python3 docs/testing/api/contrastar_contrato.py deploy/.testing/openapi-qa.json deploy/.testing/t6/newman.json
```

En Postman: importar la colección y el entorno, y completar `adminPassword`
solo en el valor actual (no se exporta). Después, Run collection.

**El reporte JSON de newman contiene tokens, secrets y contraseñas sintéticas**
en los cuerpos. Queda en `deploy/.testing/` y no se comparte. Para compartir
se usan la salida de consola de newman (se verificó que no contiene ninguno de
los 19 valores sensibles de la corrida) y la salida de `contrastar_contrato.py`.

Para regenerar la colección cuando cambie el contrato, exportar el OpenAPI de
la nueva candidata (guía de QA, sección 10.1) y ejecutar
`python3 docs/testing/api/generar_coleccion.py deploy/.testing/openapi-qa.json`.

## Limpieza

Cada corrida termina desactivando sus tres módulos sintéticos (CLN-01 a
CLN-03), su zona, su barrio y su ítem de catálogo. Los eventos, entregas, dead
letters, cuentas y colas se conservan como auditoría. No se borraron tablas ni
volúmenes. La base SQLite de esta corrida y el informe privado quedan en
`deploy/.testing/t6/`, fuera de Git.
