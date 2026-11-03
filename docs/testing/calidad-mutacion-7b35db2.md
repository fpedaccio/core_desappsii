# Calidad y mutación (T6)

> **Resultados históricos de la revisión `7b35db2`.** Se conservan sin cambios
> como evidencia de esa revisión. La candidata vigente es `16d1633`: ver
> [api-contratos.md](api-contratos.md) y [calidad-mutacion.md](calidad-mutacion.md).
> D-01 de este informe corresponde a DEF-10, ya corregido en la candidata vigente.

Fecha de ejecución: 02/11/2026. Candidata de QA: backend
`7b35db216519bedcdf891aa762b2afc64ce3b019`, en un `git worktree` limpio
(detached HEAD). La parte de API y contratos está en
[api-contratos.md](api-contratos-7b35db2.md).

Entorno: macOS, Python 3.13.3, SQLite y `FakeBroker`, igual que la suite de CI.
CI corre con Python 3.12 en Linux, así que los números pueden diferir en
detalles.

## Cobertura

Mismos comandos que CI (`docs/testing/coverage.md`, sección "Ejecución"):
pytest con `--cov=app --cov-branch`, `deploy/check_coverage.py` y los tests de
`deploy/tests`.

- Pytest: **228 passed**, código de salida 0. La medición de referencia del
  28/10 tenía 196 tests; este es el conteo vigente de la candidata.
- `fail_under=85`: se alcanza (89,44% combinado).
- Control de servicios de negocio (líneas ≥80%, ramas ≥70%): **PASS**.
- `deploy/tests`: 27 tests OK.

| Alcance | Líneas | Ramas |
| --- | ---: | ---: |
| Global | 91,87% | 75,28% |
| Servicios (`app/services`) | 93,43% | 81,85% |
| Modelos | 100,00% | No aplica |
| Repositorios | 88,77% | 63,95% |
| API y dependencias | 97,11% | 79,41% |
| Infraestructura `core` | 91,76% | 77,78% |

Archivos más bajos que importan para el alcance:

