# Headers de seguridad: hallazgo y correccion candidata

## Evidencia del 31 de octubre de 2026

En el entorno local HTTP y en dos consultas GET sin autenticacion al
despliegue HTTPS compartido se observo ausencia de Content-Security-Policy.
En las respuestas HTTPS tambien falto Strict-Transport-Security.
X-Content-Type-Options: nosniff estuvo presente.

Evidencias:
- deploy/.testing/evidence/security-headers-cors-20261031-140706/results.json
- deploy/.testing/evidence/security-https-headers-20261031-140835/results.json

El preflight local del origen externo ensayado devolvio 400 sin
Access-Control-Allow-Origin. No se considera por si solo una apertura CORS
ni una verificacion completa de todos los origenes y solicitudes.

## Correccion candidata

- Frontend: CSP en Nginx, conservando los headers existentes.
- Scripts y conexiones restringidos al mismo origen.
- Estilos: se permiten estilos inline por compatibilidad con la interfaz
  y las hojas de Google Fonts; no se habilitan scripts inline ni eval.
- Fuentes: se permite fonts.gstatic.com.
- Se bloquean objetos y enmarcado; X-Frame-Options se establece en DENY.
- Backend/deploy: HSTS en Caddy para el dominio HTTPS, con max-age de un a?o,
  sin includeSubDomains ni preload.

## Validacion pendiente

Pendientes: sintaxis de Nginx y Caddy, pruebas del dashboard con CSP activa,
comprobacion de headers y regresiones E2E.

No se ha modificado AWS. El hallazgo del despliegue compartido sigue
abierto hasta que la correccion se revise, se despliegue y se verifique.

La presencia de estos headers no acredita por si sola seguridad completa.

## Validacion local completada

- Imagen frontend candidata construida correctamente.
- Nginx: configuracion valida.
- Caddy: configuracion valida; aviso de formato sin error de validacion.
- Frontend candidato separado en localhost:18084: CSP, X-Frame-Options,
  nosniff y Referrer-Policy presentes.
- Cinco escenarios E2E aprobados en 12,225 segundos, sin omisiones.
- No se registraron violaciones CSP en esos cinco escenarios.
- Proxy Caddy temporal con HTTPS en localhost:18443:
  GET / devolvio 200 y GET /api/v1/events devolvio 401.
- Ambas respuestas HTTPS incluyeron HSTS max-age=31536000, CSP y nosniff.
- Certificado y hostname verificados usando una CA de prueba confiada
  solo por el cliente Python de esta comprobacion.
- El proxy temporal y sus volumenes anonimos se eliminaron.
- No se modifico AWS.

Evidencias locales:
- deploy/.testing/evidence/security-headers-nginx-20261031-141351/
- deploy/.testing/evidence/security-csp-candidate-20261031-141626/
- deploy/.testing/evidence/security-csp-browser-20261031-141813-2e56f4/
- deploy/.testing/evidence/security-hsts-https-20261031-142007-4ba3c0/

## Pendientes para integrar y desplegar

La validacion pendiente indicada en la seccion anterior queda cubierta
para los escenarios y respuestas enumerados aqui, no para toda la interfaz.

Falta actualizar las referencias del frontend de las automatizaciones
para que CI pruebe esta nueva revision, verificar esos runs y revisar los PR.

El hallazgo de AWS permanece abierto hasta aplicar y verificar alli
la correccion. No se ha demostrado la politica de cookies autenticadas
ni el cumplimiento completo de CORS con estas comprobaciones.
