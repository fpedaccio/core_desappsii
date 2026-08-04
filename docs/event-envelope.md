# Contrato de eventos de la plataforma

> **Para los 9 equipos.** Este es el formato que tienen que respetar todos los eventos
> asincrónicos de la Municipalidad de Ciudad UADE. Lo define y valida el módulo **Core**.
>
> Versión viva del schema: `GET /api/v1/events-meta/envelope-schema`

---

## 1. El sobre

Todo evento viaja dentro de este sobre. Los 5 campos que exige el enunciado (tipo,
identificador único, fecha y hora, módulo de origen, datos) son obligatorios; los otros dos son
opcionales pero muy recomendados.

```json
{
  "eventId": "3f6c1b7e-9d24-4a1f-9f2a-2b0f0c7d5e11",
  "eventType": "ReclamoDerivado",
  "eventVersion": "1.0",
  "occurredAt": "2026-08-04T12:34:56.789-03:00",
  "sourceModule": "atencion-ciudadana",
  "correlationId": "8a1f0c22-5d3e-4b77-9c10-6e2b4a90f3d5",
  "causationId": null,
  "data": {
    "reclamoId": "RC-2026-00184",
    "areaDestino": "obras",
    "categoria": "INFRAESTRUCTURA",
    "prioridad": "ALTA"
  }
}
```

| Campo | Tipo | Oblig. | Regla |
|---|---|---|---|
| `eventId` | UUID | **sí** | Único por evento. **Es la clave de idempotencia**: si lo reenviás, el Core lo detecta y no vuelve a rutearlo. Generalo una vez y guardalo. |
| `eventType` | string (≤120) | **sí** | Nombre exacto del tipo, en PascalCase. Tiene que estar registrado en el catálogo. |
| `eventVersion` | string (≤20) | no (`"1.0"`) | Versión del contrato contra la que se valida `data`. |
| `occurredAt` | ISO-8601 | **sí** | **Con offset de zona horaria obligatorio.** Ver §2. |
| `sourceModule` | string (≤60) | **sí** | Tu identificador técnico en minúscula: `obras`, `rentas`, `atencion-ciudadana`… |
| `correlationId` | UUID | no | Hilo de una *journey*. Ver §3. |
| `causationId` | UUID | no | El `eventId` del evento que disparó este. Sirve para reconstruir la cadena causal. |
| `data` | objeto | **sí** | Payload propio del tipo. Se valida contra el JSON Schema de la versión. |

**No se aceptan campos extra en el sobre** (`additionalProperties: false`). Todo lo tuyo va
adentro de `data`.

---

## 2. Fechas: el offset no es opcional

```json
"occurredAt": "2026-08-04T12:34:56.789-03:00"   ✅
"occurredAt": "2026-08-04T15:34:56.789Z"        ✅
"occurredAt": "2026-08-04T12:34:56"             ❌ 422
"occurredAt": "04/08/2026 12:34"                ❌ 422
```

El Core **rechaza** un timestamp sin offset en lugar de asumir la hora local del servidor.
Con 9 módulos desplegados por separado, un timestamp sin zona horaria es ambiguo: no hay forma
de saber si el reclamo entró antes o después de la orden de trabajo. Es la regla 4 del enunciado.

La mayoría de los lenguajes lo dan bien si usás el tipo con zona horaria:

| Lenguaje | Cómo |
|---|---|
| JavaScript / TypeScript | `new Date().toISOString()` |
| Python | `datetime.now(timezone.utc).isoformat()` |
| Java | `OffsetDateTime.now().toString()` |
| C# | `DateTimeOffset.Now.ToString("o")` |

---

## 3. `correlationId`: la journey del ciudadano

Cuando un evento tuyo es consecuencia de otro, **propagá el mismo `correlationId`**. El Core
reconstruye el recorrido completo con `GET /api/v1/events/journey/{correlationId}`.

Ejemplo del enunciado, el reclamo por un bache:

