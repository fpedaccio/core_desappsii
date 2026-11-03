"""Contrasta una corrida de newman con el OpenAPI de la candidata (tarea T6).

Uso, desde la raiz del repo (necesita `jsonschema`, ya incluido en el backend):

    python3 docs/testing/api/contrastar_contrato.py \\
        deploy/.testing/openapi-qa.json deploy/.testing/<corrida>/newman.json

Separa dos tipos de diferencia entre el contrato y lo observado:

1. Respuestas documentadas que no coinciden: el status esta declarado, pero el
   Content-Type o el cuerpo no cumplen lo que declara el OpenAPI.
2. Respuestas reales que faltan en el OpenAPI: status observados sin declarar.

Los comportamientos que requieren una decision de contrato no se deducen de una
corrida: se registran a mano en el informe.

El reporte JSON de newman trae tokens, secrets y contrasenas en los cuerpos: se
lee pero no se copia. La salida (Markdown por stdout) solo tiene id de caso,
operacion, status, la ruta del campo que no cumple y la regla que falla; nunca
valores de los cuerpos.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from jsonschema import Draft202012Validator

AQUI = Path(__file__).resolve().parent


def validador(openapi: dict, schema: dict) -> Draft202012Validator:
    # Los $ref del OpenAPI apuntan a #/components/schemas: se resuelven contra
    # el documento completo. Sin FormatChecker, igual que la API.
    return Draft202012Validator({**schema, "components": openapi.get("components", {})})


def cuerpo(ejecucion: dict):
    stream = ejecucion.get("response", {}).get("stream")
    if not stream:
        return None
    try:
        return json.loads(bytes(stream["data"]).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None


def content_type(ejecucion: dict) -> str:
    for header in ejecucion.get("response", {}).get("header", []):
        if header.get("key", "").lower() == "content-type":
            return header.get("value", "").split(";")[0].strip()
    return ""


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    openapi = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    corrida = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    casos = {c["id"]: c for c in json.loads((AQUI / "casos.json").read_text(encoding="utf-8"))}

    operaciones = {
        (metodo.upper(), ruta): op["responses"]
        for ruta, ops in openapi["paths"].items()
        for metodo, op in ops.items()
    }

    # Un caso puede ejecutarse varias veces (RL-01 se repite hasta el limite).
    observado: dict[str, dict] = {}
    no_coinciden: dict[tuple, dict] = {}
    for ejecucion in corrida["run"]["executions"]:
        cid = ejecucion["item"]["name"].split(" ", 1)[0]
        caso = casos[cid]
        clave = (caso["metodo"], caso["ruta"])
        codigo = ejecucion.get("response", {}).get("code")
        fila = observado.setdefault(cid, {"status": Counter(), "ok": 0, "fallas": []})
        fila["status"][codigo] += 1
        for asercion in ejecucion.get("assertions", []):
            if asercion.get("error"):
                fila["fallas"].append(asercion["assertion"])
            else:
                fila["ok"] += 1

        declarada = operaciones[clave].get(str(codigo))
        contenido = (declarada or {}).get("content") or {}
        if not contenido:
            continue
        real = content_type(ejecucion)
        motivos = []
        if real not in contenido:
            motivos.append(f"Content-Type `{real or 'sin cuerpo'}`; declarado `{', '.join(contenido)}`")
        schema = (contenido.get(real) or next(iter(contenido.values()))).get("schema")
        datos = cuerpo(ejecucion)
        if schema and datos is not None:
            errores = sorted(validador(openapi, schema).iter_errors(datos), key=lambda e: list(e.absolute_path))
            for error in errores[:3]:
                ruta = "/".join(map(str, error.absolute_path)) or "(raiz)"
                motivos.append(f"`{ruta}` no cumple `{error.validator}`")
        if motivos:
            entrada = no_coinciden.setdefault((*clave, codigo), {"casos": set(), "motivos": set()})
            entrada["casos"].add(cid)
            entrada["motivos"].update(motivos)

    sin_documentar: dict[tuple[str, str], set[int]] = defaultdict(set)
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
                sin_documentar[clave].add(codigo)
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

    print("\n## 1. Respuestas documentadas que no coinciden con la implementacion\n")
    print("| Operacion | Status | Diferencia | Casos |")
    print("| --- | --- | --- | --- |")
    for (metodo, ruta, codigo), entrada in sorted(no_coinciden.items()):
        print(
            f"| `{metodo} {ruta}` | {codigo} | {'; '.join(sorted(entrada['motivos']))} | "
            f"{', '.join(sorted(entrada['casos']))} |"
        )

    print("\n## 2. Respuestas reales que faltan en el OpenAPI\n")
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
