# Agregaci?n horaria de m?tricas

## Cambio

PostgreSQL agrupa los eventos por hora UTC y devuelve los totales y rechazados.
Se conservan los filtros de m?dulo y fecha. Otros dialectos mantienen la
implementaci?n previa de agrupaci?n en Python.

No cambia el contrato HTTP, la visibilidad por entregas ni la idempotencia.

## Validaci?n local

- Ruff aprobado.
- Suite general: 231 pruebas aprobadas; cobertura combinada 89,28 %.
- Integraci?n PostgreSQL/RabbitMQ: 11 pruebas, sin fallos, errores ni omisiones.
- Incluye dos regresiones de agrupaci?n, con sesi?n UTC y Buenos Aires:
  l?mites horarios, fechas con offset, rechazados, alcance por m?dulo,
  entregas propias sin doble conteo y resultados vac?os.
- Comparaci?n adicional con datos hist?ricos: igualdad de resultados globales
  y del m?dulo; datos sint?ticos revertidos al finalizar.

## Medici?n del repositorio

Sobre la fixture hist?rica de 4.328 eventos, con 15 muestras por variante:

| Concurrencia | Mediana anterior | Mediana propuesta |
|---|---:|---:|
| 1 | 26,53 ms | 10,94 ms |
| 15 | 514,16 ms | 94,00 ms |

Estas mediciones corresponden a un proceso separado y no acreditan el
cumplimiento del objetivo HTTP de 50 usuarios durante cinco minutos.

## Evidencia local

Bajo deploy/.testing/evidence/:

- performance-hourly-candidate-20261102-011452
- performance-hourly-regression-20261102-011816
- hourly-integration-recovery-20261102T042907Z
- hourly-suite-* contiene la ejecuci?n general y su cobertura.

El cierre inicial de integraci?n fue interrumpido por el tratamiento de stderr
en PowerShell. Se recuperaron el JUnit nuevo y el estado del contenedor terminado
con c?digo 0. El run.json anterior se conserv? identificado como obsoleto.
Los contenedores de integraci?n fueron retirados conservando sus vol?menes.

## Pendiente

Medir la candidata reconstruida mediante HTTP, registrar el resultado y resolver
cualquier incumplimiento restante antes de declarar aprobado rendimiento.
No se despleg? este cambio en AWS.
