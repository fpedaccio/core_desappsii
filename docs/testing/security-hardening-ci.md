# Validacion del frontend reforzado en CI

El frontend candidato se fija al commit
6353a6dfd3613d17ade5564b96b7e09dfec70573.

Se incorpora a la suite versionada la sexta prueba local de metricas:
autenticacion por UI, vista del modulo, barra de volumen visible con
altura positiva, carga de Inter y JetBrains Mono y ausencia de recursos
externos en la observacion de esa pagina.

La suite, el runner y el workflow requieren seis pruebas exitosas, sin
omisiones. Se conserva la comprobacion de violaciones CSP para cada
caso y se exige una politica sin unsafe-inline ni Google Fonts.
El resultado de metricas y fuentes se publica como artefacto.

La prueba adicional se verifico localmente junto con los cinco casos
anteriores. La evidencia original con codigo final 1 se conserva:
el contador del runner todavia exigia cinco casos aunque los seis tests
habian pasado. Esta version corrige los contadores.

Evidencia local:
deploy/.testing/evidence/hardening-browser-retest-20261031-155748-5a1c6b/
deploy/.testing/evidence/hardening-final-check-20261031-155919-e0e1db/

La ejecucion de CI de este nuevo commit queda pendiente de verificar.
Los resultados locales no sustituyen esa comprobacion ni cierran por
si solos los requisitos G1-G9. No se modifica AWS.

## Actualizacion del candidato de dependencias

El pin incorpora los overrides probados de glob 14.0.2 y minimatch
11.0.1 del frontend. La auditoria local completa informa cinco avisos
bajos, sin moderados, altos ni criticos; produccion informa cero.

El commit anterior del backend, c800ce4, aprobo build, lint, tests,
integracion PostgreSQL/RabbitMQ, bootstrap limpio y seis E2E en CI.
Esa ejecucion utilizo el frontend anterior cfa32de.

Los checks del push del frontend 6353a6d aprobaron lint, tests y build.
La nueva ejecucion E2E con este pin queda pendiente de verificar.
No se reutiliza el resultado anterior como prueba del nuevo candidato.
