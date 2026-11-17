# Aprobacion local del escenario de rendimiento

## Resultado ejecutado

Escenario mixto de 50 usuarios virtuales durante cinco minutos.
Cada iteracion publica un evento, consulta historial y dashboard,
y espera un segundo. Los usuarios comparten una identidad de modulo.

Umbrales conservados: p95 menor a 500 ms por operacion y tasa de
errores menor al 1 %. Resultado del runner: PASS.

| Operacion | p95 ms | Solicitudes en carga | Errores |
|---|---:|---:|---:|
| publish | 260.17 | 11096 | 0% |
| history | 101.91 | 11096 | 0% |
| dashboard | 350.72 | 11096 | 0% |

Duracion reportada de la fase completa: 302,52 segundos.
Los 11.105 eventos esperados, incluyendo el smoke, coinciden con
los eventos persistidos, sus eventId distintos y total_received.
Se verifico la limpieza de la fixture y la restauracion a un proceso.

## Version y configuracion

Backend reconstruido: 91d8e9416c9229829ba0dad5cfdcca96d97f070c.
Commit de trabajo: b5ae20a230e49f5e8df1e968e5bf3ca7421eb058.
Imagen API: sha256:409bf654db8d9109b1ca65313d12e162b5a5245bb059b3cab80b5e8fb7614fab.

La API se probo con tres procesos Uvicorn y consumidores separados.
RUN_WORKER y SEED_ON_STARTUP estaban desactivados en la API.
El limitador de autenticacion compartido en PostgreSQL se verifico
por separado mediante integracion entre procesos y HTTP real.

deploy/compose.performance.yaml conserva el comando probado.
Es un override para combinar con compose.yaml mediante el bootstrap
aislado, sus variables y su proyecto de rendimiento. No debe usarse
solo ni aplicarse automaticamente a otros ambientes.
performance_up.py incorpora el override exclusivamente al proyecto de
rendimiento. performance_run.py exige el comando de tres procesos y
registra configured_api_workers=3; rechaza una configuracion distinta.

Procedimiento habitual desde la raiz del repositorio:

```powershell
py -3 deploy/performance_up.py
py -3 deploy/performance_run.py
```

El arranque habitual fue verificado en el commit 5dcd13ff7a12ebc596266e95fd42bcf5a9af3322.
La API quedo healthy con el comando de tres procesos; los hashes de
todos los archivos Python de app coinciden entre el contenedor y el
repositorio. Bootstrap ready y worker_consumers aprobaron.
El entorno local quedo con tres procesos. No se repitio la carga.

Evidencia del arranque reproducible:
deploy/.testing/evidence/performance-bootstrap-20261102T112021Z/

## Evidencia y limites

deploy/.testing/evidence/three-process-full-20261102T110955Z/

Se conserva el historial de cargas fallidas. La carga anterior con
dos procesos no aprobo: publicacion tuvo p95 de 520,56 ms.

Esta aprobacion corresponde al escenario y host Docker locales.
No acredita capacidad en AWS, consumo funcional externo ni cierre
completo de G1-G9. Los datos historicos sinteticos se conservaron.
El entorno quedo restaurado a un proceso al finalizar el experimento.