- **`api/v1/dlq.py`: 66%.** Quedan sin cubrir todo el detalle de una dead
  letter con su filtro por módulo (83-92), el listado de entregas (206-214), el
  reintento en lote (132-133) y el procesamiento de reintentos vencidos
  (228-229). El PR
  [fpedaccio/core_desappsii#14](https://github.com/fpedaccio/core_desappsii/pull/14)
  cubre el filtro del detalle y de la auditoría, que es donde estaba D-01.
- **`core/security.py`: 80%.** No se cubren claves mal configuradas ni algunos
  caminos de tokens inválidos.
- **`services/delivery_service.py`: 84%.** No se cubren la recuperación de
  publicación diferida ni errores del broker al republicar. El mismo hueco ya
  figuraba en la medición del 28/10.

## Lint

- `ruff check app tests` (ruff 0.16.1): sin errores.
- `ruff format --check app tests`: 10 archivos quedarían reformateados. CI no
  ejecuta `ruff format`, así que no rompe nada. Queda como observación.

## Mutación

### Herramienta y alcance

- mutmut 3.7.0 con pytest 8.3.5 y pytest-asyncio 0.26.0, en un entorno virtual
  aparte con las dependencias de `requirements-deploy.lock`.
- pytest 9 no es compatible con mutmut 3.3.1 ni 3.7.0: el plugin de
  estadísticas usa `item._nodeid`, que pytest 9 eliminó. Por eso se fijó
  pytest 8.3.5, que cumple el `pytest>=8.3` del proyecto.
- Configuración usada: [calidad/mutmut-setup.cfg](calidad/mutmut-setup.cfg).
  Se muta todo `app/` excepto lo que lista `do_not_mutate`.

El alcance son los módulos que deciden qué acepta el Core, a quién le entrega y
quién puede operar:

- `services/envelope.py`
- `services/validation.py`
- `services/retry_policy.py`
- `services/auth_service.py`
- `services/user_service.py`
- `services/registry_service.py`
- `services/event_hub_service.py`
- `core/auth_rate_limit.py`

Quedaron fuera las estadísticas, los catálogos, `delivery_service`, los
repositorios y la API. Son 1.186 mutantes.

**Selección restringida para dos funciones.** `AuthService.login` y
`AuthRateLimiter` se ejecutan en casi todos los tests, porque cada test HTTP
inicia sesión. Con la selección automática, cada mutante sobreviviente
re-ejecutaba unos 140 tests y el ritmo bajó a menos de un mutante por minuto.
Para esas funciones se restringió la selección:

- `login`: los 16 tests cuyo nombre trata cuentas, credenciales, bloqueo,
  contraseñas o secrets. Se descartó uno de catálogos que coincidía solo por
  la palabra "desactiva".
- `AuthRateLimiter`: los 6 tests de `test_auth_rate_limit.py`.

El resultado de esos dos módulos es un **piso**: un mutante que sobrevive a la
selección restringida podría morir con la suite completa. El resto de los
módulos usó la selección automática de mutmut.

Una corrida intermedia se interrumpió porque la computadora se suspendió (un
JWT de test venció en medio de un caso). Se relanzó con `caffeinate`. Los
resultados ya registrados se conservaron y se verificó que el corte no dejó
mutantes mal registrados.

### Resultado

Score = (muertos + timeouts) / (muertos + timeouts + sobrevivientes). Los
mutantes "sin tests" no entran en la cuenta.

| Módulo | Mutantes | Muertos | Timeout | Sobreviven | Sin tests | Score |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `services/envelope.py` | 10 | 10 | 0 | 0 | 0 | 100,0% |
| `services/retry_policy.py` | 18 | 17 | 0 | 1 | 0 | 94,4% |
| `core/auth_rate_limit.py` (piso) | 57 | 45 | 0 | 12 | 0 | 78,9% |
| `services/validation.py` | 87 | 63 | 0 | 24 | 0 | 72,4% |
| `services/user_service.py` | 130 | 83 | 0 | 47 | 0 | 63,8% |
| `services/registry_service.py` | 288 | 161 | 0 | 117 | 10 | 57,9% |
| `services/event_hub_service.py` | 345 | 177 | 7 | 161 | 0 | 53,3% |
| `services/auth_service.py` (piso) | 251 | 106 | 7 | 138 | 0 | 45,0% |
| **Total** | **1.186** | **662** | **14** | **500** | **10** | **57,5%** |

### Qué sobrevivió

Se clasificaron los 500 sobrevivientes mirando dónde cae la línea mutada. Es
una clasificación automática y aproximada:

| Tipo | Cantidad | Lectura |
| --- | ---: | --- |
| Argumentos de `logger.*` | 164 | Cambian lo que se loguea, no el comportamiento. Ningún test verifica logs |
| Texto del mensaje de una excepción | 63 | Los tests verifican el status y el `code`, no el texto |
| Otros literales de texto | 58 | Pistas (`hint`), descripciones y textos parecidos |
| Lógica | 215 | Incluye mutantes equivalentes. Por ejemplo, `actor_is_admin=None` en lugar de `False` se comporta igual, y el valor por defecto de la firma se cambia aunque todos los llamadores pasan el argumento |

Revisando a mano los sobrevivientes de lógica, estos son huecos reales de la
suite:

1. **Autorización sin test unitario (corregido).** Desactivar el chequeo de
   permisos en `declare_publication`, `set_subscription_active` y `unsubscribe`
   no hacía fallar ningún test. Se agregaron tres tests en
   [fpedaccio/core_desappsii#17](https://github.com/fpedaccio/core_desappsii/pull/17).
   Con la mutación aplicada a mano, los tres fallan. Suite completa: 231
   tests, código de salida 0.
2. **Campos de la dead letter.** En `_reject` sobrevive guardar
   `source_module=None`, `raw_payload=None` o `attempts=None`. El filtro por
   módulo de la DLQ depende de `source_module`: si se rompiera, el módulo de
   origen dejaría de ver sus propios rechazos y ningún test lo notaría. El test
   del PR #14 que verifica que el origen ve su auditoría cubre una parte.
   Falta un test que verifique los campos de la dead letter.
3. **Reproceso sin re-entregar.** En `_route` sobrevive invertir la condición
   que evita volver a entregar a un destino que ya recibió el evento
   (`status == DELIVERED`). Ningún test reprocesa un evento que ya tenía una
   entrega hecha.
4. **Resuscribirse reactiva.** En `subscribe` sobrevive dejar
   `existing.active = False`. Ningún test verifica que suscribirse de nuevo a
   una suscripción pausada la vuelva a activar.
5. **Redeclarar con schema.** En `declare_event_type` sobrevive invertir
   `if json_schema is not None`. Ningún test verifica que redeclarar un tipo
   con un schema nuevo lo actualice.
6. **Normalización del módulo.** En `user_service.create` sobrevive cambiar
   `.lower()` por `.upper()`. Ningún test crea una cuenta indicando el módulo en
   mayúsculas.
7. **Bordes.** Sobreviven cambios de límite en `validation`
   (`MAX_REPORTED_ERRORS`, `>=` contra `>`) y en el mínimo de `Retry-After`
   del limitador (`max(1, …)` contra `max(2, …)`).

Los puntos 2 a 7 quedan como recomendación de tests. No se agregaron en esta
entrega.

## Reproducir

Cobertura, desde `backend` con las dependencias dev:

```bash
python -m pytest --cov=app --cov-branch --cov-report=term-missing --cov-report=json:coverage.json --cov-report=xml:coverage.xml
python ../deploy/check_coverage.py coverage.json --output coverage-summary.json
python -m unittest discover -s ../deploy/tests -v
```

Mutación, desde `backend`, en un entorno virtual aparte. La configuración se
copia como `setup.cfg` y no se versiona ahí:

```bash
python3 -m venv /tmp/mutvenv
/tmp/mutvenv/bin/pip install -r requirements-deploy.lock "pytest==8.3.5" "pytest-asyncio==0.26.0" "aiosqlite>=0.20" "mutmut==3.7.0"
cp ../docs/testing/calidad/mutmut-setup.cfg setup.cfg
caffeinate -i /tmp/mutvenv/bin/mutmut run   # en Linux, sin caffeinate
/tmp/mutvenv/bin/mutmut results
rm setup.cfg
```

Para repetir la selección restringida de `login` y del limitador, después del
primer paso de estadísticas hay que filtrar `mutants/mutmut-stats.json` como
se describe en "Herramienta y alcance". Sin ese filtro, la medición es más
estricta pero puede tardar horas en esta computadora.

## Pendientes

- Repetir la mutación con selección completa para `login` y el limitador, en
  CI o en una máquina con más tiempo.
- Ampliar el alcance de mutación a `delivery_service`, los repositorios y la API.
- Agregar los tests recomendados en los puntos 2 a 7.
- Calidad del frontend: lint, dependencias y tests. No se abordó acá. El
  frontend fijado tiene sus propios informes de seguridad y dependencias.
- Integrar los PRs
  [fpedaccio/core_desappsii#14](https://github.com/fpedaccio/core_desappsii/pull/14)
  y [fpedaccio/core_desappsii#17](https://github.com/fpedaccio/core_desappsii/pull/17)
  a la candidata y volver a medir (T8).
