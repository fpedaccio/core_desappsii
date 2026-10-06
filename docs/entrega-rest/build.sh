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
s = re.sub(r'<summary>(.*?)</summary>\n?', r'**\1**\n\n', s)
open(sys.argv[1], "w", encoding="utf-8").write(s)
PY

COMUN=(--metadata title="$TITULO" --metadata author="$AUTOR"
       --metadata date="$FECHA" --toc --toc-depth=2 --resource-path=.)

pandoc "$TMP/doc.md" -o entrega-servicios-rest.pdf --pdf-engine=typst \
  -V mainfont="Helvetica" -V monofont="Menlo" -V fontsize=10pt \
  -V margin-x=2cm -V margin-y=2cm "${COMUN[@]}"
echo "PDF  listo: entrega-servicios-rest.pdf"

pandoc "$TMP/doc.md" -o entrega-servicios-rest.docx "${COMUN[@]}"
echo "DOCX listo: entrega-servicios-rest.docx"
