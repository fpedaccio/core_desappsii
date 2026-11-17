# Cobertura: medición y alcance

## Medición de referencia, 28/10/2026

Fuente: coverage.json generado por Matías con coverage.py 7.17.0, branch_coverage=true y 196 pruebas backend aprobadas. Se ejecutó en una copia temporal dentro de Docker, con SQLite y FakeBroker; no conecta a AWS.

| Alcance | Líneas cubiertas/medidas | Líneas | Ramas cubiertas/medidas | Ramas |
|---|---:|---:|---:|---:|
| Código medido global | 2745/2999 | 91,53% | 369/500 | 73,80% |
| Servicios (app/services) | 950/1020 | 93,14% | 238/292 | 81,51% |
| Modelos (app/models) | 227/227 | 100,00% | 0/0 | No aplicable |
| Repositorios | 330/374 | 88,24% | 54/86 | 62,79% |
| API y dependencias | 754/777 | 97,04% | 19/26 | 73,08% |
| Infraestructura core | 247/273 | 90,48% | 22/32 | 68,75% |

El 89,00% informado por la consola es la métrica combinada, no el porcentaje de ramas. Las agrupaciones se ponderan sumando contadores, no promediando porcentajes de archivos. Un grupo sin ramas no se presenta como 100% de ramas.

## Umbrales en CI

Se conserva el fail_under=85 combinado del pyproject existente. Se activa --cov-branch para medir ramas, se publican JSON/XML y se agrega un control separado de servicios: líneas >=80% y ramas >=70%, según los mínimos para negocio/dominio del documento del profesor.

La lógica de aplicación está en app/services; los modelos se informan por separado y se comprueba su presencia en el reporte. Se controla servicios de manera independiente para que las líneas declarativas de los modelos no oculten faltantes de lógica. Esta es la delimitación técnica propuesta para la matriz de QA; debe corresponder al alcance de HU y revisarse si cambia la arquitectura. No es una exclusión de los repositorios de las pruebas de integración.

check_coverage.py contrasta el inventario completo de servicios/modelos con el reporte. Un archivo ausente o reporte sin medición de ramas falla como no verificable. No se agregó ningún omit ni pragma para aumentar números. Persisten las omisiones previas de workers, seeds y adaptador RabbitMQ, y las 19 líneas excluidas ya configuradas/reportadas. La tabla global corresponde a ese universo medido, no a todo el sistema.

## Ejecución

Desde backend, con las dependencias dev:

```bash
python -m pytest --cov=app --cov-branch --cov-report=term-missing --cov-report=json:coverage.json --cov-report=xml:coverage.xml
python ../deploy/check_coverage.py coverage.json --output coverage-summary.json
python -m unittest discover -s ../deploy/tests -v
```

CI adjunta coverage.json, coverage.xml y coverage-summary.json. El reporte no contiene valores de credenciales, pero debe revisarse antes de compartirlo si se modifica su configuración de contextos o fuentes. El código de salida 1 del control indica umbral incumplido; 2 indica evidencia inválida/incompleta.

## Faltantes relevantes detectados

- delivery_service: 88,56% líneas y 68,52% ramas. Revisar recuperación de publicación diferida, error del broker al republicar, rechazo persistente del reproceso y entregas sin evidencia correlacionada.
- core/security: 84,38% líneas y 58,33% ramas. Revisar tokens expirados/manipulados, claves/configuración inválidas y contraseñas/hash no válidos. Los gaps no prueban por sí solos un defecto explotable.
- api/v1/dlq: 71,74% líneas y 0% ramas (4 ramas medidas). Revisar los caminos de filtro/reintento/descartes administrativos con controles positivos y negativos de permisos.
- repositorios: faltan ramas de filtros/paginación y resultados ausentes; además deben probarse con PostgreSQL real.

La cobertura agregada de servicios supera los mínimos de líneas/ramas; no implica que cada archivo deba superar 70% individualmente según la consigna, ni que seguridad, resiliencia, contratos, E2E o mutation score estén acreditados. Priorizar pruebas de comportamiento real y criterios de HU, no pruebas que solo invoquen líneas sin verificar resultados.
