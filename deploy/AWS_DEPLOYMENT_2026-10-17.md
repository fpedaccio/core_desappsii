# Despliegue de Core en AWS — 17/10/2026

## Configuración
- EC2 en us-east-1: Ubuntu Server 24.04, t3.small, CPU Standard.
- Disco gp3 de 20 GiB cifrado.
- Web: https://core-uade-2026.duckdns.org
- Docker Compose: API, worker, frontend, PostgreSQL, RabbitMQ y Caddy.
- Backend base: b694c79. Frontend: e9d5f23.
- PostgreSQL: aplicación con core_app, sin superusuario, creación de bases ni roles.
- PostgreSQL y administración de RabbitMQ sin puertos públicos.
- AMQPS: puerto 5671, certificado público y usuarios separados por módulo.
- Cada usuario de módulo publica en muni.inbox y lee únicamente su cola.
- SSH y AMQPS restringidos actualmente a la IP del responsable.
- HTTP y HTTPS abiertos para la web y validación del certificado.

## Operación
Usar ambos archivos al aplicar la configuración completa:
sudo docker compose -f compose.yaml -f compose.https.yaml up -d --no-build

No ejecutar down -v: elimina los volúmenes.
Las credenciales se conservan fuera de Git, en .env y secrets/.
Las contraseñas web, AMQP y de máquina son credenciales diferentes.

Caddy renueva el certificado web. core-rabbitmq-tls.timer sincroniza
cada hora la copia de RabbitMQ y limpia su caché TLS.
core-duckdns.timer actualiza la IP pública cada cinco minutos.
Los scripts y unidades están en scripts/ y systemd/.
Su instalación actual usa /home/ubuntu/core-deploy/core-backend/deploy.
El token de DuckDNS está en /etc/core-duckdns.token, fuera del repositorio.
La sincronización TLS depende de la ruta actual de certificados de
Let's Encrypt en Caddy; revisar si cambia el dominio o el emisor.

## Evidencia
- Imágenes backend y frontend construidas en EC2.
- Seed terminado con código 0; API saludable.
- Acceso web desde PC y smoke HTTPS: PASS.
- Evento 9cd14722-18b5-45a9-b1f8-1e5b9d787eb5:
  ROUTED, cuatro entregas, recepción y confirmación en Obras.
- Publicación externa con usuario de Obras por TLS: PASS.
- Repetición del identificador: event_duplicate_ignored.
- Acceso de Obras a su cola permitido; acceso a Rentas rechazado,
  tanto por conexión interna como externa.
- Certificado y nombre verificados desde PC; TLS 1.3.
- Reinicio de API y worker: smoke PASS y consumidores recuperados.
- Dump restaurado en base separada: evento y cuatro entregas recuperados.
- Dump descargado a PC: SHA256 coincidente.
- Cuenta Core cambiada manualmente y login comprobado.
- Ocho cuentas web con contraseñas únicas y login comprobado.
- Temporizadores DNS y sincronización TLS: ejecución exitosa y programada.

## Pendientes y límites
- Autorizar IP de salida de cada equipo y entregar credenciales privadas.
- Validar integración real con al menos otro equipo.
- Respaldar configuración, claves, usuarios del broker y base actualizada
  fuera del servidor; definir frecuencia de respaldos y recuperación.
- Comprobar recuperación tras reinicio completo de EC2.
- Revisar consumo bajo carga, espacio en disco y créditos AWS.
- Verificar cómo contabiliza créditos el presupuesto; no es un bloqueo de gasto.
- Incorporar validaciones y corrección de reintentos al flujo del repositorio.
- Actualización y rollback siguen siendo manuales; CD pendiente.
- Los permisos AMQP no vinculan el usuario con sourceModule del mensaje.
- La restauración probada fue en otra base del mismo servidor, no una
  recuperación completa en un servidor nuevo.
- Las tareas automáticas se probaron con el certificado e IP actuales;
  no se simuló una renovación real ni un cambio de IP.

El README de preparación describe el estado previo. Este registro añade
la evidencia posterior de AWS y no equivale a cerrar los pendientes.

## Verificaciones posteriores y respaldo automático

- Reinicio completo de EC2: los servicios arrancaron automáticamente.
- HTTPS, login y dashboard: PASS después del reinicio.
- Worker: consumidores activos en core.inbox y q.dlq.
- PostgreSQL: evento de prueba conservado en estado ROUTED con cuatro entregas.
- Mensajes de prueba pendientes conservados en RabbitMQ.
- Respaldo privado descargado a Windows y SHA-256 coincidente.

Respaldo PostgreSQL mediante core-backup-postgres.timer, diariamente a
las 06:00 UTC (03:00 Argentina). Destino: /var/backups/core, acceso root.
Incluye database.dump y globals.sql. Se verifica que el dump pueda listarse.
La limpieza elimina carpetas con más de siete días completos según find.

Primera ejecución manual: exitosa. La ejecución diaria desatendida y la
restauración de este nuevo respaldo automático siguen pendientes.
Las copias locales no protegen frente a la pérdida del servidor.
No incluyen los mensajes pendientes de RabbitMQ ni reemplazan el respaldo
privado de configuración y claves fuera de EC2.

### Resultado de restauración del respaldo automático
Restauración manual del primer database.dump automático: PASS, en la base
separada muni_core_auto_restore_check. Evento de prueba recuperado en estado
ROUTED con cuatro entregas. Esto cierra la restauración del dump indicada
como pendiente arriba; no prueba globals.sql ni recuperación en otro servidor.
La primera ejecución diaria desatendida sigue pendiente.

## Mantenimiento y límites de logs

Ubuntu actualizado; kernel activo verificado: 7.0.0-1014-aws.
Después del reinicio: smoke HTTPS PASS, tres temporizadores activos,
ninguna unidad systemd fallida y consumidores en core.inbox y q.dlq.

Rotación Docker configurada por servicio: json-file, max-size 10m,
max-file 3. Aplicada mediante recreación de contenedores, conservando
volúmenes y realizando antes un respaldo PostgreSQL.
Opciones verificadas mediante docker inspect; smoke posterior PASS.
Este límite cubre stdout/stderr de Docker, no todos los archivos del servidor.
