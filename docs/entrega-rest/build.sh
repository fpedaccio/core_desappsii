#!/usr/bin/env bash
# Genera el entregable en PDF y DOCX desde README.md
#
#   ./build.sh
#
# Requiere: pandoc, typst (brew install pandoc typst)
# Para regenerar el diagrama: rsvg-convert (brew install librsvg)

set -euo pipefail
cd "$(dirname "$0")"

TITULO="Actividad final integradora — Servicios REST"
AUTOR="Equipo 9 — Core · Desarrollo de Aplicaciones II"
FECHA="Octubre 2026"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# El diagrama se regenera si cambio el SVG.
if command -v rsvg-convert >/dev/null && [ img/secuencia.svg -nt img/secuencia.png ]; then
  rsvg-convert -w 2800 -h 1800 -b white -o img/secuencia.png img/secuencia.svg
  echo "diagrama regenerado"
fi

# Preprocesado para los formatos de salida:
#  - los links a anclas internas no resuelven fuera de GitHub, se dejan en texto
#  - <details>/<summary> es HTML que no existe en PDF ni DOCX
python3 - "$TMP/doc.md" <<'PY'
import re, sys
s = open("README.md", encoding="utf-8").read()
s = re.sub(r'\[([^\]]+)\]\(#[^)]+\)', r'\1', s)          # [texto](#ancla) -> texto
s = re.sub(r'</?details>\n?', '', s)
# El codigo Mermaid es la fuente de un diagrama que ya se muestra como imagen:
# en el PDF ocupaba una pagina entera sin aportarle nada a quien lo lee.
s = re.sub(r'<summary>Fuente del diagrama.*?```mermaid.*?```\n', '', s, flags=re.S)
s = re.sub(r'<summary>(.*?)</summary>\n?', r'**\1**\n\n', s)
open(sys.argv[1], "w", encoding="utf-8").write(s)
PY

RESUMEN="Entregable de la actividad final integradora de la Clase 10. Diseña una fachada REST sobre un sistema de expedientes legado que solo habla SOAP, y la integra al bus de eventos de la plataforma municipal. Incluye el catálogo de endpoints, el contrato OpenAPI, ejemplos de request y response, el diagrama de secuencia y las decisiones de diseño justificadas."

COMUN=(--metadata title="$TITULO" --metadata author="$AUTOR"
       --metadata date="$FECHA" --toc --toc-depth=2 --resource-path=.)

# Plantilla propia: la de pandoc centraba y justificaba las tablas.
pandoc "$TMP/doc.md" -o entrega-servicios-rest.pdf --pdf-engine=typst \
  --template=plantilla.typ --metadata abstract="$RESUMEN" "${COMUN[@]}"
echo "PDF  listo: entrega-servicios-rest.pdf"

pandoc "$TMP/doc.md" -o entrega-servicios-rest.docx "${COMUN[@]}"
echo "DOCX listo: entrega-servicios-rest.docx"
