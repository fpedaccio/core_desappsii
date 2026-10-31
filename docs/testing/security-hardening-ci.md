# Validacion del frontend reforzado en CI

El frontend candidato se fija al commit
cfa32debbda11a87efbf2f16125349b88c2a8755.

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
