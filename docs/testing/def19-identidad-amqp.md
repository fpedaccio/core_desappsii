# DEF-19: identidad del publicador por AMQP

Rama `fix/def-19-amqp-identidad`, sobre la candidata `16d1633`. Fecha:
02/11/2026.

## Problema

Por HTTP, el módulo sale del token y se compara con el `sourceModule` del
sobre: si no coinciden, la API responde 403. Por AMQP esa comparación no
existía. El adaptador de RabbitMQ no le pasaba al worker la identidad del
publicador, y el Core aceptaba, persistía y entregaba un evento con cualquier
`sourceModule` (AMQP-06 en T6; reproducido por DevOps sobre `16d1633`).

## Corrección

La única identidad que RabbitMQ autentica es el usuario de la conexión. La
propiedad `user_id` del mensaje la refleja con una garantía: si viene, el
broker rechaza la publicación cuando no coincide con ese usuario. Lo que no
hace es exigir que venga. El Core ahora:

1. Lee `user_id` (`InboundMessage.user_id`, completado por el adaptador
   `RabbitMQBroker`).
2. Lo traduce a un módulo con un vínculo **explícito** (`AMQP_IDENTITIES`).
   No se deduce del nombre del usuario: una cuenta compartida como `core` no
   identifica a ningún módulo.
3. Compara ese módulo con el `sourceModule` declarado, antes de cualquier
   efecto (`app/services/source_identity.py`, usado por
   `app/workers/inbox_worker.py`).

Si no se puede atribuir, en modo `enforce`:

- No se crea el evento ni se entrega a ningún suscriptor.
- Queda una dead letter `SOURCE_UNVERIFIED`, auditable. Sus `details` incluyen
  `IDENTITY_MISSING`, `IDENTITY_UNKNOWN` o `SOURCE_MISMATCH`, el `userId`, el
  módulo autenticado y el origen declarado, y `rawPayload` guarda el sobre. El
  módulo suplantado la ve en su DLQ.
- La dead letter no se puede reintentar (409 y `retryable: false`): aceptarla
  sería aceptar el origen que no se pudo comprobar.
- El `eventId` no queda reservado, así que el publicador legítimo puede
  reenviar el mismo evento con su identidad.

### Configuración

| Variable | Valores | Efecto |
| --- | --- | --- |
| `AMQP_SOURCE_CHECK` | `off`, `warn` (por defecto), `enforce` | `off` no comprueba. `warn` registra `amqp_source_unverified_accepted` en el log y **acepta**. `enforce` rechaza a la DLQ |
| `AMQP_IDENTITIES` | `usuario=modulo,usuario2=modulo2`, o JSON | Vínculo explícito entre usuario AMQP y módulo |

`warn` es el valor por defecto solo para que desplegar este cambio no corte a
los publicadores actuales. **Con `warn`, DEF-19 sigue sin mitigar.**

## Verificación

- **Tests unitarios:** `backend/tests/test_def19_identidad_amqp.py`, 14 casos.
  Cubren la regla, el parseo de la configuración, `enforce` (identidad
  ausente, desconocida y discrepante se rechazan sin entregas y quedan
  auditadas), la visibilidad para el módulo suplantado, el reintento bloqueado,
  el `eventId` no reservado, y `warn` y `off`. Sin el chequeo en el worker
  fallan los 5 casos de rechazo. Suite completa: **270 passed**.
- **Regresión contra RabbitMQ real:**
  [`docs/testing/api/escenarios_def19.py`](api/escenarios_def19.py), en modo
  `enforce`, con PostgreSQL 17 y RabbitMQ 4.3.4.
  - Usuarios de prueba `qa-def19-user-a` y `qa-def19-user-b`: solo `write`
    sobre `muni.inbox`, sin `configure` ni `read`, sin tags.
  - Vinculados a los módulos `qa-def19-mod-a` y `qa-def19-mod-b`. Los nombres
    son distintos a propósito, para probar que el vínculo es explícito.
  - Dos corridas, las dos 8 de 8:

