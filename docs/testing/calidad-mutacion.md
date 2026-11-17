# Calidad, dependencias, estabilidad y mutación (T6)

Candidata: backend `16d1633c496fce0505b218249f56fca3ee7d0d4e`, frontend fijado
`d00f07b71aaa61d27adcb179ec5a3180e9e78874`. Fecha: 02/11/2026. Los resultados
sobre `7b35db2` están en [calidad-mutacion-7b35db2.md](calidad-mutacion-7b35db2.md).

## Resumen

| Tema | Estado | Evidencia |
| --- | --- | --- |
| Cobertura de la candidata | 256 tests, 88,42% combinado; servicios 93,47% líneas y 82,09% ramas. Control de CI: PASS | Backend CI, 3 corridas (abajo) |
| Cobertura con los tests nuevos | 270 tests, 88,98% combinado; servicios 94,64% líneas y 84,80% ramas | Rama `test/mutacion-16d1633`, local |
| Lint | `ruff check` sin errores | Backend CI |
| Estabilidad | 3 corridas consecutivas sin fallas de pytest, integración, bootstrap, E2E de navegador y colección de API | Ver "Estabilidad" |
| Dependencias del backend | 0 vulnerabilidades en 51 paquetes | pip-audit |
| Dependencias del frontend | 0 en producción; 5 bajas solo en desarrollo, ya documentadas | npm audit |
| Mutación | **61,43%**, por encima del mínimo de 60% | Ver "Mutación" |
| Sonar y Quality Gate | Preparado, **no ejecutado**: falta el token | Ver "Sonar" |

## Estabilidad: tres corridas consecutivas

Mismo código de backend que `16d1633`; la rama `qa/t6-candidata-16d1633` solo
agrega documentación y workflows.

