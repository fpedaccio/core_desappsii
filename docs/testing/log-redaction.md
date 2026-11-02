# Censura de datos sensibles en logs: checkpoint

## Hallazgo

La muestra de logs de la API local contenia once lineas de login_failed
con direcciones de correo. Una coincidencia de Authorization Bearer
correspondia al placeholder documental <token>, no a una credencial
observada.

Las muestras revisadas no mostraron JWT, contrasenas locales conocidas,
tracebacks ni detalles de errores de base de datos segun los patrones
utilizados. Esto no garantiza ausencia general de datos sensibles.

## Cambio preparado

Se agrega un procesador central de structlog, despues del formateo de
excepciones y antes del renderer. Censura campos sensibles y patrones de
correos, JWT, Bearer, credenciales en URLs y claves privadas.
Procesa estructuras anidadas sin modificar los objetos originales.

No cambia respuestas HTTP ni registros de auditoria de la base.
No elimina logs historicos. No intercepta automaticamente logs de Nginx,
Uvicorn, logging estandar u otras librerias que no usen esta cadena.
Patrones no reconocidos o datos sensibles sin etiquetas pueden quedar
fuera del alcance; no se declara proteccion universal.

## Validacion

- Ruff aprobado.
- 17 pruebas especificas aprobadas.
- Suite completa: 228 pruebas aprobadas en 323,41 segundos.
- Cobertura combinada: 89,44 %.
- Evidencia: deploy/.testing/evidence/log-redaction-tests-20261031-163952/

El intento previo de crear herramientas en /opt fallo por permisos.
Se corrigio usando /tmp, conservando el usuario sin privilegios.
La imagen local muni-core-backend:qa-tools queda disponible para
reutilizar las herramientas de pruebas.

## Punto de reanudacion

1. Reconstruir solo la API del entorno local ZAP con este cambio.
2. Verificar el contenido de los archivos del contenedor.
3. Ejecutar un login fallido con una identidad sintetica nueva.
4. Comprobar que el nuevo log contiene la censura y no el correo original,
   sin mostrar ni guardar el contenido sensible.
5. Documentar el resultado, abrir el PR sobre
   devops/auth-rate-limit-20261031 y verificar CI.

El cambio aun no se verifico en los logs de la API reconstruida.
No se desplego en AWS.

## Verificacion HTTP posterior al checkpoint

Se reconstruyo la API local y se verificaron por SHA-256 los archivos
logging.py y log_redaction.py contra el codigo local.

Un login fallido con una identidad sintetica inexistente respondio 401
INVALID_CREDENTIALS. Se encontro su log mediante un traceId exclusivo:

- Marcador [REDACTED] presente.
- Correo sintetico ausente de la muestra de logs.
- Contrasena sintetica ausente de la muestra.
- Los logs originales no se mostraron ni se guardaron.

Evidencia:
deploy/.testing/evidence/log-redaction-http-20261031-165138/results.json

Esta comprobacion completa el paso local que estaba pendiente en el
checkpoint anterior. No cubre todos los caminos de logging ni logs de
terceros, y no elimina registros historicos.

Al retomar: abrir el PR sobre devops/auth-rate-limit-20261031,
verificar CI y actualizar la matriz con el resultado acotado.

## Cierre de CI del candidato

PR #10 abierto sobre devops/auth-rate-limit-20261031.
El commit 9adafb0b32a1f15c1b0705c250810d4a5fe423e2 aprobo build,
Ruff, PyTest, integracion, bootstrap limpio y seis E2E en push y PR.
La verificacion HTTP local posterior al checkpoint tambien aprobo.

Esto completa los pasos locales y de CI que estaban pendientes en las
secciones anteriores. Se mantienen los limites de alcance del filtro;
no se declara saneamiento integral de todos los logs ni despliegue AWS.
