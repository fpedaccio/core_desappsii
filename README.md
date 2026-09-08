# Core — pasamanos de eventos

Módulo 9 del TPO de Desarrollo de Aplicaciones II (UADE). Plataforma municipal
distribuida, 9 módulos independientes.

**Qué hace:** recibe los eventos asincrónicos de los 9 módulos, valida que estén
bien formados, guarda evidencia y los entrega a quien esté suscripto. Cada equipo
entra a un dashboard con su credencial y ve **solo su tráfico**: lo que publicó,
lo que recibió y en qué estado quedó cada entrega.

**Qué no hace:** no administra usuarios ni ciudadanos, no valida reglas de negocio
de las áreas y no interpreta el contenido de los eventos.

---

## Arrancar

```bash
cd backend && .venv/bin/uvicorn app.main:app --reload
```

- **Swagger: http://localhost:8000/docs**
- Login: módulo `core` (es el admin, ve el tráfico de todos)

Si la base está vacía:

```bash
cd backend && .venv/bin/python -m app.seeds
```

El seed carga los 9 módulos y los **73 tipos de evento del board de Miro**, con
sus 71 publicaciones y 78 suscripciones declaradas. Es idempotente y no rota los
secrets ya generados. Para empezar de cero: `python -m app.seeds --drop`.

Los secrets se imprimen la primera vez. Para rotar uno:
`POST /api/v1/modules/{nombre}/rotate-secret`.

### El worker

El servidor de la API sirve el dashboard y la ingesta HTTP. Para consumir de
RabbitMQ hace falta el worker aparte:

```bash
cd backend && .venv/bin/python -m app.workers.inbox_worker
```

Consume `core.inbox` (todo lo que publican los módulos) y `q.dlq` (lo que los
consumidores rechazaron), y reintenta las entregas diferidas.

---

## Documentación

| Documento | Para quién |
|---|---|
| [docs/api-para-el-frontend.md](docs/api-para-el-frontend.md) | **El que hace el dashboard.** Todos los endpoints con ejemplos de respuesta y notas de UI. |
| [docs/eventos.md](docs/eventos.md) | **Los otros 8 equipos.** Cómo publicar, consumir y suscribirse. |
| [docs/desalineaciones.md](docs/desalineaciones.md) | **Todos.** Los 8 puntos donde los nombres de eventos no coinciden entre equipos. |
| `GET /docs` | Swagger completo, navegable. |

---

## Cómo funciona

### Recorrido de un evento

```
publishers ──► muni.inbox ──► core.inbox     (durable: si el Core se cae, nada se pierde)
                                  │
                     [1. ¿eventId repetido? → duplicado, no hace nada
                      2. ¿el sobre está bien formado?
                      3. ¿el tipo declaró schema? → validar el data
                      4. guardar el sobre como evidencia
                      5. buscar suscripciones activas y entregar]
                                  ▼
                            muni.events (routing key = cola destino)
                                  │
                    ┌─────────────┴─────────────┐
                    ▼                           ▼
                 q.obras                    q.rentas
                    │ el consumidor hace nack
                    ▼
        muni.retry.5s / 30s / 2m / 10m ──(TTL)──► vuelve a muni.events
                    │ agotados los 4 intentos
                    ▼
              muni.dlx ──► q.dlq ──► [tabla dead_letters → dashboard]
```

**Por qué `core.inbox` y no un topic compartido:** con el inbox el Core ve todo
antes que nadie, así puede guardar evidencia y decidir el ruteo. Y como la cola es
durable, si el Core está caído los módulos **siguen publicando sin error**: el
broker hace de buffer y al volver el Core drena la cola.

**El backoff sin scheduler:** cada cola de espera tiene un `x-message-ttl` y su
`x-dead-letter-exchange` apunta de vuelta a `muni.events`. El mensaje entra, se
queda quieto lo que dure el TTL, vence, y RabbitMQ lo devuelve conservando su
routing key original — que es la cola destino. No hay ningún proceso durmiendo.

### Tres capas en el backend

```
app/api/v1/        PRESENTACIÓN    routers, DTOs, códigos HTTP
app/services/      NEGOCIO         hub, registry, DLQ, estadísticas
app/repositories/  ACCESO A DATOS  queries SQLAlchemy
app/messaging/     INFRA           broker detrás de una interfaz abstracta
```

Sin saltos de capa: la presentación nunca toca un repositorio y el negocio nunca
importa `Request`. Los servicios dependen de la interfaz `Broker`, no de
`aio-pika`, así el hub corre con RabbitMQ o con un broker en memoria sin cambiar
lógica.

### Dos decisiones que definen el módulo

**1. Un tipo de evento que nadie declaró no se rechaza.** Se registra solo y queda
marcado como `discovered`. Los equipos todavía están alineando nombres, y trabar
la integración por un typo sería peor que dejarlo pasar y mostrarlo en el
dashboard.

**2. La validación del `data` es opcional, por tipo.** Sin JSON Schema el evento
pasa sin que lo miren (pasamanos puro). Con schema se valida la estructura y lo
que no cumple va a la DLQ con el campo exacto. Así cada equipo activa la red de
contención cuando está listo, sin frenar a los demás.

### Lo que el pasamanos sí detecta

No valida reglas de negocio, pero ve el mapa completo de quién publica qué y quién
consume qué. Cruzando esas listas encuentra los agujeros de integración solo:
eventos que alguien publica y nadie escucha, nombres sospechosamente parecidos
(`debtOverdue` vs `overdueDebt`), tipos que aparecieron sin declararse.

`GET /api/v1/dashboard/integration-alerts` — hoy encuentra 21 problemas reales del
board, incluidos dos que no habíamos visto a mano.

---

## Configuración

Todo sale de `backend/.env`.

| Variable | Default | Producción |
|---|---|---|
| `DATABASE_URL` | SQLite (`./muni_core.db`) | `postgresql+asyncpg://...` |
| `RABBITMQ_URL` | `memory://` | `amqp://...` |
| `JWT_PRIVATE_KEY` | se genera efímera | **obligatoria** |

El broker en memoria rutea de verdad (exchanges, colas, bindings, comodines), así
que el hub se prueba completo sin instalar nada. Lo que no da es persistencia
entre reinicios ni consumidores externos.

### Postgres + RabbitMQ

Ya están instalados con Homebrew:

```bash
brew services start postgresql@17 && brew services start rabbitmq
/opt/homebrew/opt/postgresql@17/bin/createdb muni_core
```

Descomentá las dos líneas reales en `backend/.env`, comentá las de SQLite y
`memory://`, y volvé a correr el seed. Consola de RabbitMQ:
http://localhost:15672 (guest/guest).

### Antes de desplegar

- [ ] `JWT_PRIVATE_KEY` configurada — sin ella se genera un par RSA efímero y los
      tokens se invalidan en cada reinicio (en producción el arranque falla).
- [ ] `ENVIRONMENT=production`, `DEBUG=false`
- [ ] `CORS_ORIGINS` con el dominio del dashboard
- [ ] `DATABASE_URL` y `RABBITMQ_URL` a los servicios gestionados

```bash
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out core.key
```

---

## Estado

**Backend completo:** 39 endpoints, 8 tablas, Swagger documentado, verificado
end-to-end (idempotencia, validación de estructura, DLQ con reintento auditado,
scope de datos por módulo, alertas de integración).

**Pendiente:** el dashboard (lo hace otra persona, con
[docs/api-para-el-frontend.md](docs/api-para-el-frontend.md)), la suite de tests y
la configuración de deploy.
