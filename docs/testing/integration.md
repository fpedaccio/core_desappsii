# Primera suite con PostgreSQL y RabbitMQ reales

Desde un clon con los cambios aplicados y Docker local iniciado:

```powershell
py -3 deploy/integration_up.py
```

El comando construye una imagen de tests, genera tres contraseñas aleatorias privadas y levanta servicios internos PostgreSQL 17 y RabbitMQ 4. No publica puertos, no usa el servidor AWS ni sus accesos y no monta el socket Docker en el contenedor de pruebas. Proyecto Compose: muni-core-testing-integration. Configuración privada: deploy/.integration/.env. El usuario de base de aplicación es core_app con permisos de creación de sus tablas, no el administrador PostgreSQL.

La suite vive en backend/integration_tests, fuera de backend/tests para no heredar sus fixtures SQLite/FakeBroker. Antes de importar la aplicación comprueba RUN_REAL_INTEGRATION=1 y nombres exactos de los servicios y base dedicados; una invocación accidental con otros endpoints falla. Usa el adaptador RabbitMQ y repositorios reales. Inyecta en los handlers del worker un SessionFactory PostgreSQL real; no simula resultados de SQL ni del broker. Cada caso crea un vhost propio y concede permisos al usuario de pruebas mediante la API del broker dedicado. Así mantiene los nombres reales de las colas de reintento sin colisiones. Al finalizar elimina únicamente su vhost temporal; no borra tablas ni volúmenes.

## Casos comprobados localmente (28/10/2026)

1. Publicación/consumo por RabbitMQBroker, cuerpo y headers observados.
2. Ingesta y lectura posterior desde otra sesión PostgreSQL, tipo JSONB real, fecha con zona, cuerpo y message_id del mensaje persistente.
3. Rollback SQL: una inserción fallida no aparece en otra sesión.
4. Mismo eventId en dos ingestas: una fila de evento, una entrega y un solo mensaje en la cola.
5. Publicación por AMQP al inbox y procesamiento del handler real del worker hasta PostgreSQL y cola destino.
6. Data inválido para el schema: rechazo persistido y DLQ en base, sin entrega al módulo.
7. Consumer que falla: el adaptador hace nack sin requeue, el handler real de DLQ programa el TTL real de 5 s y el segundo fallo con maxAttempts=2 queda como dead letter abierta. Comprueba eventId, intento y auditoría.
8. Sobre AMQP malformado: handler real conserva cuerpo sintético como MALFORMED_MESSAGE y no lo rutea.

La prueba de reintento empieza a consumir después de confirmar la transacción original para aislar ese comportamiento. No cubre todavía el caso de un consumidor que rechaza antes del commit. La publicación del hub ocurre antes del commit de su transacción: es un riesgo observado en código que debe evaluarse con una prueba de atomicidad DB/AMQP y decisión de outbox o compensación. Un rollback de SQL por sí solo no demuestra atomicidad de mensajería.

Tampoco acredita caída/reinicio del broker, recuperación automática después de esa caída, la cadena completa de los cuatro TTL, deduplicación del handler de negocio de otro módulo, TLS, permisos AMQP de cada equipo ni HTTP/UI E2E. Esos escenarios siguen pendientes y no se cuentan como aprobados.

## Evidencia y datos

Se generan deploy/.integration/evidence/integration.xml (JUnit) y run.json (revisión, estado local, fecha, tiempo y código de salida). Se elimina únicamente el XML anterior para evitar confundir evidencia vieja con una ejecución nueva. Los datos son sintéticos. No compartir .env ni credenciales. El runner termina con error si falla un test o falta el reporte; una compilación correcta no significa que las pruebas hayan pasado.

Al terminar se detienen únicamente los contenedores del proyecto de integración y se conservan sus volúmenes. Las dos instalaciones anteriores y AWS permanecen independientes. Una reejecución conserva credenciales; un volumen existente sin su configuración detiene el proceso para revisión. El proceso rechaza Docker remoto y tiene límite de ejecución, más tiempo acotado de limpieza.

Primera ejecución: un caso aprobado y siete errores de preparación por colisión de q.retry.5s entre configuraciones de exchanges. Se corrigió el aislamiento usando un vhost por caso, sin modificar código funcional del Core. Segunda ejecución: **8 passed, 1 warning in 11.63s**, código de salida 0. Ruff sobre integration_tests: **All checks passed**. La advertencia era falta de permiso para escribir la caché de PyTest en /app; se cambia a /tmp/pytest-cache, conservando el usuario no root y las aserciones.

Los ocho casos se informan como suite separada de los 196 tests existentes y las 27 regresiones de herramientas. El job de CI corre en un runner nuevo, comprueba JUnit con al menos ocho casos, sin errores/fallos/omisiones, código de salida 0 y revisión Git exacta sin cambios locales. Publica únicamente integration.xml y run.json. La primera ejecución CI de este cambio está pendiente; los resultados locales no la sustituyen.