| Caso | Escenario | Esperado | Observado | Resultado |
| --- | --- | --- | --- | --- |
| D19-01 | Usuario A publica como su modulo | aceptado y entregado a B | `(None, 'ROUTED', 1)` | PASS |
| D19-02 | Usuario A declara sourceModule de B | sin evento ni entrega; DLQ SOURCE_UNVERIFIED / SOURCE_MISMATCH | `(None, 0, ('SOURCE_UNVERIFIED', 'SOURCE_MISMATCH'))` | PASS |
| D19-03 | Usuario A publica sin user_id | sin evento ni entrega; DLQ IDENTITY_MISSING | `(None, 0, 'IDENTITY_MISSING')` | PASS |
| D19-04 | Usuario A usa el user_id de B | el broker rechaza la publicacion; sin evento | `('ChannelPreconditionFailed', None, None)` | PASS |
| D19-05 | Reintentar el rechazo por identidad | 409, sigue sin evento | `409` | PASS |
| D19-06 | B ve el intento de suplantacion en su DLQ | dead letter de D19-02 visible para B | `True` | PASS |
| D19-07 | Reenvio legitimo con el eventId de D19-03 | aceptado y entregado una vez | `(None, 'ROUTED', 1)` | PASS |
| D19-08 | Por HTTP, A no puede publicar como B | 403 | `403` | PASS |

D19-04 confirma la garantía de la que depende todo el esquema: el broker cortó
la publicación con un `user_id` ajeno (`ChannelPreconditionFailed`). Los
escenarios de [escenarios_amqp.py](api/escenarios_amqp.py) publican sin
`user_id`, así que valen solo en `warn` u `off`; en `enforce`, el reemplazo es
este script.

### Sobre la integración `342b0b1`

En la revisión integrada (`devops/t8-integracion-pr19-22`), sobre PostgreSQL
17.10 y RabbitMQ 4.3.4:

- Con el worker en `enforce` y los mismos usuarios restringidos, la regresión
  dio 8 de 8 en dos corridas.
- Con el worker en `warn`, los 11 escenarios de `escenarios_amqp.py` pasaron.
  AMQP-06 fue aceptado y el worker registró `amqp_source_unverified_accepted`:
  ese modo no mitiga.
- La suite de pytest de la integración la ejecutó T8 (exit code 0).

## Lo que hay que definir con DevOps

1. **Esquema de identidades.** En el entorno local existe solo el usuario
   `core`, con tag `administrator` y permisos `.*`. Con una cuenta compartida no
   hay forma de distinguir publicadores. Para mitigar DEF-19 hace falta:
   - un usuario AMQP por módulo, con `write` solo sobre `muni.inbox` y `read`
     solo sobre su cola;
   - credenciales no compartidas;
   - ningún usuario de módulo con el tag `impersonator`;
   - el vínculo de cada uno en `AMQP_IDENTITIES`.

   Hay que confirmar cómo se autentican hoy los publicadores reales.
2. **Despliegue.** `deploy/compose.yaml` define las variables de entorno de
   forma explícita, así que hay que agregar `AMQP_SOURCE_CHECK` y
   `AMQP_IDENTITIES` al worker. Es una ruta protegida del CD: lo tiene que
   revisar DevOps. Esta rama no la modifica.
3. **Publicadores.** Cada módulo tiene que enviar `user_id` igual a su usuario
   (en aio-pika, `Message(..., user_id=...)`).
4. **Si se usa `warn` en producción:** aceptación explícita del riesgo, quién la
   aprueba y una fecha concreta para pasar a `enforce`. Mientras se acepten
   publicaciones sin identidad validada, DEF-19 no está mitigado.

## Reproducir la regresión

1. Crear los usuarios restringidos en el vhost de prueba:
   ```bash
   rabbitmqctl add_user qa-def19-user-a '<clave>'
   rabbitmqctl set_permissions -p <vhost> qa-def19-user-a '^$' '^muni\.inbox$' '^$'
   ```
   Lo mismo con `qa-def19-user-b`.
2. Levantar la API y el worker con:
   ```bash
   AMQP_SOURCE_CHECK=enforce
   AMQP_IDENTITIES=qa-def19-user-a=qa-def19-mod-a,qa-def19-user-b=qa-def19-mod-b
   ```
3. Ejecutar `escenarios_def19.py` con las variables de su docstring. Las claves
   se pasan por entorno y no se imprimen.
