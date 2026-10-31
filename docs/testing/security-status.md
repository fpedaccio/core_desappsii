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
| Intentos fallidos de login | Cuenta sintetica desactivada; login valido posterior 403 | No se observo 429; requisito de rate limiting sigue pendiente de evaluacion |
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
| Logs y datos sensibles | Pendiente revision sistematica | Algunas respuestas se revisaron; no acredita todos los logs |
| Cuenta original de ZAP | Desactivacion y retirada de credenciales verificadas | Cola e informes privados conservados; no acredita revocacion inmediata de JWT |
| Fixtures E2E | La suite desactiva modulos sinteticos al finalizar | No equivale a borrado integral de usuarios, colas o registros historicos |

## Versiones y CI

- Frontend de refuerzo: cfa32debbda11a87efbf2f16125349b88c2a8755.
- Frontend final con overrides: 6353a6dfd3613d17ade5564b96b7e09dfec70573.
- Backend con seis escenarios y pin inicial: c800ce4, checks aprobados.
- Backend con pin final: 4451d163bee9ae25791b6a14f1a70d7976203649.
  Su CI estaba en ejecucion al preparar este documento; falta registrar
  el resultado final.

El build, lint y tests del push del frontend 6353a6d aprobaron.
No trasladar automaticamente los resultados del frontend anterior al
candidato final sin comprobar la ejecucion con el nuevo pin.

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
