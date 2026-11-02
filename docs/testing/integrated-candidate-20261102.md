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
- Revisar y, cuando corresponda, repetir la aceptaci?n de rendimiento
  con la configuraci?n de tres procesos sobre la combinaci?n final.
  La carga aprobada anterior no se atribuye a esta nueva combinaci?n.
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
