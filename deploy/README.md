# Core: preparación guiada del despliegue — 2026-10-12

> Para la instalación aislada de la candidata de testing, usar [TESTING.md](TESTING.md).
> El procedimiento y las evidencias siguientes corresponden a la preparación histórica;
> no acreditan por sí solos el arranque actual desde un clon limpio.

Candidato de preparación, NO desplegado. No hay Docker en el entorno del asistente: imágenes, PostgreSQL y RabbitMQ reales todavía no se ejecutaron. No equivale a certificación de producción.

Bases: backend `f119670211a662fe6901518f5181aad3a424e8d7`; frontend `integracion-con-core`, commit `ee292fd46b9eab8eb03c756a08b35ad942409df5`. Cambios en ramas nuevas, sin modificar las ramas existentes.

## Fases y tareas del usuario

| Fase | Preparado | Tarea del usuario / cierre pendiente |
|---|---|---|
| Alojamiento | Requisitos de los cinco componentes | Confirmar servidor/cuenta, presupuesto y dominio. Elegir proveedor antes de contratar. |
| Versión | Controles de código y prueba HTTP | Probar visualmente login, historial, métricas, suscripciones y permisos; acordar versión con el equipo. |
| Empaquetado | Dockerfiles, nginx y Compose | Construir y levantar con Docker Desktop. |
| Datos/mensajería | Volúmenes, worker y topología existente | Validar PostgreSQL y RabbitMQ reales, evento completo, rechazo y reintento. |
| Producción | Generador de secretos, seed protegido y plantilla HTTPS | Configurar DNS, TLS, usuarios de mínimos privilegios y acceso remoto de equipos. |
| Publicación | Orden y comandos de arranque | Ejecutar en servidor y verificar desde otra computadora. |
| Operación/CD | Procedimiento manual y evidencia | Probar reinicios y restore; configurar CD al elegir alojamiento. |
| Bitácora | Resumen del bloque | Agregar sprint, resultados locales y luego resultados del servidor. |

## Ensayo local en Windows

Es una prueba en tu computadora; no publica Core en internet. Primero comprobar Docker Desktop funcionando, Git y Python. Usar repos nuevos y volúmenes nuevos, sin datos importantes.

Las carpetas deben ser hermanas y llamarse `core-backend` y `core-frontend`. Compose busca el frontend en `../../core-frontend`.

```powershell
cd C:\core-deploy
# Repos creados previamente por PREPARAR_REPOS.py del paquete entregado.
py -m venv .deploy-venv
& .\.deploy-venv\Scripts\python.exe -m pip install cryptography
& .\.deploy-venv\Scripts\python.exe .\core-backend\deploy\prepare_local.py
cd .\core-backend\deploy
docker compose config --quiet
docker compose up -d --build
docker compose ps -a
```

`config --quiet` verifica Compose sin imprimir contraseñas. El servicio `seed` debe finalizar con código 0; API, worker, frontend y ambos servicios deben seguir activos. Si falla, revisar el error antes de repetir.

Abrir `http://localhost:8080`. Cuenta Core: `core@muni.uade.edu.ar`. Contraseña inicial: `SEED_INITIAL_PASSWORD` en `deploy/.env` (abrirlo localmente, NO pegarlo en el chat). Cambiarla desde el panel. Las nueve cuentas iniciales comparten contraseña de bootstrap: antes de dar acceso real, acordar cuentas y contraseñas propias para cada equipo. Reejecutar el seed no cambia cuentas existentes.

```powershell
py .\smoke_http.py --url http://localhost:8080
docker compose logs --tail 80 api worker frontend
docker compose exec rabbitmq rabbitmqctl list_queues -p core name messages_ready messages_unacknowledged consumers
```

El smoke pide contraseña sin mostrarla y comprueba readiness, login, cuenta y dashboard. No verifica UI ni worker. `core.inbox` y `q.dlq` deben tener consumidor: proceso vivo o readiness de la API no prueban consumo del worker.

NO compartir `.env`, `secrets/`, volcados de base ni logs del seed. El seed imprime secrets de máquina una sola vez; conservarlos de forma privada. Los archivos privados se excluyen de Git. El preparador rechaza sobrescribir claves existentes. Cambiar `.env` no cambia contraseñas dentro de volúmenes ya inicializados.

## Validación de eventos

El código ya declara exchanges/colas y contiene worker y reintentos. Los tests usan FakeBroker: falta probar el adaptador RabbitMQ real.

