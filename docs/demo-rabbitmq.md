# Demo de RabbitMQ — guion

## Preparar (30 segundos antes)

```bash
brew services start rabbitmq
cd backend && .venv/bin/python -m app.seeds
```

Abrí **http://localhost:15672** (guest / guest) en una pestaña, y la terminal al
lado. La gracia es mirar las dos cosas a la vez: la terminal narra, la consola
muestra los contadores moviéndose.

```bash
cd backend && .venv/bin/python demo_rabbitmq.py
```

Se frena en cada acto esperando Enter. Con `--auto` corre sola (sirve para
ensayar). Podés correrla las veces que quieras: purga las colas al arrancar, así
los números siempre dan lo mismo.

---

## Acto 1 — La topología

**Qué mostrar:** pestaña **Exchanges**, después **Queues**.

> "Estos 7 exchanges y 15 colas no están escritos a mano en ningún lado. El Core
> los deriva de la tabla de suscripciones: hay 9 colas de módulo porque hay 9
> equipos suscriptos. Si mañana alguien se suscribe a un evento nuevo, la cola y
> el binding aparecen solos."

Los cuatro que importan:

| Exchange | Para qué |
|---|---|
| `muni.inbox` (fanout) | Acá publican los 9 módulos. No saben quién recibe. |
| `muni.events` (topic) | Acá rutea el Core. La routing key es el nombre de la cola destino. |
| `muni.retry.*` | Los escalones de backoff. |
| `muni.dlx` | Lo que agotó los reintentos. |

---

## Acto 2 — Publicar y rutear

**Qué mostrar:** `core.inbox` pasa a 1, después las 4 colas de módulo pasan a 1.

> "Atención Ciudadana publica un `ticketCreated` en `muni.inbox`. Fijate que el
> que publica **no sabe quién lo va a recibir** — no elige destino.
>
> El mensaje queda esperando en `core.inbox`. Ahora el Core lo consume, busca en
> la base quién está suscripto a `ticketCreated`, y publica una copia en
> `muni.events` por cada destino, con la routing key igual al nombre de la cola."

**El punto:** el ruteo lo decide el Core leyendo la base, no un patrón de routing
key. Por eso puede registrar una fila de entrega por destino y después responder
"¿le llegó a Obras?".

---

## Acto 3 — Idempotencia

**Qué mostrar:** los contadores de las colas de módulo **no se mueven**.

> "Se republica exactamente el mismo evento, con el mismo `eventId`. El mensaje
> entra al broker igual — RabbitMQ no sabe nada de duplicados. Pero el Core ve
> que ese `eventId` ya está en su bitácora, lo marca `DUPLICATE` y no genera
> ninguna entrega nueva.
>
> Por eso un módulo puede reintentar sin miedo a duplicar efectos."

---

## Acto 4 — Backoff y DLQ ⭐

Es el más interesante. **Qué mostrar:** `q.dlq` sube a 1, después `q.retry.5s`
sube a 1, y **a los 5 segundos vuelve solo a la cola del módulo**.

> "El consumidor rechaza el mensaje con `nack(requeue=false)`. RabbitMQ lo manda
> al exchange que la cola declara en `x-dead-letter-exchange`, que es `muni.dlx`.
>
> El Core lo lee, ve que todavía le quedan intentos, y lo publica en la cola de
> espera de 5 segundos."

Y acá viene lo que conviene remarcar:

> "Miren `q.retry.5s`. Esa cola tiene dos argumentos: un `x-message-ttl` de 5
> segundos, y su `x-dead-letter-exchange` apunta **de vuelta** a `muni.events`.
>
> Entonces el mensaje entra, se queda quieto los 5 segundos, vence el TTL, y
> RabbitMQ lo dead-letterea conservando su routing key original — que es la cola
> del módulo. Vuelve solo.
>
> **No hay ningún proceso durmiendo ni ningún scheduler.** El backoff lo hace el
> TTL de la cola. Hay una cola por escalón (5s, 30s, 2m, 10m) en vez de una sola,
> porque las colas AMQP son FIFO: con una sola, un mensaje esperando 10 minutos
> en la cabeza bloquearía a los que esperan 5 segundos detrás."

En la consola de RabbitMQ, si hacés click en `q.retry.5s` → **Arguments**, se ven
los dos argumentos. Vale mostrarlo.

---

## Acto 5 — Durabilidad

**Qué mostrar:** los 3 publish funcionan con el Core apagado, y `core.inbox` se
va llenando.

> "Acá el Core está apagado: nadie consume `core.inbox`. Se publican 3 eventos y
> los tres publish funcionan sin error — el módulo que publica **ni se entera**
> de que el Core está caído, y no se bloquea.
>
> La cola es durable y los mensajes son persistentes, así que sobreviven incluso
> a un reinicio del broker. Cuando el Core vuelve, drena la cola."

El cierre verifica en la base que los 3 quedaron guardados.

> "Esta es la razón de que los módulos publiquen a `muni.inbox` y no directo a
> las colas de destino: el broker hace de buffer. Si el Core se cae, la
> plataforma sigue funcionando y no se pierde un solo evento."

---

## Si preguntan

**"¿Por qué el Core en el medio y no que cada uno publique a quien le toca?"**
Porque entonces cada módulo tendría que saber quién consume lo suyo, y cambiar un
consumidor obligaría a redeployar a los productores. Con el hub en el medio, el
que publica no sabe ni le importa quién recibe: se cambia una fila en la tabla de
suscripciones. Y de paso el Core puede guardar evidencia de todo lo que pasó.

**"¿Qué pasa si el mensaje se pierde entre el Core y el módulo?"**
No se pierde: el publish va con confirmación del broker, los mensajes son
persistentes y las colas durables. Si el consumidor falla, hay 4 reintentos con
backoff y después la DLQ, donde un operador lo ve y lo reintenta a mano.

**"¿Y si RabbitMQ se cae entero?"**
El Core sigue sirviendo la API y `/health/ready` reporta `degraded` en vez de
`down`. Los eventos que entran por HTTP quedan persistidos con su entrega en
estado `RETRYING`, y cuando el broker vuelve se completan solas.

**"¿Por qué la routing key es el nombre de la cola?"**
Para que el ruteo sea explícito y auditable. Si bindeáramos por tipo de evento,
el que decide sería el patrón del binding y el Core no tendría registro de a
quién le entregó ni cuántos intentos llevaba cada destino.

---

## Volver al modo liviano

La demo necesita `RABBITMQ_URL=amqp://...` en `backend/.env`. Para volver al
broker en memoria (arranca sin instalar nada, pero sin consola ni persistencia),
comentá esa línea y descomentá `RABBITMQ_URL=memory://`.
