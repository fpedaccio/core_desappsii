# Validacion de caracteres nulos en filtros de consulta

## Hallazgo

El escaneo activo autenticado de ZAP detecto una respuesta HTTP 500 al
consultar barrios con `zona=%00`. La reproduccion local confirmo tambien
HTTP 500 con `q=%00` en barrios y `query=%00` en eventos.
Un control con una zona valida respondio HTTP 200.

Los filtros estaban declarados como cadenas sin una restriccion que
rechazara el caracter nulo antes de ejecutar la consulta.

## Correccion

Se agrega validacion declarativa en los parametros de consulta:

- `/api/v1/catalogos/barrios`: `zona` y `q`.
- `/api/v1/events`: `query`, `eventType`, `sourceModule` y `targetModule`.

Los valores que contienen el caracter nulo se rechazan con HTTP 422 y
`VALIDATION_ERROR`, usando el manejador de errores existente.
La restriccion queda incluida en el OpenAPI generado.

Se conservan las cadenas vacias, el texto Unicode y el texto literal
`%00`. Este ultimo se transmite como `%2500` y no representa un caracter
nulo despues de la decodificacion normal del parametro.

## Validacion local

- Ruff: aprobado para los archivos modificados y la prueba agregada.
- Suite de backend: 205 pruebas aprobadas en 320,71 segundos.
- Cobertura combinada de lineas y ramas: 89,08 %.
- Nueve casos parametrizados nuevos: seis negativos y tres controles.
- API reconstruida: contenido de ambos archivos verificado contra el
  codigo local mediante SHA-256.
- Entorno con PostgreSQL real: 19 comprobaciones HTTP aprobadas.
- Doce comprobaciones negativas: caracter nulo solo e intercalado en
  cada uno de los seis filtros; todas respondieron 422 con el campo
  correspondiente en los detalles de validacion.
- Siete controles validos: todos respondieron 200.

## Evidencia

Informes originales conservados fuera de Git:

- `deploy/.testing/evidence/security-null-query-reproduction-20261031-150923/`
- `deploy/.testing/evidence/null-query-regression-20261031-151738/`
- `deploy/.testing/evidence/null-query-http-verification-20261031-152625/`

El intento previo detenido por Ruff tambien se conserva como evidencia
del proceso; no se cuenta como ejecucion aprobada.

## Alcance y pendientes

La correccion se verifico en el proyecto local `muni-core-testing-zap`,
puerto 18085. No se desplego en AWS.

Estos resultados cubren los seis filtros indicados. No acreditan la
validacion de todos los campos de entrada ni la ausencia general de
inyecciones.

## Reescaneo activo autenticado

Se repitio el escaneo sobre la API local corregida:

- Ejecucion completada, sin error de ejecucion.
- Autenticacion y lectura del evento propio verificadas antes y despues.
- Escaneo activo finalizado al 100 %, con 2.566 solicitudes.
- Codigo de salida 2: el informe conserva advertencias.
- La alerta previa de respuesta HTTP 500 ya no aparece en el informe.
- Persisten tres entradas de alertas bajas y dos informativas.

Evidencia:
`deploy/.testing/evidence/zap-active-retest-20261031-153016-1ac19c/results.json`

El alcance sigue limitado a ocho operaciones GET importadas y la politica
API-Minimal, con un tiempo de escaneo acotado. La muestra de 500 mensajes
no representa la totalidad del trafico. Los complementos de ZAP pueden
actualizarse durante la ejecucion aunque la imagen este fijada por digest.

La correccion de este defecto queda verificada localmente mediante las
regresiones, las comprobaciones HTTP y el reescaneo. No equivale a una
aprobacion general de seguridad ni acredita su despliegue en AWS.

Las otras alertas del escaneo activo y los dos hallazgos medios del
baseline del frontend mantienen su estado de revision.