```
correlationId: aaaa-…-eeee   (lo genera Atención Ciudadana al crear el reclamo)
  │
  ├── ReclamoCreado          (atencion-ciudadana)  ← genera el correlationId
  ├── ReclamoDerivado        (atencion-ciudadana)  ← mismo correlationId
  ├── OrdenTrabajoCreada     (obras)               ← mismo correlationId
  ├── CorteCalleSolicitado   (obras)               ← mismo correlationId
  ├── CorteCalleAutorizado   (transito)            ← mismo correlationId
  ├── OrdenTrabajoFinalizada (obras)               ← mismo correlationId
  ├── ReclamoResuelto        (atencion-ciudadana)  ← mismo correlationId
  └── NotificacionEnviada    (core)                ← mismo correlationId
```

**Regla práctica:** si tu evento sale de haber consumido otro, copiale el `correlationId` y poné
su `eventId` en tu `causationId`. Si el evento nace de una acción directa del usuario y no viene
de ningún otro, generá un `correlationId` nuevo.

Esta es la vista con la que se defiende la **entrega final (Journey del cliente)**, así que
conviene propagarlo desde el día uno.

---

## 4. Cómo publicar

### Opción A — AMQP (la recomendada)

Publicá en el exchange **`muni.inbox`** (fanout, durable). No hace falta routing key: el Core
decide a quién le toca leyendo las suscripciones.

```
exchange:      muni.inbox
tipo:          fanout
routing key:   ""  (se ignora)
persistente:   sí (delivery_mode = 2)
content-type:  application/json
```

Que la cola sea durable importa: **si el Core está caído, tu `publish` sigue funcionando** y los
mensajes esperan en `core.inbox`. No se pierde nada y tu módulo no se bloquea.

### Opción B — HTTP

```bash
curl -X POST http://localhost:8000/api/v1/events \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "eventId": "3f6c1b7e-9d24-4a1f-9f2a-2b0f0c7d5e11",
    "eventType": "ReclamoDerivado",
    "eventVersion": "1.0",
    "occurredAt": "2026-08-04T12:34:56.789-03:00",
    "sourceModule": "atencion-ciudadana",
    "correlationId": "8a1f0c22-5d3e-4b77-9c10-6e2b4a90f3d5",
    "data": { "reclamoId": "RC-2026-00184", "areaDestino": "obras", "prioridad": "ALTA" }
  }'
```

Mismo pipeline que AMQP: idempotencia, validación de contrato, evidencia y ruteo.

### Respuestas

| Código | Significa | Qué hacer |
|---|---|---|
| `202` | Aceptado y ruteado. `routedTo` lista los módulos que lo recibieron. | Nada. |
| `200` | `duplicate: true` — ese `eventId` ya se procesó. | Nada. No es un error: es la idempotencia funcionando. |
| `422` | El sobre o el contrato no validan. `rejectionCode` + `details` dicen qué falló. | Corregir y reenviar con **el mismo** `eventId`. El evento quedó guardado en la DLQ, no se perdió. |
| `401` / `403` | Token vencido o sin scope `events:publish`. | Pedir otro token. |
| `503` | El broker no está disponible. | Reintentar con backoff. |

Códigos de rechazo posibles: `SCHEMA_VIOLATION`, `UNKNOWN_EVENT_TYPE`,
`UNKNOWN_CONTRACT_VERSION`, `VALIDATION_ERROR`.

---

## 5. Autenticación

El Core es el proveedor de identidad de la plataforma. Tu módulo tiene una **cuenta de servicio**.

```bash
curl -X POST http://localhost:8000/api/v1/auth/token \
  -H "Content-Type: application/json" \
  -d '{"clientId": "obras", "clientSecret": "<el secret que te dio el equipo 9>"}'
```

```json
{ "accessToken": "eyJ...", "tokenType": "Bearer", "expiresIn": 900 }
```

El token dura 15 minutos y no tiene refresh: cuando expira, pedís otro.

### Para validar tokens de usuarios: NO nos llames

Si tu módulo recibe un token de un ciudadano y necesita validarlo, **no uses
`/auth/introspect`**. Cacheá la clave pública y validá localmente:

```
GET /.well-known/jwks.json
```

Algoritmo **RS256**, `issuer: muni-core`, `audience: muni-platform`. Los claims útiles son
`sub`, `email`, `roles`, `permissions`.

