# Estado tecnico de las verificaciones de seguridad

## Uso y alcance

Este documento consolida evidencia tecnica para el informe del TP.
No reemplaza la matriz oficial de la consigna, la trazabilidad con HU,
la gestion de defectos ni la revision de G1-G9.

Los resultados son del entorno local salvo indicacion expresa.
Verificado significa observado dentro del alcance indicado; no implica
cumplimiento integral ni despliegue en AWS.
Los pendientes no se consideran riesgos aceptados automaticamente.

## Matriz de resultados

| Control | Resultado dentro del alcance | Evidencia y limite |
| --- | --- | --- |
| Acceso sin token | Verificado: cinco rutas respondieron 401 | security-http.md; no cubre cada endpoint |
| Tokens invalidos o falsificados | Verificado en los casos ejecutados | security-http.md |
| Expiracion, issuer y audience | Verificado con tokens firmados de prueba | security-http.md |
| Aislamiento entre modulos y operaciones administrativas | Verificado en nueve comprobaciones | security-http.md; no equivale a todos los objetos y operaciones |
| Asignacion de privilegios desde el cuerpo | Verificado en nueve comprobaciones | security-http.md |
| Intentos de autenticacion | Bloqueo de cuenta previamente observado y limitador local 429 verificado en login y module-token | auth-rate-limit.md; contador por identidad y endpoint, por proceso; no acredita proteccion distribuida o integral |
| CORS | Origen local permitido y externo rechazado en preflight | security-headers.md; alcance limitado a origenes y solicitudes probados |
| CSP restrictiva y fuentes locales | Verificado en candidato cfa32de y seis escenarios locales | Evidencia hardening-final-check; sin unsafe-inline y sin fuentes externas |
| Fuentes y metricas | Ambas familias cargadas, barra con altura positiva y sin recursos externos observados | No sustituye revision visual integral o accesibilidad |
| HSTS | Verificado en proxy HTTPS local temporal | security-headers.md; no acredita despliegue del candidato en AWS |
| Nosniff y proteccion de frames | Verificado localmente | Cabeceras y escenarios de navegador |
| CORP y Permissions Policy | Verificado en raiz y API 401 del candidato | No cubre todos los tipos de respuesta ni integraciones cross-origin |
| Version de Nginx | Version ocultada en candidato | Server sigue identificando nginx |
| COEP y COOP | Pendientes de tratamiento | Baseline final: dos alertas bajas |
| Baseline ZAP | Informe final sin altos ni medios | Dos bajos y tres informativos; escaneo pasivo de alcance limitado |
| ZAP activo autenticado | Completado con autenticacion antes y despues; defecto 500 corregido | Ocho GET importados, politica API-Minimal y tiempo acotado; frontend anterior al ultimo refuerzo |
| Caracteres nulos en filtros | Corregido y verificado localmente | 205 tests, 19 comprobaciones HTTP y reescaneo; seis filtros concretos |
| HTML en sondas de metadatos | Respuestas comprobadas iguales al HTML del frontend | No demuestra metadatos expuestos ni acredita proteccion general contra SSRF |
| Inyecciones y XSS | Cobertura parcial; pendiente completar alcance | El escaneo API-Minimal no reemplaza pruebas de todos los campos ni XSS de navegador |
| Dependencias Python | Auditoria previa corregida y documentada | dependencies.md; requiere consolidar estado del candidato final |
| Dependencias frontend de produccion | Cero hallazgos en auditoria final ejecutada | frontend-targeted-dev-fix; no cubre paquetes del sistema operativo |
| Dependencias frontend de desarrollo | Moderados eliminados con overrides probados; cinco bajos restantes | glob/minimatch corregidos; aviso deepmerge y propagacion en Jest pendientes |
| Historial Git y secretos | Auditoria historica previa documentada, pendiente refrescar para candidato final | No afirmar que cubre commits posteriores |
| Logs y datos sensibles | Filtro probado y censura verificada con login sintetico en API reconstruida | log-redaction.md; pendiente ampliar revision a otros caminos y logs fuera de structlog |
| Cuenta original de ZAP | Desactivacion y retirada de credenciales verificadas | Cola e informes privados conservados; no acredita revocacion inmediata de JWT |
| Fixtures E2E | La suite desactiva modulos sinteticos al finalizar | No equivale a borrado integral de usuarios, colas o registros historicos |

## Versiones y CI

Candidato de codigo verificado:
- Backend: 9adafb0b32a1f15c1b0705c250810d4a5fe423e2.
- Frontend fijado: 6353a6dfd3613d17ade5564b96b7e09dfec70573.

Los checks del backend aprobaron en push y PR:
build, Ruff, PyTest, integracion PostgreSQL/RabbitMQ, bootstrap limpio
y seis escenarios reales de navegador. CD quedo omitido.

Ejecuciones del PR:
- https://github.com/fpedaccio/core_desappsii/actions/runs/41236572733
- https://github.com/fpedaccio/core_desappsii/actions/runs/41236572861

Ejecuciones del push:
- https://github.com/fpedaccio/core_desappsii/actions/runs/41236310298
- https://github.com/fpedaccio/core_desappsii/actions/runs/41236310261

El frontend 6353a6d tambien aprobo lint, tests y build en push y PR.

La verificacion corresponde a estos commits. No acredita merge en main,
tag final, despliegue AWS ni tres ejecuciones consecutivas sobre una
misma referencia final.

## Evidencias y conservacion

Los informes locales estan bajo deploy/.testing/evidence, fuera de Git.
El indice local de este checkpoint registra rutas, tamanos y SHA-256
de once informes seleccionados. Los hashes permiten comprobar integridad;
no constituyen por si solos una firma ni prueban autenticidad.

Los originales de ZAP permanecen privados porque pueden contener tokens.
No se adjuntan archivos .env, claves privadas ni configuraciones de acceso.

## Siguiente cierre

- Confirmar CI del pin final y registrar enlaces de ejecucion.
- Tratar COEP/COOP y el aviso bajo de deepmerge segun riesgo y compatibilidad.
- Completar las verificaciones pendientes de seguridad de la consigna.
- Refrescar auditorias del candidato final cuando corresponda.
- Integrar resultados, limitaciones y defectos en la matriz oficial,
  Jira y documento de entrega, con responsables y evidencia.
- Verificar por separado cada requisito G1-G9; este bloque no los cierra.

Indice local del checkpoint: `deploy/.testing/evidence/security-evidence-index-20261031-161748.json`.
