# Lectura del registro para el dashboard

El dashboard cargaba entidades ORM y relaciones de modulos,
suscripciones y publicaciones para obtener cantidades y nombres.

ModuleRepository.dashboard_registry consulta solo los campos necesarios.
Conserva el total de suscripciones, la cantidad activa, los nombres
ordenados de tipos activos y las publicaciones activas. No modifica
las consultas utilizadas por otros servicios ni agrega cache.

## Validacion

- Comparacion del dashboard completo en 14 casos existentes/inexistente:
  resultados equivalentes, con ventana temporal fija.
- Regresion PostgreSQL: activos e inactivos, orden de nombres,
  aislamiento entre modulos, modulo vacio, inexistente y rollback.
- Ruff aprobado.
- 231 pruebas de backend aprobadas; cobertura con ramas: 89,21 %.
- 13 pruebas de integracion aprobadas.
- Evidencia local:
  deploy/.testing/evidence/dashboard-registry-tests-20261102T050958Z/
- Comparacion previa:
  deploy/.testing/evidence/dashboard-registry-candidate-20261102T050902Z/

En el diagnostico separado, la mediana del servicio con concurrencia 15
paso de 218,41 a 179,20 ms. No es una medicion HTTP ni acredita los
umbrales de aceptacion.

## Pendiente

Medir el candidato reconstruido con el escenario habitual:
50 usuarios durante cinco minutos, p95 menor a 500 ms y errores
menores al 1 % por operacion. Conservar tambien los resultados fallidos.
