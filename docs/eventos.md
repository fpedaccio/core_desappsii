# Cómo publicar y consumir eventos

> **Para los 9 equipos.** El Core es un pasamanos: recibe tus eventos, los guarda
> y los entrega a quien esté suscripto. Nada más.
>
> Swagger: **http://localhost:8000/docs** · Schema en vivo del sobre:
> `GET /api/v1/events-meta/envelope-schema`

---

## 1. El sobre

Todo evento viaja con esta estructura. Los nombres de los eventos van **en inglés
y camelCase**, como se acordó en el board.

```json
{
  "eventId": "3f6c1b7e-9d24-4a1f-9f2a-2b0f0c7d5e11",
  "eventType": "ticketCreated",
  "eventVersion": "1.0",
  "occurredAt": "2026-09-08T12:34:56.789-03:00",
  "sourceModule": "atencion-ciudadana",
  "correlationId": "8a1f0c22-5d3e-4b77-9c10-6e2b4a90f3d5",
  "causationId": null,
  "data": {
    "ticketId": "TK-2026-00184",
    "category": "INFRASTRUCTURE"
  }
}
```

| Campo | Oblig. | Regla |
|---|---|---|
| `eventId` | **sí** | UUID **nuevo por evento**. Es la clave de idempotencia. |
| `eventType` | **sí** | El nombre del tipo, camelCase. |
| `eventVersion` | no (`"1.0"`) | Informativo. |
| `occurredAt` | **sí** | ISO-8601 **con offset de zona horaria**. |
| `sourceModule` | **sí** | Tu módulo. Tiene que coincidir con el autenticado. |
| `correlationId` | no | El hilo de un trámite. Ver §4. |
| `causationId` | no | El `eventId` del evento que disparó este. |
| `data` | **sí** | Tu payload. Libre, salvo que el tipo declare un schema. |

**El sobre no acepta campos extra.** Todo lo tuyo va adentro de `data`.

---

## 2. Las tres reglas que más se equivocan

### `occurredAt` necesita offset

```json
"occurredAt": "2026-09-08T12:34:56-03:00"   ✅
"occurredAt": "2026-09-08T15:34:56Z"        ✅
"occurredAt": "2026-09-08T12:34:56"         ❌ 422
```

El Core **rechaza** un timestamp sin offset en vez de asumir la hora del servidor.
Con 9 módulos desplegados por separado, un timestamp sin zona horaria no permite
saber si el reclamo entró antes o después de la orden de trabajo.

| Lenguaje | Cómo |
|---|---|
| JS / TS | `new Date().toISOString()` |
| Python | `datetime.now(timezone.utc).isoformat()` |
| Java | `OffsetDateTime.now().toString()` |
| C# | `DateTimeOffset.Now.ToString("o")` |

### `eventId` es un UUID nuevo por evento

Si reenviás el mismo, el Core responde `200` con `duplicate: true` y **no vuelve a
rutear**. Eso no es un error: es la idempotencia funcionando. Generalo una vez y
guardalo, así si tenés que reintentar no duplicás efectos.

### `sourceModule` tiene que ser el tuyo

Publicar declarando otro módulo da `403`. Nadie puede inyectar eventos haciéndose
pasar por otro equipo.

---

## 3. Autenticarse

Tu equipo tiene **dos credenciales distintas**, y esta parte usa la segunda:

| Credencial | Quién la usa | Para qué |
|---|---|---|
| Email + contraseña | Cada integrante | Entrar al dashboard |
| **Secret del módulo** | **Tu backend** | **Publicar eventos** |

Para publicar, tu backend pide un token con el secret del módulo:

```bash
curl -X POST http://localhost:8000/api/v1/auth/module-token \
  -H "Content-Type: application/json" \
  -d '{"module": "obras", "secret": "<el que te dio el equipo 9>"}'
```

```json
{ "accessToken": "eyJ...", "tokenType": "Bearer", "expiresIn": 900, "kind": "module" }
```

Dura 15 minutos, sin refresh: cuando expira pedís otro.