Usar un productor/consumidor de ensayo con eventos y colas propios. No consumir ni purgar mensajes de otros equipos. Comprobar publicación, evidencia, cola destino y recepción; repetir eventId y verificar que no se genere otra entrega; rechazo, backoff, agotamiento y DLQ; reinicio y conservación de datos. NO usar `demo_rabbitmq.py` en un broker compartido: purga colas.

El Compose local no expone PostgreSQL, RabbitMQ ni su panel. La conexión de otros equipos queda pendiente: VPN/túnel o AMQPS con usuarios y permisos por equipo. No compartir el administrador del broker. Para producción usar usuario PostgreSQL con mínimos privilegios: el usuario inicial de esta imagen es administrador y sirve al ensayo, no cierra ese requisito.

## HTTPS con un servidor real

Plantilla: `compose.https.yaml` + `Caddyfile`. Requiere dominio apuntando al servidor y puertos 80/443 accesibles. Añadir `CORE_DOMAIN` a `.env` y cambiar `CORS_ORIGINS` por el origen HTTPS.

```powershell
docker compose -f compose.yaml -f compose.https.yaml config --quiet
docker compose -f compose.yaml -f compose.https.yaml up -d --build
py .\smoke_http.py --url https://DOMINIO_REAL
```

El frontend usa `/api/v1` del mismo origen; nginx conserva esa ruta hacia la API. Caddy termina HTTPS. El puerto 8080 se limita al loopback. Falta configurar la red y el acceso de otros módulos al broker: esta plantilla por sí sola no los habilita.

Las imágenes base están fijadas por etiquetas de versión, no digests. Antes de publicar construir, comprobar disponibilidad y registrar digests. Dependencias Python fijadas para Python 3.12/Linux; npm conserva su lock.

## Respaldo y actualizaciones

Volúmenes NO son un respaldo. El primer esquema usa `create_all`; no se encontró una configuración de migraciones Alembic. Cambios futuros de esquema requieren procedimiento revisado.

Respaldo PostgreSQL sin redirección binaria de PowerShell:

```powershell
mkdir private-logs
docker compose exec -T postgres pg_dump -U core -d muni_core -Fc -f /tmp/core.dump
docker compose cp postgres:/tmp/core.dump .\private-logs\core.dump
```

Probar restauración en una instancia aislada antes de cerrar operación. Respaldar privadamente JWT y configuraciones; acordar recuperación de RabbitMQ según mensajes y tolerancia a pérdidas. NO actualizar con `down -v`: elimina volúmenes.

Actualización por ahora manual, tras pasar CI: conservar commits e imágenes anteriores, respaldar, reconstruir y ejecutar smoke. Volver a una imagen anterior no deshace cambios de base. CD queda pendiente hasta definir servidor, acceso y política de publicación; no desplegar cualquier push de cualquier rama.

## Evidencia comprobada

- Backend: 144 tests existentes PASS y cuatro nuevos controles del seed PASS.
- Backend: Ruff, build de sdist/wheel y pip check PASS.
- Frontend: npm ci, build, ESLint y cuatro tests PASS. Hubo advertencias de peer dependencies/deprecaciones; no se cambió el árbol para silenciarlas.
- Seed dos veces y login/me/dashboard/modules/events/event-types/subscriptions probados por HTTP con proceso real: PASS, usando SQLite y broker en memoria. No valida PostgreSQL/RabbitMQ.
- Generación de credenciales y rechazo de sobrescritura PASS en carpeta temporal, sin secretos en Git.
- YAML parseado: falta validación oficial `docker compose config` y ejecución real.
- Pendientes: contenedores, broker/base reales, UI completa, TLS público, permisos y conectividad entre equipos, restauración y CD. No se contrataron servicios ni se publicó Core.

## Bitácora del bloque

Preparé una configuración de despliegue con API, worker, PostgreSQL, RabbitMQ y frontend. Revisé la rama de integración y ejecuté los controles de ambos repositorios. Detecté una contraseña fija de desarrollo en el seed y agregué controles para impedirla en producción y evitar el borrado del esquema en ese entorno. Dejé pruebas y una guía de ensayo local. La ejecución con contenedores y servicios reales queda pendiente para Docker Desktop; también falta elegir alojamiento y definir acceso de los equipos. No se realizó todavía el despliegue público.

Fuentes oficiales: https://docs.docker.com/compose/how-tos/startup-order/ y https://docs.docker.com/compose/how-tos/use-secrets/ .