| Commit | Backend CI (build, Ruff, pytest y cobertura, bootstrap limpio, integración PostgreSQL/RabbitMQ) | E2E de navegador |
| --- | --- | --- |
| `f0e7522` | [41534918057](https://github.com/fpedaccio/core_desappsii/actions/runs/41534918057): 256 passed, 88,42%, 17 casos de integración | 6 de 6 |
| `241295a` | [41535336812](https://github.com/fpedaccio/core_desappsii/actions/runs/41535336812): 256 passed, 88,42%, 17 casos | 6 de 6 |
| `def81f8` | [41535714880](https://github.com/fpedaccio/core_desappsii/actions/runs/41535714880): 256 passed, 88,42%, 17 casos | 6 de 6 |

La colección de API y los escenarios AMQP corrieron tres veces seguidas en un
mismo job sobre Docker ([41535930793](https://github.com/fpedaccio/core_desappsii/actions/runs/41535930793)):
168 de 168 y 11 de 11 en cada corrida. Ver [api-contratos.md](api-contratos.md).

## Dependencias

- **Backend.** pip-audit 2.7.3 sobre `backend/requirements-deploy.lock`, el lock
  que se despliega: 51 paquetes, **0 vulnerabilidades conocidas**.
- **Frontend `d00f07b`.** npm audit con npm 11.7.0, sobre 724 dependencias.
  - Producción (`--omit=dev`): **0**.
  - Completo: 5 de severidad baja, todas de la cadena de Jest por `deepmerge`
    ([GHSA-gcqx-w48m-w2h4](https://github.com/advisories/GHSA-gcqx-w48m-w2h4)).
    El aviso no publica versión corregida y npm solo propone bajar Jest de
    versión mayor.
  - Mitigación: es una dependencia de desarrollo, no llega al bundle que se
    sirve. Coincide con lo documentado en
    `docs/testing/security-dependencies.md` del frontend. Hay que revisarlo
    cuando salga una versión corregida.

## Sonar

No existía configuración de Sonar en ninguno de los dos repos. Quedó preparado
en esta rama:

- `sonar-project.properties`: analiza el backend con la cobertura de pytest y
  espera el Quality Gate (`sonar.qualitygate.wait=true`).
- `.github/workflows/sonar.yml`: falla si el Quality Gate no pasa. Sin el
  secret `SONAR_TOKEN`, no analiza y deja un aviso, nunca un resultado verde.

**Pendiente, responsable: el admin del repo.** Hay que crear el proyecto en
SonarQube Cloud (`fpedaccio_core_desappsii`, organización `fpedaccio`) y cargar
`SONAR_TOKEN` en los secrets del repo. Después, el reporte esperado es la
ejecución del workflow con el estado del Quality Gate.

## Mutación

### Qué se midió

- **Código:** `app/` de `16d1633` sin cambios.
- **Tests:** los de la candidata más los de la rama `test/mutacion-16d1633`, 270
  en total:
  - 3 de autorización (los mismos del PR #17).
  - 10 sobre datos que el Core guarda y ningún test verificaba: versión, causa y
    canal del evento; sobre y cabeceras del mensaje; destinos de un duplicado;
    origen y payload de la dead letter; reintento que sigue rechazado;
    reactivación al resuscribirse; alta y edición parcial de un módulo;
    reemplazo del schema; normalización del módulo.
  - 1 tomado del PR #14 (404 de la auditoría de un id inexistente).
- **Alcance:** los mismos 8 módulos que en `7b35db2`: `envelope`, `validation`,
  `retry_policy`, `auth_service`, `user_service`, `registry_service`,
  `event_hub_service` y `core/auth_rate_limit`. 1.200 mutantes.
- **Herramientas:** mutmut 3.7.0, con pytest 8.3.5 y pytest-asyncio 0.26.0 en
  un entorno aparte con `requirements-deploy.lock`. pytest 9 no es compatible
  con mutmut, porque su plugin usa `item._nodeid`.
- **Configuración:** [calidad/mutmut-setup.cfg](calidad/mutmut-setup.cfg).

**Fórmula:** score = (muertos + timeouts) / (muertos + timeouts +
sobrevivientes). Los mutantes sin tests no entran. En esta medición hubo 0
timeouts.

**Selección restringida.** `AuthService.login` y `AuthRateLimiter` corren en
casi todos los tests, porque cada test HTTP inicia sesión. Para esas dos
funciones, [calidad/restringir_seleccion.py](calidad/restringir_seleccion.py)
deja solo sus suites dedicadas:

- `login`: 17 tests de cuentas y credenciales.
- `check` del limitador: 6 tests.
- `__init__` del limitador: 12 tests.

Correr menos tests solo puede matar los mismos mutantes o menos, así que el
score es un **piso** del que daría la selección completa.

**Ejecución en dos pasadas:**

1. Todo menos esas dos funciones, con selección automática.
2. Las dos funciones con la selección restringida.

La segunda pasada se repitió con la regla estricta. En la primera versión,
mutmut había sumado el test nuevo de DEF-10 al recalcular estadísticas; las dos
versiones dieron el mismo resultado.

### Resultado

| Módulo | Mutantes | Muertos | Timeout | Sobreviven | Sin tests | Score |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `services/envelope.py` | 10 | 10 | 0 | 0 | 0 | 100,0% |
| `services/retry_policy.py` | 18 | 17 | 0 | 1 | 0 | 94,4% |
| `core/auth_rate_limit.py` (piso) | 57 | 45 | 0 | 12 | 0 | 78,9% |
| `services/validation.py` | 87 | 63 | 0 | 24 | 0 | 72,4% |
| `services/registry_service.py` | 288 | 178 | 0 | 100 | 10 | 64,0% |
| `services/user_service.py` | 130 | 83 | 0 | 47 | 0 | 63,8% |
| `services/event_hub_service.py` | 359 | 228 | 0 | 131 | 0 | 63,5% |
| `services/auth_service.py` (piso) | 251 | 107 | 0 | 144 | 0 | 42,6% |
| **Total** | **1.200** | **731** | **0** | **459** | **10** | **61,43%** |

En `7b35db2`, con el mismo alcance y la misma fórmula, el score era 57,5%. El
código de `event_hub_service` cambió entre las dos candidatas (345 a 359
mutantes), así que la comparación es por alcance, no mutante por mutante.

**Condición para dar por cumplido el mínimo:** el 61,43% se midió con los tests
de la rama `test/mutacion-16d1633`. Vale para la candidata cuando esos tests se
integren. Si se integran sin cambios en `app/`, el resultado no cambia; si
cambia el código, hay que volver a medir.

### Sobrevivientes

Clasificación automática y aproximada de los 459, según dónde cae la línea
mutada:

| Tipo | Cantidad |
| --- | ---: |
| Argumentos de `logger.*` | 164 |
| Texto del mensaje de una excepción | 69 |
| Otros literales de texto | 58 |
| Valor por defecto de la firma | 1 |
| Lógica (incluye mutantes equivalentes) | 167 |

La lógica sobreviviente bajó de 214 a 167. Se concentra en:

- `_route` (23).
- `declare_publication` (16) y `subscribe` (15). En su mayoría son valores por
  defecto equivalentes, que todos los llamadores pisan, y argumentos de
  `apply_topology`.
- `_reject` (11).
- `login` (10).

Siguen como recomendación:

- Un test de reproceso que no reentregue a un destino ya `DELIVERED`.
- Verificar los campos restantes de la dead letter.

## Reproducir

Cobertura: los mismos comandos de `docs/testing/coverage.md`.

Mutación, desde `backend/`:

```bash
python3 -m venv /tmp/mutvenv
/tmp/mutvenv/bin/pip install -r requirements-deploy.lock "pytest==8.3.5" "pytest-asyncio==0.26.0" "aiosqlite>=0.20" "mutmut==3.7.0"
cp ../docs/testing/calidad/mutmut-setup.cfg setup.cfg
caffeinate -i /tmp/mutvenv/bin/mutmut run 'app.services.envelope*' 'app.services.validation*' \
  'app.services.retry_policy*' 'app.services.user_service*' 'app.services.registry_service*' \
  'app.services.event_hub_service*' 'app.services.auth_service.x_*' 'app.services.auth_service.xǁAuthServiceǁ[!l]*'
python3 ../docs/testing/calidad/restringir_seleccion.py mutants/mutmut-stats.json
caffeinate -i /tmp/mutvenv/bin/mutmut run 'app.services.auth_service.xǁAuthServiceǁlogin*' 'app.core.auth_rate_limit*'
/tmp/mutvenv/bin/mutmut results
rm setup.cfg
```

En Linux, sin `caffeinate`. Si la computadora se suspende, un JWT de test puede
vencer en medio de un caso y fallar la corrida limpia.

Dependencias:

```bash
pip-audit -r backend/requirements-deploy.lock --no-deps --disable-pip
npm audit --omit=dev && npm audit   # en el clon del frontend en d00f07b
```

## Pendientes

| Pendiente | Responsable | Reporte esperado |
| --- | --- | --- |
| Crear el proyecto en SonarQube Cloud y cargar `SONAR_TOKEN` | Admin del repo | Ejecución de `sonar.yml` con el Quality Gate |
| Integrar `test/mutacion-16d1633` y `qa/t6-candidata-16d1633` a la candidata | Equipo (coordinación con #15) | CI verde sobre la candidata integrada |
| Repetir la mutación si cambia `app/` antes del cierre | QA T6 | Nueva tabla con la misma fórmula |
