# Manual de uso — Módulo Core

Plataforma municipal distribuida · Municipalidad de Ciudad UADE
Módulo 9: **identidad, integración, notificaciones y monitoreo**

---

## Índice

**Parte 0 — Entender el Core**
[¿Qué es?](#parte-0--entender-el-core) · [Glosario](#glosario) · [Arquitectura](#arquitectura)

**Parte 1 — Para el equipo 9 (administramos el Core)**
[Puesta en marcha](#1-puesta-en-marcha) · [Roles](#2-roles-quién-hace-qué) ·
[Dar de alta un módulo](#3-dar-de-alta-un-módulo-nuevo) · [Catálogo de eventos](#4-administrar-el-catálogo-de-eventos) ·
[Operar la DLQ](#5-operar-la-dlq) · [Notificaciones](#6-configurar-notificaciones) ·
[Monitoreo](#7-monitoreo) · [Catálogos globales](#8-catálogos-globales) ·
[Usuarios](#9-usuarios-y-accesos) · [Auditoría](#10-auditoría) · [Runbooks](#11-runbooks-de-incidentes)

**Parte 2 — Para los otros 8 equipos**
[Onboarding](#onboarding-en-6-pasos) · [Autenticarse](#autenticarse) · [Publicar](#publicar-un-evento) ·
[Consumir](#consumir-eventos) · [Errores](#errores-y-qué-significan) · [Qué publica y consume cada módulo](#qué-publica-y-consume-cada-módulo)

**Parte 3 — Referencia**
[Endpoints](#referencia-de-endpoints) · [Preguntas frecuentes](#preguntas-frecuentes)

---

# Parte 0 — Entender el Core

## ¿Qué es?

El enunciado reparte la municipalidad en **9 módulos independientes**, cada uno con su frontend,
su backend y su base de datos propia. Eso resuelve la independencia, pero deja tres problemas:

1. Cada módulo necesitaría su propio login → 9 sistemas de usuarios desincronizados.
2. Todos hablan del mismo barrio y de la misma área municipal → 9 tablas de barrios que se pisan.
3. Tienen que mandarse eventos sin acoplarse → si cada uno publica directo a los otros, cambiar
   algo obliga a coordinar 9 deploys.

El Core resuelve esas tres cosas una sola vez, para todos:

| Hace | Concretamente |
|---|---|
| **Identidad** | Único proveedor de identidad. Emite tokens JWT y publica su clave pública para que los demás validen **sin llamarlo**. |
| **HUB de eventos** | Recibe todos los eventos, valida el contrato, guarda evidencia y los entrega a quien esté suscripto. Nadie publica directo a nadie. |
| **Catálogos globales** | Barrios, zonas, dependencias municipales, categorías. Una sola fuente de verdad. |
| **DLQ y reintentos** | Lo que falla no se pierde: se reintenta con backoff y queda en la DLQ para intervención manual auditada. |
| **Notificaciones** | Email e in-app, disparadas por eventos de las otras áreas, configuradas por tabla. |
| **Monitoreo** | Tablero técnico y de comunicaciones, y salud de los 9 módulos. |

### La regla que ordena todo el módulo

> *"El Core no implementará reglas de negocio de las demás áreas."* — enunciado, sección 9

El Core valida **el sobre y el contrato**; nunca interpreta el contenido de `data`. No hay una
sola línea de código que dependa de que un reclamo sea urgente o de que una habilitación esté
aprobada.

Dónde se ve claro: el Core notifica por `ReclamoResuelto` **sin saber nada de reclamos**. La
relación evento → plantilla → destinatario vive en la tabla `notification_rules`, no en el código.
Si mañana Rentas quiere avisar por `PlanPagoIncumplido`, se agrega una fila desde el panel.

**Consecuencia práctica:** si alguna vez estás por escribir un `if eventType == "..."` con lógica
de negocio adentro del Core, la respuesta correcta es una tabla de configuración.

## Glosario

| Término | Qué es |
|---|---|
| **Sobre** (envelope) | La estructura común que envuelve todo evento: `eventId`, `eventType`, `occurredAt`, `sourceModule`, `data`… |
| **Tipo de evento** | Un nombre registrado en el catálogo (`ReclamoDerivado`). Tiene un módulo propietario. |
| **Contrato / versión** | El JSON Schema que describe el `data` de un tipo de evento, en una versión (`1.0`). |
| **Productor** | Declaración de que un módulo publica un tipo de evento. |
| **Suscripción** | Declaración de que un módulo consume un tipo. **Es lo que gobierna el ruteo.** |
| **Entrega** (delivery) | El intento de dejar un evento en la cola de un módulo suscripto. |
| **DLQ** | Dead Letter Queue. Donde va lo que no se pudo procesar tras los reintentos. |
| **Dead letter** | Un registro de la DLQ: el mensaje, el motivo del fallo y su historial de reintentos. |
| **Correlation ID** | Identificador que comparten todos los eventos de una misma *journey*. |
| **Topología** | Los exchanges, colas y bindings de RabbitMQ. El Core la deriva del registry. |
| **JWKS** | El endpoint con la clave pública del Core, para que los módulos validen tokens offline. |

## Arquitectura

### Tres capas en el backend

```
app/api/v1/        PRESENTACIÓN    routers, DTOs, códigos HTTP, validación de formato
app/services/      NEGOCIO         casos de uso, transiciones de estado, publicar y consumir
app/repositories/  ACCESO A DATOS  queries SQLAlchemy, transacciones, mapeo de entidades
app/messaging/     INFRA           broker detrás de una interfaz abstracta
```

Sin saltos de capa: la presentación nunca toca un repositorio y el negocio nunca importa
`Request`. Los servicios dependen de la interfaz `Broker`, no de `aio-pika` — por eso el hub se
puede correr con RabbitMQ o con un broker en memoria sin cambiar una línea de negocio.

### Recorrido de un evento

```
publishers ──► muni.inbox ──► core.inbox        (durable: si el Core se cae, nada se pierde)
                                  │
                           [1. ¿eventId repetido? → duplicado, no se hace nada
                            2. ¿el tipo está en el catálogo?
                            3. ¿el data cumple el JSON Schema?
                            4. guardar el sobre como evidencia
                            5. buscar suscripciones activas y entregar]
                                  ▼
                            muni.events (routing key = cola destino)
                                  │
                    ┌─────────────┴─────────────┐
                    ▼                           ▼
                 q.obras                  q.core.internal
                    │ el consumidor hace nack
                    ▼
        muni.retry.5s / 30s / 2m / 10m ──(TTL)──► vuelve a muni.events
                    │ agotados los 4 intentos
                    ▼
              muni.dlx ──► q.dlq ──► [tabla dead_letters → panel]
```

**Por qué el `core.inbox` y no un topic compartido:** el enunciado pide que el Core *"sea el HUB
de eventos y redireccione según corresponda"*. Con el inbox el Core ve todo y puede validar
contratos y guardar evidencia. Y como la cola es durable, **si el Core está caído los módulos
siguen publicando sin error** — el broker hace de buffer y al volver el Core drena la cola.

**El Core es un módulo más del registry.** Se registró a sí mismo con la cola `q.core.internal` y
se suscribió a los eventos que necesita. No tiene un atajo interno: su propio consumo pasa por el
mismo camino que el de los otros 8.

---

# Parte 1 — Para el equipo 9

## 1. Puesta en marcha

### Levantar en local

```bash
cd backend && .venv/bin/uvicorn app.main:app --reload
```

- Swagger: **http://localhost:8000/docs**
- Admin: `admin@muni.uade.edu.ar` / `Admin123!`

Si la base está vacía:

```bash
cd backend && .venv/bin/python -m app.seeds
```

El seed es **idempotente**: se puede volver a correr cuantas veces quieras. Carga 24 permisos,
6 roles, 5 usuarios, 9 módulos, **101 tipos de evento con su contrato**, 78 suscripciones, los
catálogos globales y 7 reglas de notificación. Para empezar de cero: `python -m app.seeds --drop`.

> Volvé a correr el seed cada vez que agregues un tipo de evento o un permiso al código:
> reconcilia los roles de sistema y agrega lo que falte sin duplicar lo que ya está.

### Los dos modos de ejecución

Todo sale de `backend/.env`:

| | Modo liviano (default) | Modo real |
|---|---|---|
| Base | SQLite (`./muni_core.db`) | `postgresql+asyncpg://postgres@localhost:5432/muni_core` |
| Broker | `memory://` | `amqp://guest:guest@localhost:5672/` |
| Sirve para | Probar la API al instante, sin instalar nada | Demostrar persistencia, consumidores reales, ver colas |

El broker en memoria **rutea de verdad** (exchanges, colas, bindings, comodines de routing key),
así que el hub se prueba completo. Lo que no da es persistencia entre reinicios ni consumidores
externos.

Para pasar al modo real:

```bash
brew services start postgresql@17 && brew services start rabbitmq
/opt/homebrew/opt/postgresql@17/bin/createdb muni_core
# descomentar las dos líneas reales en backend/.env y comentar las de SQLite/memory
cd backend && .venv/bin/python -m app.seeds
```

Consola de RabbitMQ: **http://localhost:15672** (guest/guest) — para ver colas y DLQ a ojo.

### Antes de desplegar

- [ ] Cambiar `SEED_ADMIN_PASSWORD`.
- [ ] **Configurar `JWT_PRIVATE_KEY`.** Sin ella se genera un par RSA efímero y todos los tokens
      se invalidan en cada reinicio. En producción el arranque falla si no está.
- [ ] `ENVIRONMENT=production` y `DEBUG=false`.
- [ ] `CORS_ORIGINS` con el dominio real del frontend.
- [ ] `DATABASE_URL` y `RABBITMQ_URL` apuntando a los servicios gestionados.

Generar el par de claves:

```bash
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out core.key
openssl rsa -in core.key -pubout -out core.pub
```

## 2. Roles: quién hace qué

Los permisos son finos (`recurso:acción`) y los roles los agrupan. Se puede crear un rol nuevo
desde el panel sin tocar código.

| Rol | Permisos | Para qué |
|---|---|---|
| `ADMIN_SISTEMA` | 24 (todos) | Administración total del Core. |
| `RESPONSABLE_SEGURIDAD` | 8 | Usuarios, roles, cuentas de servicio y auditoría. |
| `OPERADOR_TECNICO` | 10 | El día a día del hub: mirar eventos, reintentar y descartar DLQ. |
| `RESPONSABLE_INTEGRACION` | 13 | Módulos, contratos, suscripciones, topología, notificaciones. |
| `AUDITOR` | 11 (solo lectura) | Ve todo, no modifica nada. |
| `CIUDADANO` | 0 | Se provisiona por evento. Sin acceso al panel. |

Usuarios sembrados para probar, todos con `Admin123!`:

```
admin@muni.uade.edu.ar          ADMIN_SISTEMA
seguridad@muni.uade.edu.ar      RESPONSABLE_SEGURIDAD
operador@muni.uade.edu.ar       OPERADOR_TECNICO
integracion@muni.uade.edu.ar    RESPONSABLE_INTEGRACION
auditor@muni.uade.edu.ar        AUDITOR
```

> **Para la defensa:** logueate como `auditor@` e intentá reintentar una dead letter. Devuelve
> `403` con el detalle de qué permiso falta. Eso demuestra "autorización por roles" y
> "mostrar las operaciones disponibles según el rol autenticado".

## 3. Dar de alta un módulo nuevo

El proceso completo, en orden. Los 8 módulos del enunciado ya están dados de alta por el seed;
esto sirve para uno nuevo o para reconstruir el proceso en la defensa.

### Paso 1 — Registrar el módulo

```http
POST /api/v1/registry/modules
```
```json
{
  "name": "obras",
  "displayName": "Obras Públicas e Infraestructura",
  "team": "Equipo 3",
  "healthUrl": "https://obras.onrender.com/health/live",
  "contactEmail": "equipo3@uade.edu.ar"
}
```

El `name` es el identificador técnico en minúscula: es el `sourceModule` de sus eventos y define
su cola (`q.obras`). El `healthUrl` es lo que el Core sondea para el tablero de salud.

### Paso 2 — Crear su cuenta de servicio

```http
POST /api/v1/api-clients
```
```json
{ "clientId": "obras", "moduleName": "obras", "description": "Cuenta de servicio de Obras" }
```

**La respuesta trae el `clientSecret` en claro y es la única vez que se muestra** — el Core solo
guarda su hash. Pasáselo al equipo por un canal seguro. Si se pierde:
`POST /api/v1/api-clients/{id}/rotate-secret`.

### Paso 3 — Registrar sus tipos de evento

```http
POST /api/v1/event-types
{ "name": "OrdenTrabajoCreada", "ownerModule": "obras", "description": "..." }
```

### Paso 4 — Publicar el contrato de cada tipo

```http
POST /api/v1/event-types/{id}/versions
{ "version": "1.0", "jsonSchema": { ... }, "example": { ... }, "publish": true }
```

### Paso 5 — Declarar qué publica y qué consume

```http
POST /api/v1/registry/producers      { "moduleName": "obras", "eventType": "OrdenTrabajoCreada" }
POST /api/v1/registry/subscriptions  { "moduleName": "obras", "eventType": "ReclamoDerivado" }
```

**Al crear la suscripción el Core declara la cola y su binding en el acto**, para que exista antes
de que llegue el primer evento. Si el broker no responde, la suscripción queda igual registrada y
se aplica después con `POST /api/v1/registry/topology/apply`.

### Paso 6 — Verificar

```http
GET /api/v1/registry/topology     # ¿está su cola con sus bindings?
GET /api/v1/monitoring/modules    # ¿el health check lo ve arriba?
```

## 4. Administrar el catálogo de eventos

### Ver qué hay

```http
GET /api/v1/event-types?ownerModule=obras
GET /api/v1/event-types/catalog.md
```

`catalog.md` **se genera** desde las tablas, no se escribe a mano: siempre refleja lo que el hub
realmente valida. Es el documento que se les pasa a los otros equipos.

### Versionar un contrato

**Nunca edites una versión publicada.** Hay eventos en vuelo y en colas que la declaran. Se crea
una versión nueva.

Antes de publicarla, corré el chequeo de compatibilidad:

```http
POST /api/v1/event-types/{id}/compatibility-check
{ "jsonSchema": { ...el schema nuevo... } }
```

| Veredicto | Significa | Cómo desplegar |
|---|---|---|
| `FULL` | Compatible en ambas direcciones. | Cuando quieras, sin coordinar. |
| `BACKWARD` | Un consumidor nuevo lee eventos viejos, pero no al revés. | **Actualizar primero los consumidores.** |
| `FORWARD` | Un consumidor viejo lee eventos nuevos, pero no al revés. | **Drenar las colas antes de desplegar.** |
| `BREAKING` | Rompe las dos direcciones. | Publicarlo como tipo nuevo, o coordinar una ventana. |

Qué rompe qué:

| Cambio | Rompe |
|---|---|
| Agregar un campo **requerido** | BACKWARD (los eventos ya publicados no lo traen) |
| **Quitar** un campo requerido | FORWARD (los consumidores viejos lo esperan siempre) |
| Cambiar el tipo de un campo | las dos |
| Quitar valores de un `enum` | BACKWARD |
| Agregar valores a un `enum` | FORWARD |
| Agregar un campo **opcional** | nada, es seguro |

La clasificación **queda guardada con la versión**: cuando alguien pregunte por qué un consumidor
dejó de entender un evento, la respuesta está escrita.

### Deprecar

```http
POST /api/v1/event-types/versions/{id}/deprecate
```

Deprecar **avisa pero no rompe**: el hub sigue aceptando la versión, porque hay eventos en vuelo
que la declaran.

### Dejar `additionalProperties: true`

Los contratos sembrados lo tienen así a propósito. Permite que un equipo agregue campos a su
`data` sin romper a nadie. Si se cierra, **cualquier campo nuevo se vuelve un cambio incompatible**.

## 5. Operar la DLQ

Esta es la pantalla del operador técnico. La regla de fondo: **nada se borra**. Un mensaje se
reintenta o se descarta con motivo, y las dos cosas quedan auditadas con el usuario que las hizo.

```http
GET /api/v1/dlq?status=OPEN
GET /api/v1/dlq/{id}          # con el payload crudo y el historial de reintentos
```

### Los motivos y cómo se resuelve cada uno

| `reasonCode` | Qué pasó | Cómo se arregla |
|---|---|---|
| `UNKNOWN_EVENT_TYPE` | El tipo no está en el catálogo. | Registrar el tipo + su contrato → **Reintentar**. |
| `UNKNOWN_CONTRACT_VERSION` | El tipo existe pero no esa versión. | Crear la versión → **Reintentar**. |
| `SCHEMA_VIOLATION` | El `data` no cumple el contrato. | Si el schema estaba mal: corregirlo → **Reintentar**. Si el evento estaba mal: **Descartar** y avisar al equipo. |
| `DELIVERY_FAILED` | El módulo destino agotó sus 4 intentos. | Esperar a que vuelva → **Reintentar**. |
| `MALFORMED_MESSAGE` | Ni siquiera era JSON válido. | **No se puede reintentar.** Descartar con motivo y avisar al equipo origen. |

### Los dos caminos del reintento

```http
POST /api/v1/dlq/{id}/retry
```

El Core elige el camino según la causa, no hace falta que lo decidas:

- **Problema de configuración nuestra** (`UNKNOWN_*`, `SCHEMA_VIOLATION`) → **reprocesa el evento
  que ya tiene guardado**. No hay que pedirle al otro equipo que republique nada.
- **Entrega fallida** (`DELIVERY_FAILED`) → **republica** en la cola del módulo destino con el
  contador de intentos reiniciado.

Reintento masivo: `POST /api/v1/dlq/retry-bulk` con hasta 200 ids. Cada uno se procesa y se audita
por separado; un fallo no interrumpe los demás.

### Descartar

```http
POST /api/v1/dlq/{id}/discard
{ "reason": "Evento de prueba del equipo 3, confirmado por Slack el 04/08" }
```

El motivo es **obligatorio** y queda en la auditoría. El registro se conserva siempre.

### Ver la auditoría de un mensaje

```http
GET /api/v1/dlq/{id}/audit
```

Cada intento —automático o manual— con quién lo hizo, cuándo y qué resultado dio. Es
"los reintentos deberán quedar auditados" del enunciado.

## 6. Configurar notificaciones

Tres piezas: **plantilla** (qué dice), **regla** (ante qué evento y a quién), **preferencia**
(opt-out del destinatario).

### Crear una plantilla

```http
POST /api/v1/notifications/templates
```
```json
{
  "code": "PLAN_PAGO_INCUMPLIDO_EMAIL",
  "name": "Plan de pago incumplido",
  "channel": "EMAIL",
  "subjectTemplate": "Tu plan de pago {{ data.planId }} está en incumplimiento",
  "bodyTemplate": "Hola,\n\nEl plan {{ data.planId }} cayó en incumplimiento el {{ occurredAt }}.\n\nMunicipalidad de Ciudad UADE"
}
```

Es Jinja2 con el sobre completo como contexto: `{{ data.campo }}`, `{{ occurredAt }}`,
`{{ sourceModule }}`. La sintaxis **se valida al guardar**, así una plantilla rota no llega al
momento del envío. Previsualizar sin enviar:
`POST /api/v1/notifications/templates/{id}/preview`.

### Crear la regla

```http
POST /api/v1/notifications/rules
```
```json
{
  "eventType": "PlanPagoIncumplido",
  "templateCode": "PLAN_PAGO_INCUMPLIDO_EMAIL",
  "recipientSource": "PAYLOAD_FIELD",
  "recipientExpression": "email"
}
```

Cómo se resuelve el destinatario:

| `recipientSource` | `recipientExpression` | Cuándo usarlo |
|---|---|---|
| `PAYLOAD_FIELD` | Ruta con puntos dentro de `data`: `email`, `ciudadano.contacto.email` | El evento trae el email. Lo más común. |
| `EXTERNAL_USER` | Ruta al id del ciudadano: `ciudadanoId` | El evento trae el id y el email lo tiene el Core, de cuando provisionó la cuenta. |
| `ROLE` | Código de rol: `OPERADOR_TECNICO` | Avisos internos a todos los que tengan ese rol. |
| `FIXED` | La dirección literal | Un buzón fijo. |

### Después de crear una regla, sincronizá

```http
POST /api/v1/registry/core-subscriptions/sync
```

Suscribe al Core al tipo de evento nuevo. **Sin esto la regla no se dispara**, porque el Core no
está recibiendo ese evento. (En el arranque de la aplicación se corre solo.)

### Canales

| Canal | Comportamiento |
|---|---|
| `EMAIL` | SMTP. **Sin `SMTP_HOST` configurado registra el envío como simulado con estado `SENT`** — el flujo se demuestra completo sin servidor de correo. |
| `IN_APP` | La fila de `notifications` es la bandeja. El usuario la lee en `GET /api/v1/notifications/inbox`. |
| `SMS`, `PUSH` | Simulados. Quedan en el historial igual. |

### El Core publica sus propios eventos

Cada envío genera un `NotificacionEnviada` o `NotificacionFallida`, **publicado a través del
propio hub**: se valida contra el catálogo, queda en `event_log` y se rutea a los módulos
suscriptos (2, 4, 6 y 8 los consumen). El Core no tiene atajos para publicar.

Conserva el `correlationId` del evento que originó el aviso, así la journey se lee completa.

> **Cuidado con los ciclos.** Si configurás una regla sobre `NotificacionEnviada`, notificar
> generaría otro `NotificacionEnviada` para siempre. El código corta eso explícitamente
> (`CORE_OWN_EVENTS` en `internal_consumer_service.py`), pero conviene saberlo.

## 7. Monitoreo

### Tablero técnico

```http
GET /api/v1/monitoring/dashboard/technical?windowHours=24
```

Eventos por estado y por minuto, top de tipos, eventos por módulo, tiempos de procesamiento,
entregas por módulo y estado, tamaño de la DLQ por motivo, salud de los 9 módulos, estado del
broker.

### Tablero de comunicaciones

```http
GET /api/v1/monitoring/dashboard/communications?windowHours=24
```

Notificaciones enviadas, fallidas y suprimidas, por canal y por plantilla, con tasa de éxito.

### Salud de los módulos

```http
GET /api/v1/monitoring/modules          # último sondeo de cada uno + disponibilidad 24h
POST /api/v1/monitoring/modules/poll    # forzar un sondeo ahora
```

Un módulo caído se registra como `DOWN`; **no propaga el fallo al Core**. Estados: `UP`,
`DEGRADED` (responde pero tarda más de 2s), `DOWN`, `UNKNOWN` (nunca se sondeó).

### Salud del propio Core

```http
GET /health/live     # el proceso está vivo. No toca base ni broker.
GET /health/ready    # chequea base de datos y broker.
```

`ready` tiene tres estados y la diferencia importa:

| Estado | Significa |
|---|---|
| `up` | Todo en orden. |
| `degraded` | **Base arriba, broker caído.** La API responde y los eventos esperan en `core.inbox` sin perderse. |
| `down` | Sin base de datos. |

Que el broker caído sea `degraded` y no `down` es deliberado: el Core sigue sirviendo consultas.

## 8. Catálogos globales

Los consumen los 9 módulos, así que **las bajas son lógicas** (`active: false`), nunca físicas: si
borraras un barrio, los módulos que lo referencian por id quedarían con una referencia colgada que
el Core no puede reparar.

```http
GET  /api/v1/catalogs/dependencias        # áreas municipales (9 sembradas)
GET  /api/v1/catalogs/zonas               # zonas operativas (5)
GET  /api/v1/catalogs/barrios?zonaId=...  # barrios (10)
GET  /api/v1/catalogs/types               # catálogos genéricos (4)
GET  /api/v1/catalogs/types/{code}/items
```

Los **catálogos genéricos** evitan crear una tabla nueva cada vez que un módulo necesita una lista
de referencia. Sembrados: `CATEGORIA_RECLAMO`, `PRIORIDAD`, `CANAL_ATENCION`, `RUBRO_COMERCIAL`.

Cada item tiene un campo `attributes` libre. Por ejemplo la categoría `INFRAESTRUCTURA` trae
`{"areaDestino": "obras", "slaHoras": 72}`: el Core guarda el dato, el módulo de Atención decide
qué hacer con él. **El Core no aplica el SLA** — eso sería lógica de negocio ajena.

## 9. Usuarios y accesos

```http
GET  /api/v1/users?query=perez&status=ACTIVE&role=OPERADOR_TECNICO
POST /api/v1/users
PATCH /api/v1/users/{id}
PUT  /api/v1/users/{id}/password
GET  /api/v1/roles       POST /api/v1/roles
GET  /api/v1/permissions
```

Detalles que importan:

- **Al pasar un usuario a `INACTIVE` o `BLOCKED` se revocan sus sesiones.** Si no, su refresh
  token seguiría emitiendo access tokens válidos.
- Tras **5 intentos fallidos** consecutivos la cuenta se bloquea sola.
- Los **roles de sistema no se pueden eliminar**: sin `ADMIN_SISTEMA` la plataforma quedaría sin
  forma de administrarse.
- Los refresh tokens **rotan**: usar uno ya usado revoca todas las sesiones del usuario, porque
  indica que se filtró.

### Cuentas provisionadas por evento

El enunciado pide que el ciudadano se registre siempre en el módulo Ciudadanos para después poder
entrar a los demás, pero los usuarios y permisos los administra el Core. Se resuelve así:
Ciudadanos publica `CiudadanoRegistrado` y el Core **provisiona la cuenta de acceso** con rol
`CIUDADANO` y sin contraseña.

El Core guarda solo email, nombre, documento y el `externalId` con el que correlacionar. **El dato
personal sigue siendo de Ciudadanos y el Core nunca lo modifica ahí** (reglas 5 y 8).

Se reconocen en el listado por `sourceModule: "ciudadanos"` y `hasPassword: false`.

## 10. Auditoría

```http
GET /api/v1/audit?actor=admin@muni.uade.edu.ar&action=DLQ_RETRY&since=2026-08-01T00:00:00Z
```

Quién hizo qué sobre qué entidad, con el `traceId` de la operación y el antes/después de los
campos que cambiaron. El rol `AUDITOR` tiene acceso de lectura a todo el módulo.

El `traceId` viaja también en el header `X-Trace-Id` de toda respuesta, y queda en los logs
estructurados y en `event_log`. **Si un equipo reporta un problema, pedile el `traceId`**: con eso
se encuentra su evento y su rastro completo.

## 11. Runbooks de incidentes

### La DLQ se está llenando de un solo tipo de evento

1. `GET /api/v1/dlq?status=OPEN` y mirá el `reasonCode` predominante.
2. Si es `SCHEMA_VIOLATION` de un mismo tipo → el equipo cambió su payload sin versionar el
   contrato. Hablá con ellos, decidan si el contrato tiene que cambiar o el evento estaba mal.
3. Si es `DELIVERY_FAILED` de un mismo módulo → ese módulo está caído. Mirá
   `GET /api/v1/monitoring/modules`. Cuando vuelva, `POST /api/v1/dlq/retry-bulk`.

### Un módulo dice que publica pero no recibe nada su consumidor

1. ¿Llegó el evento? `GET /api/v1/events/by-event-id/{eventId}`.
   - No aparece → no llegó al Core. Que revisen a qué exchange publican y su token.
   - Aparece `REJECTED` → mirá `rejectionReason`. Está en la DLQ.
   - Aparece `NO_SUBSCRIBERS` → **falta la suscripción.** Es la causa más común.
2. ¿Está la suscripción? `GET /api/v1/registry/subscriptions`. Verificá que esté `active` y que
   el módulo también.
3. ¿Existe la cola con su binding? `GET /api/v1/registry/topology`. Si falta,
   `POST /api/v1/registry/topology/apply`.
4. Mirá las entregas del evento: `GET /api/v1/events/{id}` trae el array `deliveries` con el
   estado y el último error de cada una.

### El broker se cayó

No hay que hacer nada urgente. Qué pasa mientras está caído:

- Los módulos **siguen publicando sin error** a `muni.inbox` (cola durable).
- El Core sigue sirviendo la API. `/health/ready` dice `degraded`.
- Los eventos que se ingesten por HTTP se guardan y sus entregas quedan en `RETRYING`.

Cuando vuelve:

```http
POST /api/v1/registry/topology/apply
POST /api/v1/deliveries/process-due-retries
```

El segundo completa las entregas que quedaron pendientes. Nada se perdió.

### Alguien reporta que no puede loguearse tras un deploy

Casi seguro es `JWT_PRIVATE_KEY` sin configurar: se generó un par RSA efímero nuevo y los tokens
anteriores dejaron de validar. Configurala y avisá que vuelvan a loguearse. En producción el
arranque directamente falla para que esto no pase inadvertido.

---

# Parte 2 — Para los otros 8 equipos

> El contrato técnico completo del sobre está en **[event-envelope.md](event-envelope.md)**. Esta
> parte es el resumen operativo.

## Onboarding en 6 pasos

1. **Pedile al equipo 9 tu `clientId` y `clientSecret`.** El secret se muestra una sola vez.
2. **Verificá que tus tipos de evento estén en el catálogo:**
   `GET /api/v1/event-types?ownerModule=obras`. Los 101 del enunciado ya están sembrados.
3. **Registrá los que falten**, con su JSON Schema.
4. **Declarate productor** de lo que publicás y **suscribite** a lo que consumís.
5. **Registrá tu `healthUrl`** así apareces en el tablero de salud.
6. **Probá el flujo completo** con `POST /api/v1/event-types/validate-sample` antes de publicar
   un evento de verdad.

## Autenticarse

```bash
curl -X POST http://localhost:8000/api/v1/auth/token \
  -H "Content-Type: application/json" \
  -d '{"clientId": "obras", "clientSecret": "<tu secret>"}'
```

Devuelve un token de 15 minutos, sin refresh. Cuando expira pedís otro.

### Para validar tokens de usuarios: NO nos llames

Cacheá `GET /.well-known/jwks.json` y validá localmente. RS256, `issuer: muni-core`,
`audience: muni-platform`. Claims útiles: `sub`, `email`, `roles`, `permissions`.

Validar offline es lo que hace que una caída del Core no bloquee el login de la plataforma. Usá
`POST /api/v1/auth/introspect` solo si de verdad necesitás el estado en vivo del token.

## Publicar un evento

**Por AMQP (recomendado):** al exchange `muni.inbox` (fanout, durable), mensaje persistente,
`content-type: application/json`. No hace falta routing key.

**Por HTTP:** `POST /api/v1/events` con el sobre en el body.

Los dos caminos pasan por el mismo pipeline.

### Las 3 reglas que más se equivocan

1. **`occurredAt` necesita offset de zona horaria.** `"2026-08-04T12:34:56-03:00"` ✅ ·
   `"2026-08-04T12:34:56"` ❌ 422. Con 9 módulos desplegados por separado, un timestamp sin
   offset no permite saber qué pasó antes.
2. **`eventId` es UUID nuevo por evento, y guardalo.** Es la clave de idempotencia: si lo
   reenviás, el Core responde `200 duplicate:true` sin volver a rutear.
3. **Propagá el `correlationId`.** Si tu evento sale de consumir otro, copiale el `correlationId`
   y poné su `eventId` en tu `causationId`. Con eso se reconstruye la journey completa — es la
   vista con la que se defiende la entrega final. Si arrancás sin esto, después no se puede
   reconstruir hacia atrás.

## Consumir eventos

Consumís de **tu cola**: `q.<tu-modulo>`. El Core la declara y le hace los bindings de los tipos a
los que estés suscripto.

### Semántica de ack / nack

| Situación | Qué hacer |
|---|---|
| Procesado bien | `ack` |
| Error transitorio (tu DB cayó, timeout) | `nack(requeue=false)` → el Core reintenta 5s → 30s → 2m → 10m, después DLQ |
| Error permanente (el payload no te sirve) | `nack(requeue=false)` → va a la DLQ con el motivo |

**No uses `requeue=true`.** La cadena de reintentos la gobierna el Core; si reencolás, el mensaje
gira en tu cola sin backoff y sin quedar auditado.

### Idempotencia de tu lado también

El Core garantiza no rutear dos veces el mismo `eventId`, pero un `nack` + reintento **sí** puede
entregarte el mismo mensaje otra vez — es *at-least-once*, como cualquier broker. Guardá los
`eventId` que ya aplicaste y salí temprano si repite.

## Errores y qué significan

| Código | Qué pasó | Qué hacer |
|---|---|---|
| `200` `duplicate:true` | Ese `eventId` ya se procesó. | Nada. Es la idempotencia funcionando, no un error. |
| `202` | Aceptado y ruteado. `routedTo` lista a quién llegó. | Nada. |
| `401` | Token vencido o ausente. | Pedir otro. |
| `403` | Falta el scope `events:publish`. | Hablar con el equipo 9. |
| `422 SCHEMA_VIOLATION` | El `data` no cumple el contrato. `details` dice qué campo. | Corregir y reenviar **con el mismo `eventId`**. |
| `422 UNKNOWN_EVENT_TYPE` | El tipo no está en el catálogo. | Registrarlo. El evento quedó en la DLQ, se puede reintentar. |
| `422 VALIDATION_ERROR` | El sobre está mal (casi siempre `occurredAt` sin offset). | Corregir el sobre. |
| `503` | El broker no está disponible. | Reintentar con backoff. |

**Un `422` no significa que se perdió el evento.** Queda guardado en la DLQ del Core con el
motivo, y se puede reprocesar desde el panel una vez corregida la causa.

Todos los errores traen la misma forma, con un `traceId`. **Si algo no cierra, pasale ese
`traceId` al equipo 9.**

## Qué publica y consume cada módulo

Estado sembrado actual: 9 módulos, 101 tipos de evento, 78 suscripciones.

| Módulo | Cola | Suscripciones |
|---|---|---|
| `ciudadanos` (Eq. 1) | `q.ciudadanos` | 9 |
| `atencion-ciudadana` (Eq. 2) | `q.atencion-ciudadana` | 12 |
| `obras` (Eq. 3) | `q.obras` | 8 |
| `habilitaciones` (Eq. 4) | `q.habilitaciones` | 8 |
| `rentas` (Eq. 5) | `q.rentas` | 8 |
| `ambiente` (Eq. 6) | `q.ambiente` | 7 |
| `transito` (Eq. 7) | `q.transito` | 8 |
| `desarrollo-social` (Eq. 8) | `q.desarrollo-social` | 8 |
| `core` (Eq. 9) | `q.core.internal` | 10 |

Los eventos que más cruzan equipos:

| Evento | Publica | Consumen |
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

# Parte 3 — Referencia

## Referencia de endpoints

Swagger completo en `/docs`. Prefijo `/api/v1` salvo donde se indique.

### Autenticación
| | |
|---|---|
| `POST /auth/login` | Login de una persona → access + refresh token |
| `POST /auth/refresh` | Rotar el refresh token |
| `POST /auth/logout` | Cerrar la sesión actual |
| `POST /auth/token` | Token de servicio de un módulo (client_credentials) |
| `POST /auth/introspect` | Validación sincrónica de un token |
| `GET /auth/me` | Roles y permisos del llamador |
| `GET /.well-known/jwks.json` | **Sin prefijo.** Clave pública para validar offline |

### Hub de eventos
| | |
|---|---|
| `POST /events` | Publicar un evento |
| `GET /events` | Explorar la bitácora (filtros por tipo, módulo, estado, fecha, correlación) |
| `GET /events/{id}` | Un evento con sus entregas |
| `GET /events/by-event-id/{eventId}` | Buscar por el `eventId` de negocio |
| `GET /events/journey/{correlationId}` | La journey completa |
| `GET /events/{eventId}/processed-by` | Qué consumidores lo procesaron |
| `GET /events-meta/envelope-schema` | El contrato del sobre |

### DLQ y entregas
| | |
|---|---|
| `GET /dlq` | Listar (filtros por estado, tipo, módulo, motivo) |
| `GET /dlq/{id}` | Detalle con payload crudo e historial |
| `POST /dlq/{id}/retry` | Reintentar |
| `POST /dlq/retry-bulk` | Reintento masivo (hasta 200) |
| `POST /dlq/{id}/discard` | Descartar con motivo obligatorio |
| `GET /dlq/{id}/audit` | Auditoría de reintentos |
| `GET /deliveries` | Entregas por módulo y estado |
| `POST /deliveries/process-due-retries` | Completar reintentos vencidos |

### Catálogo de eventos
| | |
|---|---|
| `GET /event-types` · `POST /event-types` | Listar y registrar tipos |
| `GET /event-types/catalog.md` | Catálogo documentado, generado |
| `GET`/`POST /event-types/{id}/versions` | Versiones de contrato |
| `POST /event-types/{id}/compatibility-check` | Clasificar un schema candidato |
| `POST /event-types/versions/{id}/publish` · `/deprecate` | Publicar / deprecar |
| `POST /event-types/validate-sample` | Probar un payload contra un contrato |

### Registry
| | |
|---|---|
| `GET`/`POST /registry/modules` · `PATCH /registry/modules/{id}` | Módulos |
| `GET`/`POST /registry/producers` · `DELETE .../{id}` | Productores |
| `GET`/`POST /registry/subscriptions` · `PATCH`/`DELETE .../{id}` | Suscripciones |
| `GET /registry/topology` · `POST /registry/topology/apply` | Topología |
| `POST /registry/core-subscriptions/sync` | Sincronizar suscripciones del Core |

### Usuarios y accesos
| | |
|---|---|
| `GET`/`POST /users` · `GET`/`PATCH`/`DELETE /users/{id}` · `PUT /users/{id}/password` | Usuarios |
| `GET`/`POST /roles` · `PATCH`/`DELETE /roles/{id}` | Roles |
| `GET /permissions` | Permisos disponibles |
| `GET`/`POST /api-clients` · `POST /api-clients/{id}/rotate-secret` · `/toggle` | Cuentas de servicio |

### Catálogos globales
`GET`/`POST`/`PATCH` sobre `/catalogs/dependencias`, `/catalogs/zonas`, `/catalogs/barrios`,
`/catalogs/types`, `/catalogs/types/{code}/items`, `/catalogs/items/{id}`

### Notificaciones
| | |
|---|---|
| `GET`/`POST /notifications/templates` · `PATCH .../{id}` · `POST .../{id}/preview` | Plantillas |
| `GET`/`POST /notifications/rules` · `PATCH`/`DELETE .../{id}` | Reglas |
| `PUT /notifications/preferences` · `GET .../{subjectRef}` | Preferencias |
| `GET /notifications` · `GET /notifications/{id}` | Historial |
| `GET /notifications/inbox` · `POST /notifications/{id}/mark-read` | Bandeja in-app |
| `POST /notifications/{id}/retry` | Reintentar un envío fallido |

### Monitoreo
| | |
|---|---|
| `GET /health/live` · `GET /health/ready` | **Sin prefijo.** Probes |
| `GET /monitoring/dashboard/technical` · `/communications` | Tableros |
| `GET /monitoring/modules` · `POST /monitoring/modules/poll` | Salud de los módulos |
| `GET /monitoring/modules/{name}/history` | Histórico de sondeos |
| `GET /audit` | Auditoría |

## Preguntas frecuentes

**¿Por qué el Core rechaza un tipo de evento que no está registrado, en vez de dejarlo pasar?**
Porque sin catálogo tampoco sabría a quién entregárselo: el ruteo se decide leyendo las
suscripciones de ese tipo. Rechazarlo es la única opción correcta. Y no se pierde: queda en la
DLQ y se reprocesa una vez registrado.

**¿Por qué `occurredAt` exige zona horaria?** Con 9 módulos desplegados en servicios distintos, un
timestamp sin offset es ambiguo: no hay forma de saber si el reclamo entró antes o después de la
orden de trabajo. Es la regla 4 del enunciado.

**¿Qué pasa si publico dos veces el mismo evento?** El Core lo detecta por `eventId`, lo marca
como duplicado y **no genera efectos nuevos**. Responde `200` con `duplicate: true`.

**¿Y si el Core se cae?** Los módulos siguen publicando a `muni.inbox` sin error (cola durable) y
los tokens ya emitidos siguen validando contra el JWKS cacheado. Al volver, el Core drena la cola.
No se pierde nada y ningún módulo se bloquea.

**¿Por qué el Core no aplica el SLA de las categorías de reclamo, si lo tiene en el catálogo?**
Porque sería una regla de negocio de Atención Ciudadana. El Core guarda el dato en los atributos
del catálogo; el módulo dueño decide qué hacer con él.

**¿Puedo editar un contrato ya publicado?** No. Hay eventos en vuelo y en colas que declaran esa
versión. Se crea una versión nueva y se corre el chequeo de compatibilidad.

**¿Por qué mi regla de notificación no dispara?** Casi seguro falta
`POST /api/v1/registry/core-subscriptions/sync`: el Core no está suscripto a ese tipo de evento,
así que no lo recibe. Verificá también que la plantilla esté `active`.

**¿Cómo sé si un evento llegó a destino?** `GET /api/v1/events/by-event-id/{eventId}` trae el
array `deliveries`, con el estado, los intentos y el último error de cada módulo destino.

**¿Los emails se mandan de verdad?** Solo si configurás `SMTP_HOST`. Sin eso quedan registrados
como simulados con estado `SENT`, para poder demostrar el flujo completo sin servidor de correo.

**¿Qué diferencia hay entre `NO_SUBSCRIBERS` y `REJECTED`?** `NO_SUBSCRIBERS` es un evento
**válido** que nadie consume todavía: se conserva como evidencia de que el hecho ocurrió, y si
mañana alguien se suscribe queda registrado. `REJECTED` es un evento que no pasó la validación y
está en la DLQ.

---

## Documentos relacionados

| Documento | Para qué |
|---|---|
| [event-envelope.md](event-envelope.md) | Contrato técnico del sobre. **Es el que se les pasa a los otros 8 equipos.** |
| [../README.md](../README.md) | Puesta en marcha y guion de prueba manual de 12 pasos |
| `GET /docs` | Swagger completo, con ejemplos por endpoint |
| `GET /api/v1/event-types/catalog.md` | Catálogo de los 101 tipos de evento con sus schemas |
