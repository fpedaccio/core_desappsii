# API del Core — guía para el frontend

Todo lo que necesitás para armar el dashboard. La referencia navegable y con
ejemplos por endpoint está en **Swagger: http://localhost:8000/docs**.

---

## Lo que hace el Core, en dos frases

Es un **pasamanos de eventos**: recibe los eventos de los 9 módulos de la
municipalidad, valida que estén bien formados, guarda evidencia y los entrega a
quien esté suscripto. No maneja usuarios ni ciudadanos, y no valida reglas de
negocio de las áreas.

El dashboard tiene que dejar que cada equipo **entre con su credencial**, vea sus
estadísticas y sus eventos, y **se suscriba** a los tipos que quiere recibir.

---

## Convenciones

- Base URL: `http://localhost:8000/api/v1` (va a cambiar en el deploy)
- Todo JSON, todo **camelCase**
- Auth: `Authorization: Bearer <token>` en todo salvo el login y `/health/*`
- Todos los errores tienen la misma forma:

```json
{
  "code": "FORBIDDEN",
  "message": "Estas autenticado como 'obras' y solo podes ver tu propio tablero.",
  "details": [],
  "traceId": "9f2a-..."
}
```

El `message` está escrito para mostrarse al usuario tal cual. El `traceId` viene
también en el header `X-Trace-Id`: conviene loguearlo, sirve para rastrear un
problema con el equipo del Core.

Los listados paginados devuelven siempre:

```json
{ "items": [...], "total": 143, "page": 1, "size": 25, "pages": 6 }
```

---

## 1. Login

Hay **dos credenciales distintas** y conviene tener clara la diferencia:

| | Quién la usa | Para qué |
|---|---|---|
| **Email + contraseña** | Las personas de cada equipo | Entrar al dashboard |
| **Secret de módulo** | El backend del equipo | Publicar eventos |

**Al frontend le importa solo la primera.** La segunda vive en la configuración
del backend de cada equipo y ninguna persona la usa.

```http
POST /api/v1/auth/login
{ "email": "ana@obras.uade.edu.ar", "password": "..." }
```

```json
{
  "accessToken": "eyJ...",
  "tokenType": "Bearer",
  "expiresIn": 900,
  "module": "obras",
  "displayName": "Obras Publicas e Infraestructura",
  "isAdmin": false,
  "kind": "user",
  "actor": "ana@obras.uade.edu.ar"
}
```

La persona queda atada a **un** módulo, y de ahí sale qué datos ve. No hay roles
ni permisos: el único privilegio es `isAdmin`.

**`isAdmin` es la bifurcación principal de la UI.** Solo lo tienen las personas
del módulo `core` (equipo 9):

| | `isAdmin: false` (los 8 equipos) | `isAdmin: true` (equipo 9) |
|---|---|---|
| Dashboard | `GET /dashboard` — solo lo suyo | `GET /dashboard/global` — el hub completo |
| Eventos | solo los que publicó o recibió su módulo | todos |
| DLQ | las que involucran a su módulo | todas, y puede reintentar/descartar |
| Módulos | los ve, no los edita | alta, baja, rotar secrets |
| Cuentas | las de su equipo | las de todos |

El token dura 15 minutos y **no hay refresh**: cuando expira se vuelve a pedir
con `POST /auth/login`. Es un panel interno, así que mandar al login de nuevo es
una salida aceptable.

`GET /api/v1/auth/me` devuelve `{module, displayName, isAdmin, kind, email, name}`
— útil para restaurar la sesión al refrescar la página.

### Errores del login

| Código | `code` | Qué mostrar |
|---|---|---|
| `401` | `INVALID_CREDENTIALS` | "Email o contraseña incorrectos." No dice cuál de los dos, a propósito. |
| `403` | `ACCOUNT_INACTIVE` | La cuenta está desactivada. **Tras 5 intentos fallidos se desactiva sola**; la reactiva cualquier integrante del equipo. |
| `403` | `MODULE_INACTIVE` | El módulo entero está dado de baja. Eso lo arregla el equipo 9. |

---

## 1b. Cuentas del dashboard

Cada equipo administra las de sus integrantes, sin depender del equipo 9.

