# Resiliencia: evidencia local del 28/10/2026

Entorno: `muni-core-testing-clean`, puerto HTTP 18081. Ejecución manual guiada,
con PostgreSQL y RabbitMQ reales. No se modificó AWS. Los informes fueron
aportados en `resiliencia-20261028.zip` y revisados conjuntamente.
La rama local reportó HEAD `e5d8f910cc152ec81c7e770ea972a4a11ead85fc` sin cambios.
Estos informes no incluyen un hash completo del código ejecutado dentro de las
imágenes; no deben presentarse como certificación del tag final ni del CI.

| Caso | Observación | Resultado y alcance |
| --- | --- | --- |
| RES-01 Reconexión | Broker detenido 15 s; regresan consumidores de core.inbox y q.dlq; API y worker conservan ID, inicio y contador de reinicios | Aprobado para detención controlada |
| RES-02 Persistencia | Publicación AMQP persistente confirmada en cola durable exclusiva; reinicio; mismo ID, cuerpo y delivery mode | Aprobado para ese mensaje y reinicio |
| RES-03 Ingesta durante caída | HTTP 202 en 0,05 s con broker detenido; un evento persistido; entrega DELIVERED con dos intentos; mensaje recuperado en cola | Aprobado hasta publicación en la cola |
| RES-04 Duplicados tras recuperación | Reenvío del mismo sobre: HTTP 200, duplicate:true; mismo evento, entrega, intentos y un mensaje; sin consumidores que puedan ocultar duplicados | Aprobado para ese reenvío |

Evento HTTP: `16fd44e2-ca09-4017-a0e1-c34011c08a45`.
El comparador inicial marcó `payload_matches: false`: la única diferencia fue
`occurredAt` de `2026-10-28T18:53:45.027656+00:00` a
`2026-10-28T18:53:45.027656Z`. Representan el mismo instante; `data` permaneció
intacto. Se conservan tanto el resultado original como su explicación.

`DELIVERED` indica publicación al broker, no procesamiento por un consumidor.
No se probaron caída abrupta, partición de red, reinicio de PostgreSQL,
crash entre publicación y commit, carga concurrente, deduplicación del
consumidor ni garantía universal de entrega exactamente una vez. Tampoco se
midió de forma suficiente un objetivo máximo de recuperación automática.
Estos cuatro casos no equivalen al cumplimiento completo del eje de resiliencia.

## Limpieza y trazabilidad

Se retiraron mensaje y cola exclusivos; se desactivaron módulo y suscripción
sintéticos, se eliminó su secreto y el archivo temporal de credenciales.
Se conservan el evento, la entrega y los registros desactivados como auditoría.
No se borraron registros de otros módulos. Un error inicial del guion esperaba
`access_token`; OpenAPI confirmó `accessToken`. Se corrigió el guion y se
recuperó la misma preparación; no fue un defecto de la API.

## Revalidar los informes

Los informes privados se encuentran en `deploy/.testing/evidence/resiliencia`.
No se suben al repositorio, y no son entradas disponibles en los runners del CI.
Desde la raíz del repositorio:

```powershell
py -3 deploy/check_resilience_evidence.py deploy/.testing/evidence/resiliencia
```

El verificador vuelve a comprobar consistencia, identidad, normalización temporal,
conteos y limpieza. No se limita a confiar en el campo `passed` del guion.
No detiene contenedores, no reproduce las pruebas y no debe añadirse al CI como
si ejecutara una caída real. La automatización de nuevas ejecuciones con reportes
propios, restauración garantizada y asociación al SHA de la imagen sigue sin
implementarse; no se declara un nuevo job de resiliencia aprobado.

## Repetición manual

1. Usar un proyecto local aislado, registrar imágenes/código y estado inicial.
2. Crear identificadores únicos y una cola durable de uso exclusivo.
3. Publicar con confirmación, detener únicamente el broker con recuperación en
   `finally`, arrancar y esperar las condiciones de disponibilidad con plazo.
4. Verificar consumidores y mensajes, sin reiniciar API ni worker.
5. Preparar módulo/evento/suscripción sintéticos y autenticar antes de la caída.
6. Detener broker, publicar por HTTP una sola vez con timeout acotado y registrar
   incluso errores o timeouts. Restaurar broker siempre.
7. Consultar por eventId la base y la cola; comparar data e instante de occurredAt.
8. Reenviar el mismo sobre y verificar respuesta y conteos antes/después sin
   consumidor activo. Guardar informes de fallos igual que los exitosos.
9. Limpiar únicamente los recursos identificados y preservar auditoría.

La implementación de un runner que ejecute esta secuencia automáticamente es
un trabajo distinto del verificador de evidencias incluido aquí.
