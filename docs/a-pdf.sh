#!/usr/bin/env bash
# Convierte cualquier documento del repo a PDF con el maquetado del equipo.
#
#   ./a-pdf.sh respuesta-obras-convenciones.md
#   ./a-pdf.sh respuesta-obras-convenciones.md "Título" "Autor"
#
# Requiere: pandoc, typst (brew install pandoc typst)

set -euo pipefail
cd "$(dirname "$0")"

ORIGEN="${1:?uso: ./a-pdf.sh <archivo.md> [titulo] [autor]}"
[ -f "$ORIGEN" ] || { echo "no existe: $ORIGEN" >&2; exit 1; }

# Si no dan titulo, se usa el primer encabezado del documento.
TITULO="${2:-$(grep -m1 '^# ' "$ORIGEN" | sed 's/^# //')}"
AUTOR="${3:-Equipo 9 — Core · Desarrollo de Aplicaciones II}"
SALIDA="${ORIGEN%.md}.pdf"

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

python3 - "$ORIGEN" "$TMP/doc.md" <<'PY'
import re, sys
s = open(sys.argv[1], encoding="utf-8").read()

# El primer encabezado ya va en la portada: repetirlo arriba del cuerpo sobra.
s = re.sub(r'\A# .*\n+', '', s, count=1)

# Los links a anclas internas y a otros .md del repo no resuelven en un PDF:
# se dejan como texto para no mostrar un link muerto.
s = re.sub(r'\[([^\]]+)\]\(#[^)]+\)', r'\1', s)
s = re.sub(r'\[([^\]]+)\]\((?!https?://)[^)]+\.md\)', r'\1', s)

# HTML que no existe fuera de GitHub.
s = re.sub(r'</?details>\n?', '', s)
s = re.sub(r'<summary>(.*?)</summary>\n?', r'**\1**\n\n', s)

# `|---|` deja que el conversor elija la alineacion y termina centrando.
s = re.sub(r'\|-{2,}(?=\|)', '|:---', s)

open(sys.argv[2], "w", encoding="utf-8").write(s)
PY

pandoc "$TMP/doc.md" -o "$SALIDA" \
  --pdf-engine=typst --template=entrega-rest/plantilla.typ \
  --metadata title="$TITULO" --metadata author="$AUTOR" \
  --metadata date="$(LC_ALL=es_ES.UTF-8 date '+%d de %B de %Y' 2>/dev/null || date '+%d/%m/%Y')" \
  --toc --toc-depth=2 --resource-path=.:entrega-rest

echo "listo: docs/$SALIDA"