```http
GET    /api/v1/users                      las de mi equipo (todas si admin)
POST   /api/v1/users                      { email, fullName, password }
PATCH  /api/v1/users/{id}                 { fullName?, active? }
PUT    /api/v1/users/{id}/password        { password }
DELETE /api/v1/users/{id}
```

```json
{
  "id": "...", "email": "ana@obras.uade.edu.ar", "fullName": "Ana Perez",
  "moduleName": "obras", "active": true,
  "lastLoginAt": "2026-09-08T13:00:00Z", "createdAt": "..."
}
```

Dos cosas a tener en cuenta en la UI:

- **No se puede desactivar ni eliminar la única cuenta activa de un equipo** —
  devuelve `409`. Si no, el equipo se queda sin forma de volver a entrar.
  Conviene deshabilitar el botón cuando la lista tiene un solo activo.
- La contraseña necesita **8 caracteres y mezclar letras con números**. Validalo
  en el cliente para no depender del `422`.

## 2. Dashboard de un módulo

```http
GET /api/v1/dashboard?windowHours=24
```

Es la pantalla principal para los 8 equipos:

```json
{
  "module": "obras",
  "windowHours": 24,
  "generatedAt": "2026-09-08T11:12:10Z",

  "published": {
    "total": 142,
    "inWindow": 18,
    "topTypes": [{ "eventType": "workOrderCompleted", "total": 9 }]
  },

  "received": {
    "byStatus": { "DELIVERED": 87, "RETRYING": 2, "DEAD": 1 },
    "total": 90,
    "delivered": 87,
    "pendingRetry": 2,
    "dead": 1
  },

  "deadLetters": {
    "open": 1,
    "byReason": [{ "reasonCode": "DELIVERY_FAILED", "total": 1 }]
  },

  "subscriptions": {
    "total": 10,
    "active": 10,
    "eventTypes": ["ticketCreated", "ticketUpdated", "..."]
  },

  "publications": { "declared": ["workOrderScheduled", "..."] },

  "volumeByHour": [{ "hour": "2026-09-08T10:00:00Z", "total": 12, "rejected": 0 }],
  "processing": { "avgMs": 8.4, "maxMs": 41 }
}
```

**Ideas:** cuatro tarjetas (publicados / recibidos / DLQ abiertas / suscripciones
activas), `volumeByHour` como barras con `rejected` apilado en otro color, y
`received.byStatus` como donut.

`windowHours` acepta 1 a 720; serviría un selector 24h / 7d / 30d.

---

## 3. Dashboard global (solo admin)

```http
GET /api/v1/dashboard/global?windowHours=24
```

Agrega a lo anterior:

```json
{
  "events": {
    "byStatus": { "ROUTED": 210, "NO_SUBSCRIBERS": 4, "REJECTED": 3, "DUPLICATE": 11 },
    "lastHour": 34,
    "perMinuteLastHour": 0.57,
    "bySourceModule": [{ "module": "atencion-ciudadana", "total": 88 }]
  },
  "deliveries": { "byModule": [{ "module": "obras", "status": "DELIVERED", "total": 87 }] },
  "modules": [{ "name": "obras", "active": true, "subscriptions": 10, "lastPublishAt": "..." }],
  "broker": { "connected": true },
  "integrationAlerts": [...]
}
```

Los cuatro estados de `events.byStatus` conviene mostrarlos con su significado,
porque no son obvios:

| Estado | Qué significa |
|---|---|
| `ROUTED` | Entregado a todos sus suscriptores. Lo normal. |
| `NO_SUBSCRIBERS` | Válido, pero nadie lo consume. **No es un error**: es la señal de que falta una suscripción o el nombre no coincide. |
| `REJECTED` | No pasó la validación de estructura. Está en la DLQ. |
| `DUPLICATE` | Reenvío de un `eventId` ya visto. No generó efectos nuevos. |

---

## 4. Alertas de integración

```http
GET /api/v1/dashboard/integration-alerts
```

**Es la pantalla más valiosa del panel.** El Core no valida reglas de negocio,
pero sí ve el mapa completo de quién manda qué y quién escucha qué, así que
detecta solo los agujeros de la integración:

```json
[
  {
    "severity": "warning",
    "kind": "SIMILAR_NAMES",
    "eventType": "debtOverdue",
    "detail": "'debtOverdue' y 'overdueDebt' son sospechosamente parecidos. Si son el mismo evento, los equipos tienen que ponerse de acuerdo en un solo nombre."
  }
]
```

