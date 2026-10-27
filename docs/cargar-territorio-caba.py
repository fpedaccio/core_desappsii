"""Carga las 15 comunas y los 48 barrios reales de CABA por la API del Core.

Es el camino que NO necesita tocar el servidor: no hace falta SSH, ni reconstruir
la imagen, ni pasar por la ruta protegida del deploy. Solo el token de admin.

Lee la lista de verdad desde `backend/app/seeds/territorio.py` (una sola fuente)
y hace POST de cada zona y barrio. Es idempotente: si una zona o barrio ya
existe, el Core responde 409 y el script lo saltea, así que se puede correr de
nuevo sin duplicar nada.

    python docs/cargar-territorio-caba.py --base https://core-uade-2026.duckdns.org

Después conviene correr `limpiar-territorio-ficticio.py` para dar de baja los
barrios de arranque inventados.

El token se pide por stdin: no queda en el historial ni en la línea de comandos.
"""

from __future__ import annotations

import argparse
import getpass
import importlib.util
import json
import pathlib
import sys
import urllib.error
import urllib.request


def _cargar_datos():
    """Lee ZONAS y BARRIOS del seed, sin importar todo el paquete del backend."""
    ruta = pathlib.Path(__file__).resolve().parent.parent / "backend/app/seeds/territorio.py"
    spec = importlib.util.spec_from_file_location("territorio", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo.ZONAS, modulo.BARRIOS


def _post(base: str, token: str, ruta: str, cuerpo: dict) -> int:
    req = urllib.request.Request(
        f"{base}{ruta}",
        data=json.dumps(cuerpo).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
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

    zonas, barrios = _cargar_datos()
    creados = existentes = errores = 0

    def aplicar(ruta: str, cuerpo: dict, etiqueta: str) -> None:
        nonlocal creados, existentes, errores
        code = _post(base, token, ruta, cuerpo)
        if code == 201:
            creados += 1
        elif code == 409:
            existentes += 1  # ya estaba: idempotente
        else:
            errores += 1
            print(f"  ERROR {code}  {etiqueta}", file=sys.stderr)

    # Primero las comunas, porque los barrios las referencian.
    for codigo, nombre, descripcion in zonas:
        aplicar("/zonas", {"codigo": codigo, "nombre": nombre, "descripcion": descripcion},
                f"zona {codigo}")
    for codigo, nombre, comuna in barrios:
        aplicar("/barrios", {"codigo": codigo, "nombre": nombre, "zona": comuna},
                f"barrio {codigo}")

    print(f"\nListo: {creados} creados, {existentes} que ya existían, {errores} con error.")
    if errores:
        sys.exit(1)


if __name__ == "__main__":
    main()
