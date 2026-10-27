"""Da de baja el territorio ficticio de arranque (zonas y barrios inventados).

El seed carga los 48 barrios y 15 comunas reales de CABA, pero es idempotente
por `codigo`: en un servidor que ya tenia el territorio ficticio, correr el seed
AGREGA lo real al lado de lo ficticio, no lo reemplaza. Este script da de baja lo
ficticio por la API (activo=false), asi deja de aparecer en `?soloActivos=true`.

Es *soft-delete*: no borra nada, porque un evento viejo puede referenciar un
codigo y el identificador no se reusa. Lo corre quien tenga el token de admin;
no necesita acceso a la base.

    python docs/limpiar-territorio-ficticio.py --base https://core-uade-2026.duckdns.org

El token se pide por stdin (no queda en el historial ni en la linea de comandos).
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
import urllib.error
import urllib.request

ZONAS_FICTICIAS = ["centro", "norte", "sur", "oeste", "ribera"]
BARRIOS_FICTICIOS = [
    "plaza-mayor", "tribunales", "mercado-viejo", "villa-elisa", "los-aromos",
    "alto-verde", "san-cayetano", "parque-industrial", "barrio-obrero",
    "las-quintas", "santa-rita", "el-molino", "loma-linda", "puerto-viejo",
    "costanera", "isla-verde",
]


def _patch(base: str, token: str, ruta: str) -> int:
    req = urllib.request.Request(
        f"{base}{ruta}",
        data=json.dumps({"activo": False}).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True, help="URL del Core, sin barra final")
    args = parser.parse_args()
    base = args.base.rstrip("/") + "/api/v1/catalogos"
    token = getpass.getpass("Token de admin (Bearer, no se muestra): ").strip()

    objetivos = [("barrios", c) for c in BARRIOS_FICTICIOS] + [("zonas", c) for c in ZONAS_FICTICIAS]
    bajas = ausentes = otros = 0
    for recurso, codigo in objetivos:
        code = _patch(base, token, f"/{recurso}/{codigo}")
        if code == 200:
            bajas += 1
            print(f"  baja  {recurso}/{codigo}")
        elif code == 404:
            ausentes += 1  # ya no estaba: nada que hacer
        else:
            otros += 1
            print(f"  ERROR {code}  {recurso}/{codigo}", file=sys.stderr)

    print(f"\nListo: {bajas} dados de baja, {ausentes} que ya no estaban, {otros} con error.")
    if otros:
        sys.exit(1)


if __name__ == "__main__":
    main()
