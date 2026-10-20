# Integración con Core desplegado en AWS

Configuración verificada el 17 de octubre de 2026.
Esta guía reemplaza los datos de alojamiento y conexión de las guías anteriores.

## 1. Solicitar acceso

Informar al equipo Core:
- Nombre del módulo.
- IP pública de salida del backend que se conectará.
- Si esa IP es fija o puede cambiar.

Core debe habilitar esa IP y entregar por privado las credenciales del módulo.
Una conexión desde otra red puede requerir habilitar otra IP.
No compartir credenciales en repositorios, capturas ni canales generales.

## 2. Conexión

| Parámetro | Valor |
|---|---|
| Web y base HTTPS | https://core-uade-2026.duckdns.org |
| Host RabbitMQ | core-uade-2026.duckdns.org |
| Puerto | 5671 |
| Protocolo | AMQPS |
| Virtual host | core |
| Usuario | module_<modulo> |
| Exchange de publicación | muni.inbox |
| Routing key de publicación | Cadena vacía |
| Cola de consumo | q.<modulo> |

Validar la cadena del certificado TLS y el nombre del servidor.
No desactivar esa validación. Usar el dominio, no la IP, como nombre TLS.

Actualmente existe un solo ambiente compartido: vhost core.
No están habilitados ambientes test/prod separados.
Coordinar los eventos de prueba: pueden llegar a otros módulos suscriptos.

## 3. Credenciales diferentes

- Email y contraseña: acceso humano al dashboard.
- Usuario y contraseña RabbitMQ: conexión AMQPS del backend.
- Secret de máquina del módulo: obtención del token para publicar por HTTP.

Estas credenciales no son intercambiables.
No usar el usuario administrador de RabbitMQ en los módulos.

## 4. Publicar por AMQPS

Publicar JSON en muni.inbox con content-type application/json,
mensajes persistentes y publisher confirms. Usar mandatory y manejar
mensajes devueltos por falta de ruta.

No crear ni modificar exchanges, colas o bindings: los administra Core.
Los usuarios de módulo solo pueden publicar en muni.inbox y leer su propia cola.

El confirm del broker acredita la recepción por RabbitMQ; no confirma que
Core haya validado el evento ni que un destinatario lo haya procesado.
Comprobar su estado en Core por eventId.

## 5. Sobre del evento

Enviar:
- eventId: UUID generado una vez por evento lógico; conservarlo al retransmitir.
- eventType: nombre exacto acordado entre los equipos, en inglés y camelCase.
- eventVersion: normalmente "1.0".
- occurredAt: fecha ISO-8601 con zona horaria, por ejemplo terminada en Z.
- sourceModule: nombre propio del módulo registrado en Core.
- data: objeto con los datos acordados para ese tipo de evento.
- correlationId y causationId: cuando correspondan al recorrido del trámite.

No agregar campos propios fuera de data.
Los nombres de módulo registrados conservan su forma actual, por ejemplo
atencion-ciudadana y desarrollo-social.

Advertencia de implementación: el worker AMQP no vincula el usuario RabbitMQ
con sourceModule. Los permisos aíslan las colas, pero no autentican ese campo
del cuerpo. Cada equipo debe declarar su módulo; el control adicional de
identidad queda pendiente de resolución técnica.

Las respuestas HTTP 200/202/403/422 no son respuestas de publicación AMQP.
No asumir que un mensaje inválido se corrige retransmitiendo su eventId:
coordinar con Core según el registro de rechazo y el mecanismo de reproceso.

## 6. Consumir

Consumir únicamente q.<modulo>, con confirmación manual.
No realizar declaraciones activas ni crear bindings.
Puede comprobarse la existencia mediante una declaración pasiva.

- Procesamiento exitoso: confirmar con ack después de guardar el resultado.
- Fallo de procesamiento: rechazar con nack/reject y requeue=false.
- Evitar requeue=true como estrategia automática: puede generar un bucle.

Core correlaciona el rechazo con la entrega y programa el reintento.
Los escalones disponibles son 5s, 30s, 2m y 10m; los utilizados dependen
del número de intento y del máximo configurado para la entrega.
Agotados los intentos, queda un registro para intervención en la DLQ de Core.
El rechazo AMQP por sí solo no transmite un motivo de negocio detallado.

Implementar idempotencia por eventId en el consumidor.
Puede haber duplicados y cambios en el orden de llegada.
Conservar los headers de Core si se implementa alguna republicación acordada.

## 7. Prueba inicial coordinada

1. Core habilita la IP y entrega las credenciales privadas.
2. El módulo comprueba conexión TLS y autenticación.
3. El consumidor se conecta a su cola existente.
4. Se acuerdan emisor, destinatario, tipo de evento y payload de prueba.
5. El emisor publica un evento nuevo y conserva su eventId.
6. Core verifica el registro y el destinatario verifica recepción y procesamiento.
7. El destinatario confirma el mensaje después de procesarlo.
8. Se registra el resultado con eventId, fecha y módulos participantes.

No purgar colas ni consumir mensajes de otros equipos.
No usar los identificadores de pruebas anteriores para una prueba nueva.

Ante un fallo, informar etapa, hora, eventId y error sin contraseñas ni tokens.