Validar offline es lo que hace que una caída del Core no bloquee el login de toda la plataforma.
Usá `/auth/introspect` solo si de verdad necesitás el estado en vivo del token.

---

## 6. Cómo consumir

Tu módulo tiene **una cola propia**: `q.<tu-modulo>` (por ejemplo `q.obras`). El Core la declara
y le hace los bindings de los tipos a los que estés suscripto. Vos solo consumís de ahí.

```
cola:      q.obras
prefetch:  10–20
```

### Semántica de ack / nack — importante

| Situación | Qué hacer | Qué pasa |
|---|---|---|
| Lo procesaste bien | `ack` | Listo. |
| Error transitorio (tu DB cayó, timeout) | `nack(requeue=false)` | El Core lo reintenta con backoff **5s → 30s → 2m → 10m**. Agotados los intentos, va a la DLQ y un operador lo ve en el panel. |
| Error permanente (el payload no te sirve) | `nack(requeue=false)` | Igual: va a la DLQ con el motivo. Alguien lo revisa. |

**No uses `requeue=true`.** La cadena de reintentos la gobierna el Core; si reencolás, el mensaje
gira en la misma cola sin backoff y sin quedar auditado.

### Idempotencia de tu lado

El Core garantiza que no rutea dos veces el mismo `eventId`, pero un `nack` + reintento **sí**
puede entregarte el mismo mensaje otra vez (es *at-least-once*, como cualquier broker). Guardá
los `eventId` que ya aplicaste y salí temprano si repite. La regla 1 del enunciado —"un evento ya
procesado no deberá generar efectos duplicados"— aplica a los dos lados.

Si querés consultar qué consumidores procesaron un evento:
`GET /api/v1/events/{eventId}/processed-by`

---

## 7. Registrar tus tipos de evento

**Un tipo que no está en el catálogo se rechaza** (`UNKNOWN_EVENT_TYPE`) y va a la DLQ. Sin
catálogo el Core no sabe validarlo ni a quién entregarlo. Los 101 tipos del enunciado ya están
sembrados, así que probablemente el tuyo ya exista — verificá primero:

```bash
GET /api/v1/event-types?ownerModule=obras
GET /api/v1/event-types/catalog.md      # el catálogo completo, documentado
```

Para uno nuevo:

```bash
# 1. El tipo
POST /api/v1/event-types
{ "name": "OrdenTrabajoReasignada", "ownerModule": "obras",
  "description": "Una orden de trabajo cambio de cuadrilla." }

# 2. Su contrato
POST /api/v1/event-types/{id}/versions
{
  "version": "1.0",
  "jsonSchema": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
      "ordenId":         { "type": "string" },
      "cuadrillaAnterior": { "type": "string" },
      "cuadrillaNueva":  { "type": "string" }
    },
    "required": ["ordenId", "cuadrillaNueva"],
    "additionalProperties": true
  },
  "example": { "ordenId": "OT-2026-0044", "cuadrillaNueva": "CUAD-3" },
  "publish": true
}
```

Antes de mandar un evento de verdad, podés probar el payload:

```bash
POST /api/v1/event-types/validate-sample
{ "eventType": "OrdenTrabajoReasignada", "version": "1.0",
  "data": { "ordenId": "OT-2026-0044", "cuadrillaNueva": "CUAD-3" } }
```

### Dejá `additionalProperties: true`

Así podés agregar campos a `data` sin romper a los consumidores. Si lo cerrás, **cualquier campo
nuevo se vuelve un cambio incompatible**.

### Cambiar un contrato ya publicado

Creá una versión nueva, no edites la vigente: hay eventos en vuelo y en colas que declaran la
anterior. El Core clasifica el cambio solo:

```bash
POST /api/v1/event-types/{id}/compatibility-check
{ "jsonSchema": { ...tu schema nuevo... } }
```

