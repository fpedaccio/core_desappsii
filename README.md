# Módulo Core — Municipalidad UADE

Módulo 9 del TPO de Desarrollo de Aplicaciones II: **identidad, integración, notificaciones y monitoreo**.
Es el HUB de eventos y el proveedor de identidad de los 9 módulos de la plataforma.

**Estado actual:** backend completo y funcionando (70 endpoints, Swagger, datos sembrados). Frontend pendiente.

---

## Arrancar

```bash
cd backend && .venv/bin/uvicorn app.main:app --reload
```

- **Swagger:** http://localhost:8000/docs
- **Admin:** `admin@muni.uade.edu.ar` / `Admin123!`

Si la base no existe todavía:

```bash
cd backend && .venv/bin/python -m app.seeds
```

El seed carga 24 permisos, 6 roles, 5 usuarios, 9 módulos, **101 tipos de evento con su contrato
JSON Schema**, 78 suscripciones, los catálogos globales y 7 reglas de notificación. Es idempotente:
se puede volver a correr. Para empezar de cero: `python -m app.seeds --drop`.

### Usuarios sembrados

Todos con la contraseña `Admin123!`. Sirven para probar que el panel muestra solo las operaciones
del rol autenticado.

| Email | Rol |
|---|---|
| `admin@muni.uade.edu.ar` | ADMIN_SISTEMA (todo) |
| `seguridad@muni.uade.edu.ar` | RESPONSABLE_SEGURIDAD |
| `operador@muni.uade.edu.ar` | OPERADOR_TECNICO (opera la DLQ) |
| `integracion@muni.uade.edu.ar` | RESPONSABLE_INTEGRACION |
| `auditor@muni.uade.edu.ar` | AUDITOR (solo lectura) |

---

## Guion de prueba manual

En Swagger, primero `POST /api/v1/auth/login`, copiá el `accessToken` y pegalo en **Authorize**.

**1. Publicar un evento válido** — `POST /api/v1/events`

```json
{
  "eventId": "11111111-2222-3333-4444-555555555556",
  "eventType": "ReclamoDerivado",
  "eventVersion": "1.0",
  "occurredAt": "2026-08-04T10:30:00-03:00",
  "sourceModule": "atencion-ciudadana",
  "correlationId": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
  "data": { "reclamoId": "RC-2026-00184", "areaDestino": "obras", "prioridad": "ALTA" }
}
```

→ `202` y `routedTo: ["obras","habilitaciones","ambiente","transito","desarrollo-social"]`.
Esas son las suscripciones que el enunciado declara para `ReclamoDerivado`.

**2. Idempotencia** — mandá el mismo JSON otra vez → `200` con `duplicate: true` y **sin** entregas nuevas.

**3. Contrato inválido** — cambiá el `eventId` y dejá `"data": {}` → `422` con `SCHEMA_VIOLATION` y el
campo que falta. El evento **no se pierde**: aparece en `GET /api/v1/dlq`.

**4. Fecha sin zona horaria** — poné `"occurredAt": "2026-08-04T10:30:00"` → `422`. Un timestamp sin
offset es ambiguo entre módulos desplegados por separado, así que se rechaza.

**5. Tipo no registrado** — `"eventType": "EventoInventado"` → `422` con `UNKNOWN_EVENT_TYPE`, y a la DLQ.

**6. Reintento desde la DLQ** — `GET /api/v1/dlq`, tomá el `id` del `UNKNOWN_EVENT_TYPE`, registrá el
tipo con `POST /api/v1/event-types` + su versión, y después `POST /api/v1/dlq/{id}/retry`.
Se reprocesa el evento ya guardado y queda auditado en `GET /api/v1/dlq/{id}/audit`.

**7. Notificación end-to-end** — publicá un `ReclamoResuelto` con `"email": "vecino@example.com"` en
`data`. Mirá `GET /api/v1/notifications` (queda `SENT`, simulado porque no hay SMTP) y después
`GET /api/v1/events/journey/{correlationId}`: vas a ver `ReclamoResuelto` **y** el
`NotificacionEnviada` que el Core publicó en su propio hub.

**8. Provisión de identidad** — publicá un `CiudadanoRegistrado` con
`data: {"ciudadanoId":"CIU-9001","nombreCompleto":"Ana Perez","email":"ana@example.com"}`.
Después `GET /api/v1/users?query=ana`: el Core creó la cuenta con rol `CIUDADANO` y sin contraseña.
El dato personal sigue siendo de Ciudadanos; el Core solo administra la credencial.

**9. Compatibilidad de contratos** — `POST /api/v1/event-types/{id}/compatibility-check` con un schema
que agregue un campo requerido → lo clasifica `FORWARD` y explica qué rompe y en qué dirección.