| `kind` | Severidad | Qué significa |
|---|---|---|
| `NO_CONSUMER_DECLARED` | warning | Alguien publica y nadie consume. Cuando se publique, no le llega a nadie. |
| `SIMILAR_NAMES` | warning | Dos tipos casi idénticos: un typo, o el mismo evento con dos nombres. |
| `NO_SUBSCRIBERS` | warning | Ya llegaron eventos de ese tipo y nadie estaba suscripto. |
| `UNDECLARED_TYPE` | info | Un tipo apareció por el hub sin que nadie lo declarara. |
| `NEVER_RECEIVED` | info | Hay suscriptores y productor declarado, pero nunca llegó ninguno. |

Vienen **ordenadas con los `warning` primero**. Los `info` son muchos y conviene
colapsarlos por defecto. Hoy hay 21 warnings y son todos hallazgos reales del
board — están explicados en [desalineaciones.md](desalineaciones.md).

---

## 5. Explorar eventos

```http
GET /api/v1/events?page=1&size=25
    &query=ticket              busca por tipo o módulo origen
    &eventType=ticketCreated
    &sourceModule=obras
    &targetModule=rentas
    &status=ROUTED             ROUTED | NO_SUBSCRIBERS | REJECTED | DUPLICATE
    &correlationId=<uuid>
    &since=2026-09-01T00:00:00Z
    &until=2026-09-08T00:00:00Z
```

Cada fila:

```json
{
  "id": "...", "eventId": "...", "eventType": "ticketCreated",
  "sourceModule": "atencion-ciudadana",
  "occurredAt": "2026-09-08T10:00:00-03:00",
  "receivedAt": "2026-09-08T13:00:01Z",
  "correlationId": "...", "status": "ROUTED",
  "rejectionCode": null, "ingestionChannel": "HTTP",
  "processingMs": 8, "deliveryCount": 4, "deliveredCount": 4
}
```

**`deliveredCount` / `deliveryCount` es el dato clave de la fila**: "4/4" en
verde, "3/4" en ámbar.

`occurredAt` es cuándo pasó en el módulo origen (con su offset original) y
`receivedAt` cuándo lo recibió el Core. Son distintos y vale mostrar los dos.

### Detalle

```http
GET /api/v1/events/{eventId}
```

Agrega el `envelope` completo (mostralo como JSON formateado) y el array
`deliveries`, que es lo que va como tabla:

```json
"deliveries": [
  {
    "targetModule": "obras", "queueName": "q.obras", "status": "DELIVERED",
    "attempts": 1, "maxAttempts": 4, "lastError": null,
    "nextRetryAt": null, "deliveredAt": "2026-09-08T13:00:01Z"
  }
]
```

Estados: `PENDING`, `DELIVERED`, `RETRYING` (mostrá `nextRetryAt`), `DEAD` (agotó
intentos, está en la DLQ), `DISCARDED`.

### Journey

```http
GET /api/v1/events/journey/{correlationId}
```

```json
{
  "correlationId": "...", "eventCount": 7,
  "modulesInvolved": ["atencion-ciudadana", "obras", "transito"],
  "events": [...]
}
```

Los eventos que comparten un `correlationId`, en orden cronológico: es el
recorrido de un trámite entre módulos. Queda muy bien como **timeline vertical**.
En el detalle de un evento, si tiene `correlationId`, poné un link acá.

---

## 6. Suscripciones

Es lo que cada equipo se autoadministra.

```http
GET    /api/v1/subscriptions                             las propias (todas si admin)
POST   /api/v1/subscriptions                             { "eventType": "ticketCreated", "maxAttempts": 4 }
POST   /api/v1/subscriptions/{id}/toggle?active=false    pausar sin borrar
DELETE /api/v1/subscriptions/{id}                        cancelar
```

Al crear una suscripción el Core declara la cola y su binding en el broker en el
acto. **`maxAttempts`** (1–10) son los intentos antes de que el mensaje vaya a la
DLQ.

Se puede suscribir a un tipo que todavía nadie publicó: cuando llegue el primero,
ya tiene destino.

Para el selector de tipos disponibles:

```http
GET /api/v1/event-types?page=1&size=200
```