| Veredicto | Qué significa | Cómo desplegar |
|---|---|---|
| `FULL` | Compatible en las dos direcciones. | Desplegá cuando quieras. |
| `BACKWARD` | Un consumidor nuevo lee eventos viejos, pero no al revés. | Actualizá **primero los consumidores**. |
| `FORWARD` | Un consumidor viejo lee eventos nuevos, pero no al revés. | **Drená las colas** antes de desplegar. |
| `BREAKING` | Rompe las dos. | Publicalo como un tipo nuevo, o coordinen una ventana. |

Casos típicos: agregar un campo **requerido** rompe BACKWARD; **quitar** un campo requerido rompe
FORWARD; cambiar el tipo de un campo rompe las dos.

---

## 8. Los eventos que ya existen

Están los 101 tipos de las tablas del enunciado, cada uno con su contrato y su módulo
propietario. Los que más se cruzan entre equipos:

| Evento | Lo publica | Lo consumen |
|---|---|---|
| `CiudadanoRegistrado` | ciudadanos | rentas, desarrollo-social, **core** (provisiona la cuenta) |
| `OrganizacionRegistrada` | ciudadanos | habilitaciones, rentas |
| `ReclamoDerivado` | atencion-ciudadana | obras, habilitaciones, ambiente, transito, desarrollo-social |
| `OrdenTrabajoFinalizada` | obras | atencion-ciudadana, ambiente |
| `CorteCalleSolicitado` | obras | transito |
| `CorteCalleAutorizado` / `Rechazado` | transito | obras, ambiente |
| `TasaHabilitacionGenerada` | habilitaciones | rentas |
| `InfraccionConfirmada` | transito | rentas |
| `PagoRegistrado` | rentas | habilitaciones, transito |
| `BeneficioSocialAprobado` | desarrollo-social | rentas, atencion-ciudadana, ciudadanos |
| `NotificacionEnviada` / `Fallida` | **core** | atencion-ciudadana, habilitaciones, ambiente, desarrollo-social |

Cada dato tiene **un único módulo propietario** (regla 8). Los eventos llevan identificadores y
hechos de negocio; ningún módulo modifica datos ajenos.

---

## 9. Checklist antes de integrar

- [ ] Tenés tu `clientId` / `clientSecret` (los pide el equipo 9).
- [ ] Tus tipos de evento están en el catálogo con su JSON Schema publicado.
- [ ] Te declaraste **productor** de lo que publicás (`POST /api/v1/registry/producers`).
- [ ] Te **suscribiste** a lo que consumís (`POST /api/v1/registry/subscriptions`).
- [ ] Tu `health_url` está registrado, así el tablero del Core te muestra arriba.
- [ ] Generás un `eventId` UUID **nuevo por evento** y lo guardás.
- [ ] Tus `occurredAt` llevan offset de zona horaria.
- [ ] Propagás el `correlationId` cuando tu evento viene de otro.
- [ ] Guardás los `eventId` que ya procesaste (idempotencia de tu lado).
- [ ] Hacés `nack(requeue=false)` cuando falla, nunca `requeue=true`.
- [ ] Validás tokens con el JWKS cacheado, no llamando al Core en cada request.

---

## 10. Errores

Todos los errores de la API tienen la misma forma:

```json
{
  "code": "SCHEMA_VIOLATION",
  "message": "El payload no cumple el contrato declarado (2 error(es)).",
  "details": [
    { "field": "areaDestino", "message": "'areaDestino' is a required property",
      "constraint": "required" }
  ],
  "traceId": "9f2a-…"
}
```

El `traceId` también viaja en el header `X-Trace-Id`. **Si algo falla, pasale ese `traceId` al
equipo 9**: con eso encontramos tu evento en la bitácora y en los logs. Podés mandarlo vos en el
request y lo respetamos, así se sigue una operación entre módulos.

---

## Dónde mirar

| Qué | Dónde |
|---|---|
| Swagger completo | `GET /docs` |
| Schema del sobre en vivo | `GET /api/v1/events-meta/envelope-schema` |
| Catálogo de eventos documentado | `GET /api/v1/event-types/catalog.md` |
| Tu evento después de publicarlo | `GET /api/v1/events/by-event-id/{eventId}` |
| La journey completa | `GET /api/v1/events/journey/{correlationId}` |
| Si algo cayó en la DLQ | `GET /api/v1/dlq?targetModule=obras` |
