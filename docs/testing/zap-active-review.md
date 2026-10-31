# Revision del escaneo activo autenticado local

## Alcance

Escaneo ZAP API-Minimal sobre ocho operaciones GET importadas del
OpenAPI, en el proyecto local muni-core-testing-zap. La herramienta
tambien sondeo rutas adicionales del mismo destino.

El reescaneo termino con 2.566 solicitudes activas y autenticacion
verificada antes y despues. El codigo 2 indica advertencias.
No constituye una aprobacion general de seguridad.

## Hallazgos revisados

| Hallazgo | Clasificacion y estado |
| --- | --- |
| HTTP 500 con caracteres nulos en filtros | Corregido y verificado localmente. Ver null-query-validation.md. |
| CORP ausente | Configuracion ausente confirmada. Pendiente de evaluar compatibilidad y tratamiento. |
| Version en Server | Exposicion de nginx/1.30.6 confirmada. Pendiente de tratamiento. |
| Content-Type HTML inesperado | La raiz sirve la interfaz web. Las rutas adicionales comprobadas devuelven el mismo HTML por fallback. Las dos rutas API con NUL responden 400 HTML, consistente con rechazo del proxy. No se demostro una vulnerabilidad por este aviso. |
| Respuestas de cliente | 244 instancias: 2 de HTTP 400, 152 de HTTP 404 y 90 de HTTP 422. El conteo no demuestra por si solo un defecto. No se reviso individualmente la correccion funcional de cada respuesta. |
| Contenido no cacheable | Observacion informativa en solicitudes autenticadas. No acredita una vulnerabilidad ni justifica habilitar cache compartida de datos privados. |

## Comprobacion de respuestas

Se hicieron 13 consultas adicionales sin autenticacion:

- La raiz y nueve rutas adicionales respondieron 200 text/html con el
  mismo SHA-256 del cuerpo.
- Las rutas incluyen un path aleatorio y sondas de metadatos. Las
  respuestas comprobadas contienen el frontend, no evidencia de
  metadatos expuestos.
- Dos rutas API con %00 respondieron 400 text/html, con cuerpos iguales
  entre si y diferentes de la pagina principal.
- El control /api/v1/events sin token respondio 401 application/json.

Esta comprobacion no acredita la proteccion general contra SSRF ni la
ausencia de exposicion de metadatos por otros mecanismos.

## Evidencias locales

- deploy/.testing/evidence/zap-active-retest-20261031-153016-1ac19c/
- deploy/.testing/evidence/zap-response-classification-20261031-154215/

Los originales del escaner permanecen en zap-private, fuera de Git,
porque pueden contener el token sintetico.

## Pendientes

- Evaluar tratamiento de CORP y exposicion de version.
- Mantener abiertos los dos hallazgos medios del baseline del frontend:
  style-src unsafe-inline y falta de SRI en el recurso externo.
- Consolidar estos resultados en la matriz de seguridad del TP.
- Limpiar la cuenta y los recursos sinteticos cuando finalice su uso.

No se aplicaron exclusiones al escaner para ocultar alertas.
Los resultados corresponden al entorno local; no acreditan despliegue
de estas correcciones en AWS.
