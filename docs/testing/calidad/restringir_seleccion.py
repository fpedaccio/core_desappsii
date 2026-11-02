"""Restringe la seleccion de tests de mutmut para login y el limitador (T6).

`AuthService.login` y `AuthRateLimiter` se ejecutan en casi todos los tests,
porque cada test HTTP inicia sesion. Con la seleccion automatica, cada mutante
sobreviviente re-ejecuta unos 170 tests y la medicion tarda horas. Este script
deja, para esas funciones, solo sus suites dedicadas:

- login: los tests cuyo nombre trata cuentas, credenciales, bloqueo,
  contrasenas, secrets o tokens (sin los de catalogos, que coinciden solo por
  la palabra "desactiva").
- AuthRateLimiter: test_auth_rate_limit.py y test_shared_auth_http.py.

Correr menos tests solo puede matar los mismos mutantes o menos: el score que
sale es un piso del que daria la seleccion completa.

Uso, desde backend/, despues de la primera pasada de `mutmut run`:

    python ../docs/testing/calidad/restringir_seleccion.py mutants/mutmut-stats.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PALABRAS = (
    "login", "auth", "bloque", "lock", "credencial", "contrasen",
    "password", "secret", "token", "desactiv", "inactiv",
)
LIMITADOR = ("tests/test_auth_rate_limit.py", "tests/test_shared_auth_http.py")


def main() -> None:
    ruta = Path(sys.argv[1])
    stats = json.loads(ruta.read_text(encoding="utf-8"))
    tests = stats["tests_by_mangled_function_name"]
    for funcion in list(tests):
        if funcion.endswith("ǁAuthServiceǁlogin"):
            tests[funcion] = [
                t for t in tests[funcion]
                if any(p in t.lower() for p in PALABRAS) and "test_catalogos" not in t
            ]
        elif "ǁAuthRateLimiterǁ" in funcion:
            tests[funcion] = [t for t in tests[funcion] if t.startswith(LIMITADOR)]
        else:
            continue
        print(f"{funcion}: {len(tests[funcion])} tests")
    ruta.write_text(json.dumps(stats), encoding="utf-8")


if __name__ == "__main__":
    main()
