"""Contrasta una corrida de newman con el OpenAPI de la candidata (tarea T6).

Uso, desde la raiz del repo:

    python3 docs/testing/api/contrastar_contrato.py \\
        deploy/.testing/openapi-qa.json deploy/.testing/<corrida>/newman.json

El reporte JSON de newman trae tokens, secrets y contrasenas en los cuerpos: se
lee pero no se copia. La salida (Markdown por stdout) solo tiene id de caso,
operacion, status esperado/observado y resultado de las aserciones.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

AQUI = Path(__file__).resolve().parent


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    openapi = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    corrida = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    casos = {c["id"]: c for c in json.loads((AQUI / "casos.json").read_text(encoding="utf-8"))}

    # Un caso puede ejecutarse varias veces (RL-01 se repite hasta el limite).
    observado: dict[str, dict] = {}
    for ejecucion in corrida["run"]["executions"]:
        cid = ejecucion["item"]["name"].split(" ", 1)[0]
        fila = observado.setdefault(cid, {"status": Counter(), "ok": 0, "fallas": []})
        fila["status"][ejecucion.get("response", {}).get("code")] += 1
        for asercion in ejecucion.get("assertions", []):
            if asercion.get("error"):
                fila["fallas"].append(asercion["assertion"])
            else:
                fila["ok"] += 1

    operaciones = {
        (metodo.upper(), ruta): set(op["responses"])
        for ruta, ops in openapi["paths"].items()
        for metodo, op in ops.items()
    }

    sin_documentar: dict[tuple[str, str], set[int]] = {}
    filas = []
    for cid, caso in casos.items():
        obs = observado.get(cid)
        clave = (caso["metodo"], caso["ruta"])
        if obs is None:
            filas.append(f"| {cid} | {caso['metodo']} {caso['ruta']} | {caso['espera']} | no ejecutado | — | NO EJECUTADO |")
            continue
        codigos = sorted(c for c in obs["status"] if c is not None)
        for codigo in codigos:
            if str(codigo) not in operaciones[clave]:
                sin_documentar.setdefault(clave, set()).add(codigo)
        resultado = "PASS" if not obs["fallas"] and codigos == [caso["espera"]] else "FAIL"
        documentado = "si" if all(str(c) in operaciones[clave] for c in codigos) else "no"
        filas.append(
            f"| {cid} | {caso['metodo']} {caso['ruta']} | {caso['espera']} | "
            f"{', '.join(map(str, codigos))} | {documentado} | {resultado} |"
        )

    ejercidas = {(c["metodo"], c["ruta"]) for c in casos.values() if c["id"] in observado}
    no_ejercidas = sorted(set(operaciones) - ejercidas)

    stats = corrida["run"]["stats"]
    total_pass = sum(1 for f in filas if f.endswith("| PASS |"))
    print("## Resumen de la corrida\n")
    print(f"- Casos: {len(casos)}; PASS: {total_pass}; otros: {len(casos) - total_pass}")
    print(
        f"- Requests: {stats['requests']['total']} (fallidos {stats['requests']['failed']}); "
        f"aserciones: {stats['assertions']['total']} (fallidas {stats['assertions']['failed']})"
    )
    print(f"- Operaciones del OpenAPI ejercidas: {len(ejercidas)} de {len(operaciones)}")
    if no_ejercidas:
        print("- No ejercidas: " + ", ".join(f"`{m} {r}`" for m, r in no_ejercidas))

    print("\n## Status observados que el OpenAPI no declara\n")
    print("| Operacion | Status observados sin declarar |")
    print("| --- | --- |")
    for (metodo, ruta), codigos in sorted(sin_documentar.items()):
        print(f"| `{metodo} {ruta}` | {', '.join(map(str, sorted(codigos)))} |")

    print("\n## Resultado por caso\n")
    print("| Caso | Operacion | Esperado | Observado | Documentado | Resultado |")
    print("| --- | --- | --- | --- | --- | --- |")
    print("\n".join(filas))

    fallas = {cid: o["fallas"] for cid, o in observado.items() if o["fallas"]}
    if fallas:
        print("\n## Aserciones fallidas\n")
        for cid, nombres in fallas.items():
            for nombre in nombres:
                print(f"- {cid}: {nombre}")


if __name__ == "__main__":
    main()
