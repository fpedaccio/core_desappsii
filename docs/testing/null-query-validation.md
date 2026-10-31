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

Queda pendiente repetir el escaneo activo de ZAP sobre esta version y
revisar sus resultados. Las demas alertas del baseline y del escaneo
original conservan su estado; esta correccion no las resuelve.