**El secret va en la configuración de tu backend, no lo usa ninguna persona.**
Están separados a propósito: si se rota el secret, nadie pierde el acceso al
dashboard; y si alguien cambia su contraseña, tu backend sigue publicando.

Si perdiste el secret, el equipo 9 lo rota con
`POST /api/v1/modules/{tu-modulo}/rotate-secret` — pero acordate de actualizar la
config de tu backend, porque el anterior deja de servir en el acto.

Para **entrar al dashboard**, cada integrante usa su propia cuenta:

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -d '{"email": "ana@obras.uade.edu.ar", "password": "..."}'
```

Tu equipo arranca con una cuenta inicial (`<tu-modulo>@muni.uade.edu.ar`) y desde
el dashboard crean las de cada integrante con `POST /api/v1/users`.

## 4. `correlationId`: el recorrido de un trámite

Cuando tu evento es consecuencia de otro, **propagá el mismo `correlationId`** y
poné el `eventId` del que consumiste en tu `causationId`.

```
correlationId: aaaa-…-eeee   (lo genera atencion-ciudadana al crear el ticket)
  │
  ├── ticketCreated             (atencion-ciudadana)  ← genera el correlationId
  ├── workOrderScheduled        (obras)               ← mismo correlationId
  ├── streetClosureRequested    (obras)               ← mismo correlationId
  ├── streetClosureApproved     (transito)            ← mismo correlationId
  ├── workOrderCompleted        (obras)               ← mismo correlationId
  └── updateTicketStatus        (atencion-ciudadana)  ← mismo correlationId