**10. Permisos por rol** — logueate como `auditor@` y probá `POST /api/v1/dlq/{id}/retry` → `403`
con el detalle de qué permiso falta.

**11. Tableros** — `GET /api/v1/monitoring/dashboard/technical` y `.../communications`.

**12. Catálogo generado** — `GET /api/v1/event-types/catalog.md` devuelve los 101 tipos documentados
con sus schemas. Es el documento que consumen los otros 8 equipos.

---

## Configuración

Todo sale de `backend/.env`. Por defecto arranca en el modo más liviano:

| Variable | Default | Alternativa real |
|---|---|---|
| `DATABASE_URL` | SQLite (`./muni_core.db`) | `postgresql+asyncpg://postgres@localhost:5432/muni_core` |
| `RABBITMQ_URL` | `memory://` (broker en memoria) | `amqp://guest:guest@localhost:5672/` |

El broker en memoria rutea de verdad (exchanges, colas, bindings, comodines), así que el hub se
prueba completo. Lo que no da es persistencia entre reinicios ni consumidores externos.

### Pasar a Postgres + RabbitMQ

Ya están instalados con Homebrew:

```bash
brew services start postgresql@17 && brew services start rabbitmq
```

```bash
/opt/homebrew/opt/postgresql@17/bin/createdb muni_core
```

Después, en `backend/.env`, descomentá las dos líneas de `DATABASE_URL` y `RABBITMQ_URL` reales,
comentá las de SQLite y `memory://`, y volvé a correr `python -m app.seeds`.

Consola de RabbitMQ: http://localhost:15672 (guest/guest) — sirve para ver las colas y la DLQ a ojo.

---

## Arquitectura

Tres capas estrictas en el backend, sin saltos:

```
app/api/v1/       PRESENTACIÓN   routers, DTOs, códigos HTTP, validación de formato
app/services/     NEGOCIO        casos de uso, transiciones de estado, publicación y consumo
app/repositories/ ACCESO DATOS   queries SQLAlchemy, transacciones, mapeo de entidades
app/messaging/    INFRA          broker detrás de una interfaz abstracta (RabbitMQ | memoria)
```

La capa de presentación nunca toca un repositorio y la de negocio nunca importa `Request`.
Los servicios dependen de la interfaz `Broker`, no de `aio-pika`.

### Topología de mensajería

```
publishers ──► muni.inbox ──► core.inbox        (durable: si el Core se cae, nada se pierde)
                                  │
                           [validar contrato + persistir evidencia + rutear]
                                  ▼
                            muni.events (rk = cola destino)
                                  │
                    ┌─────────────┴─────────────┐
                    ▼                           ▼
                 q.obras                  q.core.internal
                    │ el consumidor rechaza
                    ▼
        muni.retry.5s / 30s / 2m / 10m  ──(TTL)──► vuelve a muni.events
                    │ agotados los reintentos
                    ▼
              muni.dlx ──► q.dlq ──► [tabla dead_letters]
```

**La regla que ordena todo el módulo:** el Core no implementa reglas de negocio de las demás áreas.
Valida el sobre y el contrato; nunca interpreta el contenido de `data`. Las notificaciones se
disparan por configuración en `notification_rules`, no con `if eventType == ...` en el código.

---

## Contrato del sobre de eventos

Lo comparten los 9 módulos. Disponible en vivo en `GET /api/v1/events-meta/envelope-schema`.

```json
{
  "eventId":      "uuid",                          // clave de idempotencia
  "eventType":    "ReclamoDerivado",
  "eventVersion": "1.0",
  "occurredAt":   "2026-08-04T12:34:56.789-03:00", // offset OBLIGATORIO
  "sourceModule": "atencion-ciudadana",
  "correlationId": "uuid",                         // opcional, habilita la vista de journey
  "causationId":   "uuid",                         // opcional
  "data": { }                                      // validado contra el JSON Schema de la versión
}
```

### Cómo se conecta un módulo

1. Un admin le crea la cuenta de servicio (`POST /api/v1/api-clients`). El seed ya creó una por módulo.
2. El módulo se autentica con `POST /api/v1/auth/token` (client_credentials).
3. Registra sus tipos de evento y contratos, y se declara productor o consumidor.
4. Publica en `muni.inbox`, o por HTTP con `POST /api/v1/events`.
5. Para validar tokens **no llama al Core**: cachea `GET /.well-known/jwks.json` y valida offline.
   Es lo que hace que una caída del Core no bloquee el acceso a la plataforma.

---

## Pendiente

- Frontend Next.js (panel administrativo con los dos tableros)
- Suite de tests con cobertura ≥85% en BE y FE
- `docs/` completo (arquitectura, integración para los otros equipos) y colección Postman
- Configuración de deploy (Render + Vercel + Neon + CloudAMQP)
