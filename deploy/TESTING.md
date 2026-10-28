# Arranque aislado para la prueba de testing

## Requisitos

Clonar este backend y ubicarse en la raíz del clon. Tener Git, Python 3.12 o superior y Docker con Compose disponibles en PATH; Docker Desktop debe estar iniciado en Windows. Docker debe usar un motor local. Las imágenes, dependencias y el frontend fijado se descargan por Internet; es necesario acceso a los repositorios y registros correspondientes.

No usar el checkout de AWS para este ensayo. No hacen falta secretos de producción ni un clon manual del frontend. El frontend se obtiene en la revisión `27df1e4636ba1b7df60f23ca14f6b967487c021c`; cambiarla requiere revisar compatibilidad y volver a validar la candidata.

## Un comando desde el clon

Windows:

```powershell
py -3 deploy/testing_up.py
```

Linux/macOS:

```bash
python3 deploy/testing_up.py
```

El comando obtiene una copia privada del frontend, construye la imagen backend, genera configuración nueva con contraseñas aleatorias y clave RSA dentro de un contenedor, valida Compose y levanta PostgreSQL, RabbitMQ, seed, API, worker y frontend. No instala paquetes Python en el host.

El proyecto Compose es `muni-core-testing`, con imágenes específicas de testing y volúmenes propios. La UI queda en `http://localhost:18080`. Solo ese puerto se publica, en loopback. El usuario inicial es `core@muni.uade.edu.ar`; su contraseña es el valor `SEED_INITIAL_PASSWORD` del archivo privado `deploy/.testing/.env`. No copiar ese archivo al informe, a Git o a un canal público.

Para una segunda instalación limpia conservando la primera, usar otro clon y otro proyecto/puerto:

```powershell
py -3 deploy/testing_up.py --project-name muni-core-testing-clean --port 18081
```

Los volúmenes del primer proyecto no se reutilizan. La nueva carpeta debe carecer de configuración previa; el script rechaza credenciales parciales o configuración que no coincida. La existencia de imágenes en caché no equivale a volúmenes existentes: registrar esa condición al evaluar el tiempo. Este ensayo es provisional mientras los cambios estén sin commit y fuera del tag de entrega.

El arranque comprueba `/health/ready` a través de nginx, los cinco servicios persistentes activos y consumidores en `core.inbox` y `q.dlq`. No demuestra todavía un flujo E2E de negocio ni las condiciones de seguridad/rendimiento del TP.

Se escribe evidencia sin credenciales en `deploy/.testing/bootstrap-result.json`: revisiones, fecha UTC, tiempo, proyecto y estado de readiness/consumidores. Indica también si la configuración se generó sin volúmenes previos. El plazo máximo es 15 minutos, incluyendo descargas/build. Si se supera, el comando falla y no acredita G1.

La evidencia incluye `backend_dirty`: si es true, backend_ref es solo el commit base y no identifica por sí solo los cambios ejecutados. Para la entrega definitiva hay que validar el commit/tag completo, sin cambios locales pendientes.

## Reejecución y datos existentes

Una reejecución conserva credenciales y volúmenes. No resetea la base, no rota secretos y no cambia el checkout privado del frontend si tiene modificaciones o una revisión distinta: en esos casos se detiene para revisión.

El script rechaza credenciales parciales, configuración distinta a la esperada, volúmenes existentes sin configuración y motores Docker remotos. No ejecuta `down -v`. Si falla, puede dejar los contenedores de testing activos; no declara éxito ni elimina sus datos. Un lock existente exige verificar que no haya otro bootstrap en ejecución antes de retirarlo.

El script PostgreSQL `postgres-init/10-core-app.sh` crea `core_app` con login, sin superusuario ni administración de roles/bases, y permisos para crear sus tablas en `public`. El bootstrap normaliza sus finales de línea a LF antes de iniciar contenedores; se monta la carpeta `postgres-init` completa, en lugar del archivo individual. La imagen oficial lo ejecuta solo al inicializar un volumen vacío; no cambia roles ni contraseñas de instalaciones existentes. Para un entorno existente que carezca del rol hay que revisar su aprovisionamiento: no borrar volúmenes para resolverlo.

Para detener solo este entorno, desde la raíz del backend:

```bash
docker compose --project-name muni-core-testing --env-file deploy/.testing/.env -f deploy/compose.yaml down
```

Esto conserva los volúmenes. El operador debe revisar el entorno antes de cualquier limpieza de datos de prueba; una reejecución con volúmenes existentes no reemplaza la evidencia de instalación desde cero.

## Verificación de regresiones

```bash
python -m unittest discover -s deploy/tests -v
```

Estas pruebas necesitan `cryptography` (incluido en las dependencias backend), pero no Docker ni red. Cubren generación privada, configuración completa, ausencia de sobrescritura, aislamiento, rechazo de motores remotos, revisión fija del frontend, readiness del worker y límite de tiempo. Son regresiones del bootstrap; no reemplazan la prueba real de instalación PostgreSQL/RabbitMQ en Docker.

Estado de este cambio: pruebas locales preparadas/ejecutadas por separado en la bitácora. G1 permanece pendiente hasta ejecutar el comando sobre un clon y volúmenes nuevos con Docker real y conservar su evidencia. No crear ni mover `v1.0-testing` por este cambio solamente.

## Base técnica

- Inicio por dependencias: https://docs.docker.com/compose/how-tos/startup-order/
- Scripts de inicialización PostgreSQL: https://hub.docker.com/_/postgres