```

Con eso `GET /api/v1/events/journey/{correlationId}` reconstruye el recorrido
completo entre módulos.

**Si arrancás sin esto, después no se puede reconstruir para atrás.** Conviene
propagarlo desde el primer día. Si tu evento nace de una acción directa del
usuario y no viene de ningún otro, generá un `correlationId` nuevo.

---

## 5. Publicar

### Por AMQP (recomendado)

Al exchange **`muni.inbox`** (fanout, durable). No hace falta routing key.

```
exchange:      muni.inbox
tipo:          fanout
routing key:   ""  (se ignora)
persistente:   sí (delivery_mode = 2)
content-type:  application/json
```

Que la cola sea durable importa: **si el Core está caído tu `publish` sigue
funcionando** y los mensajes esperan. No se pierde nada y tu módulo no se bloquea.

### Por HTTP

```bash
curl -X POST http://localhost:8000/api/v1/events \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ ...el sobre... }'
```

Mismo pipeline que AMQP.

### Respuestas

| Código | Significa | Qué hacer |
|---|---|---|
| `202` | Aceptado y ruteado. `routedTo` dice a quién le llegó. | Nada. |
| `200` | `duplicate: true` — ese `eventId` ya se procesó. | Nada. |
| `403` | El `sourceModule` no es el tuyo, o el token venció. | Revisar. |
| `422` | El sobre o el `data` no validan. `details` dice qué campo. | Corregir y reenviar **con el mismo `eventId`**. |
| `503` | El broker no está disponible. | Reintentar con backoff. |

**Un `422` no significa que el evento se perdió.** Queda guardado en la DLQ del
Core con el motivo, y se reprocesa desde el panel una vez corregida la causa.

---

## 6. Consumir

Tu módulo tiene **una cola propia**: `q.<tu-modulo>` (por ejemplo `q.obras`). El
Core la declara y le hace los bindings de los tipos a los que estés suscripto. Vos
solo consumís de ahí.

```
cola:      q.obras
prefetch:  10–20
```

### ack / nack

| Situación | Qué hacer | Qué pasa |
|---|---|---|
| Lo procesaste bien | `ack` | Listo. |
| Error transitorio (tu DB cayó, timeout) | `nack(requeue=false)` | El Core reintenta **5s → 30s → 2m → 10m**. Agotados, va a la DLQ. |
| Error permanente (el payload no te sirve) | `nack(requeue=false)` | Igual: DLQ con el motivo. |

**No uses `requeue=true`.** La cadena de reintentos la maneja el Core; si
reencolás, el mensaje gira en tu cola sin backoff y sin quedar auditado.

### Idempotencia de tu lado también

El Core no rutea dos veces el mismo `eventId`, pero un `nack` + reintento **sí**
puede entregarte el mismo mensaje otra vez (es *at-least-once*, como cualquier
broker). Guardá los `eventId` que ya aplicaste y salí temprano si repite.

---

## 7. Suscribirte

Podés hacerlo desde el dashboard o por API:

```http
POST /api/v1/subscriptions
{ "eventType": "ticketCreated", "maxAttempts": 4 }
```

La cola y su binding se declaran en el broker en el acto. Podés suscribirte a un
tipo que todavía nadie publicó: cuando llegue el primero, ya tiene destino.

Para ver qué hay disponible:

```http
GET /api/v1/event-types
GET /api/v1/event-types/map      quién publica y quién consume cada tipo
```

---

## 8. Tipos de evento: no hace falta declararlos

**Un tipo que nadie declaró no se rechaza.** El Core lo registra solo y lo marca
como `discovered` en el dashboard.

Es a propósito: los equipos todavía están alineando nombres, y trabar la
integración por un typo sería peor que dejarlo pasar y mostrarlo. Si publicás
`ticketCreatd` por error, el evento entra, no le llega a nadie, y aparece en las
alertas de integración para que lo veas.

Declararlo igual sirve para dos cosas: ponerle descripción, y **activar la
validación de estructura**.

```http
POST /api/v1/event-types
{
  "name": "workOrderScheduled",
  "ownerModule": "obras",
  "description": "Se programo una orden de trabajo.",
  "jsonSchema": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
      "workOrderId": { "type": "string" },
      "scheduledFor": { "type": "string", "format": "date-time" }
    },
    "required": ["workOrderId"],
    "additionalProperties": true
  }
}
```

**El `jsonSchema` es opcional.** Sin schema, el `data` pasa sin que lo miren. Con
schema, lo que no cumple va a la DLQ con el campo exacto que falló.

Recomendación: dejá `additionalProperties: true`, así podés agregar campos a tu
`data` sin romper a los consumidores.

Para activar o quitar la validación después:

```http
PUT /api/v1/event-types/workOrderScheduled/schema
{ "jsonSchema": { ... } }      # activar
{ "jsonSchema": null }         # desactivar
```

---

## 9. Checklist antes de integrar

- [ ] Tenés el `secret` de máquina de tu módulo (lo da el equipo 9) en la config
      de tu backend.
- [ ] Cada integrante tiene su cuenta del dashboard.
- [ ] Te suscribiste a lo que querés recibir.
- [ ] Declaraste lo que publicás (`POST /api/v1/publications`) — es documentación,
      no un permiso, pero es lo que hace que el mapa detecte los agujeros.
- [ ] Generás un `eventId` UUID nuevo por evento y lo guardás.
- [ ] Tus `occurredAt` llevan offset de zona horaria.
- [ ] Propagás el `correlationId` cuando tu evento viene de otro.
- [ ] Guardás los `eventId` que ya procesaste.
- [ ] Hacés `nack(requeue=false)`, nunca `requeue=true`.
- [ ] Revisaste [desalineaciones.md](desalineaciones.md) para ver si algún nombre
      tuyo no coincide con el que espera el otro equipo.

---

## 10. Cuando algo no funciona

```http
GET /api/v1/events/{eventId}     ¿llegó? ¿a quién se le entregó?
GET /api/v1/dlq                  ¿falló? ¿por qué?
GET /api/v1/dashboard            tus estadísticas
```

Si el evento **no aparece**, no llegó al Core: revisá a qué exchange publicás y tu
token.

Si aparece con `NO_SUBSCRIBERS`, llegó bien pero **nadie está suscripto**: falta la
suscripción, o el nombre no coincide con el que espera el consumidor. Es la causa
más común.

Si aparece con `REJECTED`, mirá `rejectionReason`. Está en la DLQ, no se perdió.

Todos los errores traen un `traceId` (también en el header `X-Trace-Id`). **Si
algo no cierra, pasale ese `traceId` al equipo 9.**
