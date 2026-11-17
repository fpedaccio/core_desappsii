# Candidata integrada de testing ? 02/11/2026

## Versiones y alcance

- Backend probado: `2af90eccf7c8ff83375607bd9d0e97f25d818fc7`.
- Frontend: `d00f07b71aaa61d27adcb179ec5a3180e9e78874`.
- Rama local: `devops/testing-integration-20261102`.
- Incluye backend PR #12 (rendimiento y contadores), #11
  (permisos de DLQ) y #13 (Problem Details).
- Incluye frontend PR #9 y su base.
- Entorno Docker local: `muni-core-testing-integrated`, puerto 18088.
- No acredita despliegue en AWS ni cierre completo del TP.

## Validaciones

Sobre el backend integrado 2af90ec:

- 256 casos de backend aprobados; Ruff y gates de cobertura aprobados.
- 17 casos de integraci?n con PostgreSQL y RabbitMQ aprobados.
- Seis E2E existentes aprobados, sin fallos, errores ni omitidos.
- Un recorrido adicional de navegador aprobado:
  reintento como representante, estado RETRIED, auditor?a MANUAL con su
  email visible en la web y aislamiento frente a un m?dulo ajeno
  (detalle, auditor?a y reintento responden 404).
- El contrato modificado para recuperar la falla pertenece exclusivamente
  a un tipo sint?tico. No se modificaron contratos de m?dulos externos.

Sobre el mismo frontend d00f07b:

- 29 tests aprobados; lint y build aprobados.
- Antes de incorporar backend #13, el operador inform? cinco controles
  manuales satisfactorios: listado y detalle de DLQ, filtro por eventId,
  filtros de estado/fechas y carga de m?tricas con tasa de errores.
- Esos controles manuales no se presentan como repetidos sobre 2af90ec.

## Evidencias locales

Rutas relativas al repositorio; informes fuera de Git:

- `deploy/.testing/evidence/combined-validation-20261102T170721Z/`
  Backend, integraci?n y log del runner de navegador.
- `deploy/.testing/evidence/integrated-frontend-20261102T163003Z/`
  Lint, tests y build del frontend.
- `deploy/.testing/evidence/module-ui-retry-20261102T171800Z/`
  Suite y runner adaptados del recorrido adicional.
- `deploy/.testing/evidence/e2e-20261102-141801-7f861d/`
  Resultado, JUnit y verificaciones del recorrido adicional.

Los runners adaptados se conservaron como evidencia local;
todav?a no constituyen un comando versionado de validaci?n integrada.
Los actores sint?ticos fueron desactivados por la suite;
eventos y auditor?as se conservan como evidencia.

## Pendientes

- Versionar un procedimiento reproducible para validar esta combinaci?n.
- Compartir la candidata y sus evidencias con QA, coordinar cambios
  posteriores y verificar CI del commit que se proponga integrar.
- Consolidar ejecuci?n de HU v2, decisiones y defectos pendientes
  con T2/T3/T6/T7 y G4. Las pruebas t?cnicas no cierran esos bloques.
- Crear el tag de entrega ?nicamente cuando corresponda al cierre acordado.

## Verificaci?n adicional: doble clic

Sobre el mismo c?digo de aplicaci?n, con HEAD documental b56e016,
aprob? el recorrido de doble clic como representante: una sola solicitud
POST de reintento y una sola entrada MANUAL en la auditor?a, con el
email del representante. Tambi?n volvieron a aprobar el reintento,
la visualizaci?n de la auditor?a y el aislamiento del m?dulo ajeno.

Evidencia local:
`deploy/.testing/evidence/e2e-20261102-141951-8cb7f2/`.

La suite ejecutada se conserva en
`deploy/e2e/integrated_dlq_suite.py`.
Ejecuta un caso con varias comprobaciones, no seis casos.
Este archivo requiere el runner de navegador con configuraci?n privada
y red del proyecto integrado; no debe ejecutarse directamente en el host.
La integraci?n de ese runner en un comando versionado sigue pendiente.

## Comandos versionados de la candidata

Desde la ra?z del repositorio, en Windows:

    py -3 deploy/integrated_up.py
    py -3 deploy/integrated_e2e_run.py

El primero construye y levanta el proyecto local
`muni-core-testing-integrated` en el puerto 18088, usando el frontend
fijado en `testing_up.py`. El segundo ejecuta ?nicamente el caso
espec?fico de DLQ con doble clic, auditor?a y aislamiento.
No sustituye las suites de backend, integraci?n ni los seis E2E generales.

El runner comprueba la configuraci?n de arranque, las versiones y los
contenedores; conserva informes y elimina su archivo temporal de
credenciales. No publicar ni adjuntar `deploy/.testing/.env`.

Estos comandos cubren arranque y el recorrido espec?fico de DLQ.
La aceptaci?n de rendimiento y el cierre global de QA son independientes.

## Rendimiento de la candidata integrada: aprobado

Backend: `8d275d667ebb3a8cf418204a8521f39c1e7d78a6`.
Frontend: `d00f07b71aaa61d27adcb179ec5a3180e9e78874`.

