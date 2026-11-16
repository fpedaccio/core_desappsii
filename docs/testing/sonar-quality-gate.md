# Sonar Quality Gate — triage de hallazgos (Entrega 4)

Proyecto: [`fpedaccio_core_desappsii`](https://sonarcloud.io/dashboard?id=fpedaccio_core_desappsii)
en SonarQube Cloud. Gate por defecto ("Sonar way") sobre código nuevo.

## Estado de partida (12/11/2026)

El Automatic Analysis corrió sobre los PRs #4, #12, #15 y #16 y el gate falló
en todos. Detalle del PR #15 (`16d1633`):

| Condición | Valor | Umbral |
|---|---|---|
| Reliability Rating on New Code | E | A |
| Security Rating on New Code | C | A |
| Duplicated Lines on New Code | 18,7 % | ≤ 3 % |
| Maintainability Rating on New Code | A (OK) | A |
| Security Hotspots Reviewed | 100 % (OK) | 100 % |

Ninguno de esos PRs es la candidata de entrega: hay que leer el gate en el PR
de la candidata hacia `main`.

> El job `Backend - Sonar quality gate` de `.github/workflows/sonar.yml` termina
> en verde **sin analizar** cuando el repo no tiene el secret `SONAR_TOKEN`. Ese
> verde no vale como evidencia. La evidencia es el check `SonarCloud Code
> Analysis` (o el job de CI con token) sobre el commit entregado.

## Triage

| # | Regla | Ubicación | Impacto | Decisión | Responsable |
|---|---|---|---|---|---|
| S-01 | python:S930 | `backend/app/api/deps.py:51` | Fiabilidad, BLOCKER | **Corregido en esta rama + falso positivo en Sonar.** `Depends(..., scope="function")` existe desde FastAPI 0.121.0, verificado en los wheels publicados: 0.120.4 no lo tiene y 0.121.0 sí. `pyproject.toml` declaraba `fastapi>=0.115`, que permitía instalar una versión sin ese parámetro. Se sube el mínimo a `>=0.121`. El lock de despliegue ya fija 0.143.0. El analizador de Sonar no conoce el parámetro, así que se marca *False positive* con este enlace. | Diego |
| S-02 | python:S8786 | `backend/app/core/log_redaction.py:7` | Fiabilidad, MEDIUM | **Corregir.** La regex de email tiene backtracking super-lineal (`[A-Za-z0-9.-]+\.`), con riesgo de ReDoS sobre líneas de log largas. Reescribirla sin solapamiento y agregar un test con una entrada patológica. | Facu |
| S-03 | pythonsecurity:S8707 (×2) | `deploy/check_coverage.py:65,69` | Seguridad, HIGH | **Falso positivo / Safe.** Es una herramienta de CI que se invoca con rutas fijas desde `backend-ci.yml`. No recibe entrada de usuarios ni de un LLM, y quien la ejecuta ya tiene acceso al árbol. | Diego |
| S-04 | docker:S8541, S8544 (×4) | `backend/Dockerfile.integration:6` | Seguridad, MEDIUM | **Corregir o aceptar con justificación.** La imagen solo corre la suite de integración en el runner. Opciones: `--require-hashes` en el lock, o aceptar el riesgo porque las dependencias de producción ya vienen de `requirements-deploy.lock` con versiones fijas. | Matías |
| S-05 | python:S2612 | `deploy/integration_up.py:51` | Seguridad, MEDIUM | **Revisar.** `chmod 0o777` sobre el directorio de evidencias sintéticas, para que el uid 10001 del contenedor pueda escribir. Alternativa: `chown`/ACL o `0o770` con el grupo del contenedor. Si se mantiene, marcar *Safe* con la justificación del comentario. | Matías |
| S-06 | Duplicación (CPD) | `deploy/e2e/browser_suite.py` ↔ `deploy/e2e/integrated_dlq_suite.py` (345 + 345 líneas), `deploy/e2e_run.py` ↔ `deploy/integrated_e2e_run.py` (98 + 98) | 886 líneas = 100 % de la duplicación nueva | **Excluidos de CPD en esta rama** (`sonar.cpd.exclusions`). Son arneses de prueba que repiten a propósito el mismo flujo en el stack aislado y en el integrado. `backend/app` sigue sujeto a la condición de duplicación, y los archivos se siguen analizando para bugs y vulnerabilidades. | Diego |

## Modo de análisis

- **Automatic Analysis (estado actual):** toma la configuración de
  `.sonarcloud.properties`. No importa cobertura.
- **Análisis por CI (recomendado):** `.github/workflows/sonar.yml` con
  `sonar-project.properties`. Sube `coverage.xml` de pytest, así que la cobertura
  del backend queda acreditada en el gate. Requiere que el dueño del repo cargue
  el secret `SONAR_TOKEN` y desactive el Automatic Analysis en SonarQube Cloud;
  con los dos activos, el job de CI falla.

## Evidencia a adjuntar

1. Captura del gate **Passed** en el PR de la candidata, o del análisis de `main`
   con el commit del tag `v2.0-entrega4`.
2. Lista de issues marcados *False positive* o *Safe*, con el enlace a este documento.
3. Si se usa el análisis por CI: la ejecución del job `Backend - Sonar quality gate`
   que **no** muestre el warning `SONAR_TOKEN is not configured`.
