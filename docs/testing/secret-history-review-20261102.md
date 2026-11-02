# Revisi?n de secretos en historial ? 02/11/2026

## Herramienta y alcance

Gitleaks 8.24.2, imagen:
`ghcr.io/gitleaks/gitleaks@sha256:b5918eb91b8d2473cec722f066abb4352e4ffdc4ec9f4283ec143aba9ec9ebc4`.

Los informes se generaron con redacci?n total de los valores detectados.

- Backend: historial alcanzable desde las referencias locales incluidas
  en el bundle inicial, despu?s de ejecutar fetch de origin.
- Frontend: historial alcanzable desde las referencias de un clon espejo
  no superficial. Se comprob? que contiene el commit d00f07b usado
  por la candidata.
- No se modific? ni reescribi? ning?n historial.

## Resultados

- Backend: un hallazgo inicial, clasificado como falso positivo;
  segundo an?lisis del mismo bundle con excepci?n puntual: cero pendientes.
- Frontend: cero hallazgos, sin excepciones a?adidas por esta revisi?n.

La excepci?n del backend corresponde a un UUID usado como valor de
Idempotency-Key en un ejemplo HTTP documental, no a una credencial
de autenticaci?n. Se comprob? su ubicaci?n exacta y su formato UUID.

Huella excluida en `.gitleaksignore`:

`e7322372d2bccd68586d6a4d359b9a4e87d1a7d8:docs/entrega-rest/README.md:generic-api-key:165`

No se deshabilit? la regla generic-api-key ni se excluy? el archivo completo.
Los informes iniciales se conservaron.

## Evidencias locales, fuera de Git

- `deploy/.testing/evidence/g6-backend-20261102T180751Z/`
- `deploy/.testing/evidence/g6-frontend-20261102T181331Z/`

No adjuntar history.bundle, el clon espejo ni revision-privada.txt:
contienen informaci?n hist?rica sin redactar. Compartir ?nicamente
res?menes e informes redactados, previa revisi?n.

## L?mites

El resultado describe lo detectado por la herramienta en las referencias
analizadas; no demuestra ausencia absoluta de secretos ni cubre referencias
inaccesibles, repositorios externos o registros de ejecuci?n.

El bundle backend se cre? antes de a?adir esta excepci?n y este informe.
Toda incorporaci?n posterior, incluidos los cambios nuevos del PO,
debe cubrirse en el an?lisis de la candidata final.

La revisi?n de logs y credenciales operativas es independiente.
Este documento no declara cerrado G6 para un tag a?n no creado.