Entorno Docker local independiente:
`muni-core-testing-integrated-performance`, puerto 18089,
tres procesos Uvicorn. Carga de 50 usuarios virtuales durante cinco
minutos, con smoke previo y los umbrales originales sin cambios.

| Endpoint | Solicitudes de carga | Errores | p95 |
|---|---:|---:|---:|
| Publicaci?n | 12130 | 0 % | 268,59 ms |
| Historial | 12130 | 0 % | 95,42 ms |
| Dashboard | 12130 | 0 % | 252,87 ms |

Los tres cumplen p95 menor a 500 ms y errores menores al 1 %.

Consistencia verificada por consulta PostgreSQL de solo lectura:
12140 publicaciones esperadas, incluyendo smoke; 12140 eventos
persistidos; 12140 eventId distintos; contador total_received de 12140.
Sin eventos del tipo sint?tico con otro origen.

La suscripci?n sint?tica qued? desactivada, la publicaci?n eliminada
y el m?dulo desactivado. Los eventos y mensajes sint?ticos se conservan.

Evidencia local en el worktree `C:/core-integrated-performance-20261102`:
`deploy/.testing/evidence/performance-20261102-143920-1249b071fcb9/`.
Incluye results.json y consistency-verification.json.
Las invocaciones adaptadas de arranque y carga est?n en:
`deploy/.testing/evidence/integrated-performance-20261102T173826Z/`.

Alcance: escenario local documentado, con un token de m?dulo compartido
y una pausa de un segundo por iteraci?n de tres solicitudes.
No acredita capacidad de producci?n ni procesamiento de consumidores
externos. El entorno integrado habitual de 18088 usa otra configuraci?n;
esta aceptaci?n corresponde espec?ficamente a tres procesos.

## Candidata unificada con cambios del PO

Revisi?n de aplicaci?n validada:
`63a5221367355b6aa4cfe70261e1cb36e2348506`.
Frontend sin cambios: `d00f07b71aaa61d27adcb179ec5a3180e9e78874`.

Se incorporaron los commits bc69ca3 y 4fcfe37 de qa/candidate-t8-t3:

- docs/eventos.md distingue el 422 persistido como REJECTED de los errores
  de validaci?n previos a la persistencia.
- published.topTypes filtra por source_module en el dashboard del m?dulo,
  evitando mostrar eventos consumidos como si fueran publicados.
- Se ampliaron las comprobaciones del dashboard para productor y suscriptor.

Validaci?n posterior al merge:

- Ruff y los 26 casos de tests/test_scope_y_dashboard.py aprobados.
- Entorno integrado reconstruido: arranque en 75,13 segundos.
- Runner versionado de DLQ aprobado: reintento como representante,
  doble clic con un POST y una auditor?a MANUAL, visualizaci?n de auditor?a
  y aislamiento frente a un m?dulo ajeno.
- No se presentan las suites completas locales de la revisi?n anterior
  como repetidas sobre este commit.

### Rendimiento y consistencia de la revisi?n unificada

Entorno local independiente de rendimiento, tres procesos Uvicorn,
50 usuarios virtuales durante cinco minutos, con smoke previo.
Mismo escenario y umbrales que las ejecuciones anteriores.

| Endpoint | Solicitudes de carga | Errores | p95 |
|---|---:|---:|---:|
| Publicaci?n | 11801 | 0 % | 243,97 ms |
| Historial | 11801 | 0 % | 93,04 ms |
| Dashboard | 11801 | 0 % | 271,23 ms |

Los tres endpoints cumplen p95 menor a 500 ms y errores menores al 1 %.

Consulta PostgreSQL de solo lectura: 11810 publicaciones esperadas,
incluyendo smoke; 11810 eventos persistidos; 11810 eventId distintos;
total_received de 11810; cero or?genes inesperados.

Fixture: suscripci?n desactivada, publicaci?n eliminada y m?dulo
desactivado. Eventos y mensajes sint?ticos conservados.

Evidencias locales:

- En C:/core-integration-20261102:
  deploy/.testing/evidence/dashboard-scope-fix-20261102T181612Z/
  y deploy/.testing/evidence/e2e-20261102-152209-c3f966/.
- En C:/core-integrated-performance-20261102:
  deploy/.testing/evidence/performance-20261102-152340-ae4f8e7e9104/
  y deploy/.testing/evidence/unified-performance-20261102T182302Z/.

El resultado anterior de 8d275d6 se conserva como evidencia hist?rica.
Esta secci?n identifica la validaci?n posterior al fix del PO.

### Pendientes de entrega

- CI del commit que se proponga integrar y coordinaci?n del merge.
- Consolidaci?n de evidencias y decisiones de QA con el equipo.
- Actualizar el an?lisis G6 para incluir los commits posteriores al bundle
  inicial; consultar secret-history-review-20261102.md.
- Preparar el tag despu?s del cierre acordado.

No se modific? AWS ni se acredita capacidad de producci?n.