```json
{
  "name": "ticketCreated",
  "description": "Un vecino presento un reclamo, solicitud o denuncia.",
  "ownerModule": "atencion-ciudadana",
  "discovered": false,
  "validates": true,
  "totalReceived": 142,
  "jsonSchema": { "...": "..." }
}
```

`discovered: true` = apareció solo por el hub sin que nadie lo declarara (va un
badge). `validates: true` = tiene JSON Schema y se le valida el `data`.

### El mapa de integración

```http
GET /api/v1/event-types/map
```

Una fila por tipo con `publishedBy: []` y `consumedBy: []`. Queda muy bien como
**matriz** (tipos en filas, módulos en columnas, íconos distintos para publica y
consume). Las filas donde alguno de los dos arrays está vacío son los agujeros.

---

## 7. DLQ

```http
GET /api/v1/dlq?status=OPEN&reasonCode=DELIVERY_FAILED&page=1
GET /api/v1/dlq/{id}                    detalle + payload crudo + historial
GET /api/v1/dlq/{id}/audit              auditoría de reintentos
```

Acciones (**solo admin**):

```http
POST /api/v1/dlq/{id}/retry
POST /api/v1/dlq/retry-bulk       { "deadLetterIds": [...] }     hasta 200
POST /api/v1/dlq/{id}/discard     { "reason": "..." }             obligatorio
```

Cada fila trae **`retryable`**: si es `false`, deshabilitá el botón de reintentar.
Pasa con `MALFORMED_MESSAGE`, que no tiene sobre válido y solo se puede descartar.

| `reasonCode` | Qué pasó |
|---|---|
| `SCHEMA_VIOLATION` | El `data` no cumple el schema del tipo. `details` trae el campo exacto. |
| `DELIVERY_FAILED` | El módulo destino agotó sus intentos. Reintentar cuando vuelva. |
| `MALFORMED_MESSAGE` | No era JSON válido. No se puede reintentar. |

El detalle trae `details` con forma `[{field, message, constraint}]` — es lo que
le dice al equipo qué corregir, mostralo como lista.

---

## 8. Módulos (admin)

```http
GET   /api/v1/modules                          lista (todos la ven)
POST  /api/v1/modules                          alta → devuelve el secret
PATCH /api/v1/modules/{name}                   editar / dar de baja
POST  /api/v1/modules/{name}/rotate-secret     → devuelve el secret
```

Los dos que devuelven secret responden `{module, secret, warning}`. **El secret se
muestra una sola vez**: va en un modal con botón de copiar y una advertencia
clara, porque el Core solo guarda el hash y no lo puede volver a mostrar.

---

## 9. Topología y salud

```http
GET  /api/v1/topology              exchanges, colas y bindings actuales
POST /api/v1/topology/apply        re-declarar en el broker (admin)
GET  /health/ready                 sin prefijo /api/v1 y sin auth
```

`/health/ready` devuelve `up`, `degraded` o `down`. **`degraded` es base arriba y
broker caído**: la API responde y los eventos esperan en cola sin perderse. No va
en rojo — ámbar con la explicación.

---

## Notas de implementación

**Publicar eventos desde el dashboard es opcional.** El camino real es que el
backend de cada equipo publique con su token de máquina
(`POST /auth/module-token`). Si querés un formulario para probar a mano, el token
de una persona también sirve, y el `sourceModule` tiene que ser el de su módulo.

**El scope de datos lo aplica el backend.** Un módulo que pida
`GET /events?sourceModule=rentas` recibe solo lo suyo igual. No hace falta
filtrar en el cliente por seguridad, pero sí conviene no mostrar controles que
van a dar 403.

**Qué esconder con `isAdmin: false`:** las acciones de DLQ, el alta y edición de
módulos, las cuentas de otros equipos, `POST /topology/apply` y el link al dashboard global. Todo eso responde
403 con un mensaje claro, así que si algo se escapa no rompe nada.

**Las fechas son ISO-8601.** `occurredAt` conserva el offset del módulo origen
(`-03:00`); el resto viene en UTC. Convertir a hora local para mostrar.

**`GET /dashboard` es la llamada más pesada** (varias agregaciones). Un polling de
15–30s alcanza.

**Paginación:** `size` acepta hasta 200; el default de 25 está bien para tablas.
