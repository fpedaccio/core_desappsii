# Seguridad de dependencias — revisión del 29/10/2026

## Alcance

Se analizó backend/requirements-deploy.lock con pip-audit 2.10.1.
El análisis cubrió las 51 dependencias informadas del lock de despliegue,
sin dependencias omitidas. No incluye dependencias de desarrollo,
paquetes del sistema operativo ni el frontend.

## Hallazgo y corrección

certifi 2026.7.22 fue señalado por PYSEC-2026-4320,
alias GHSA-6q48-6c7w-9gw2. Las dos entradas del informe corresponden
al mismo problema, no a dos vulnerabilidades independientes.

La consulta directa a PyPI confirmó el aviso sobre autoridades
certificadoras afectadas. Su descripción recomienda certifi 2026.10.19
o posterior. Se cambió únicamente el pin a certifi==2026.10.19.

No se deshabilitó la verificación TLS ni se agregaron exclusiones.
El hallazgo no demuestra que se haya producido una interceptación.

## Verificación posterior

- pip-audit: salida 0; 51 dependencias; cero hallazgos y cero omitidas.
- Imagen separada muni-core-backend:qa-certifi construida correctamente.
- pip check: sin incompatibilidades detectadas.
- Versión efectiva de certifi en la ejecución de tests: 2026.10.19.
- Backend: 196 tests aprobados en 280,84 segundos.
- Cobertura global: 91,53 % líneas y 73,80 % ramas.
- Servicios: 93,14 % líneas y 81,51 % ramas; gate aprobado.
- Integración con PostgreSQL y RabbitMQ reales: 8 tests aprobados
  en 11,76 segundos; runner con salida 0 y limpieza completada.

Los ensayos se realizaron localmente. No se desplegó esta actualización
en AWS ni se reemplazaron los contenedores activos de la aplicación.

## Incidencias de preparación

Un primer intento no encontró la imagen local y terminó con código 125,
sin ejecutar tests. Se construyó y verificó la imagen.

Después, la lectura de logs en Windows falló por codificación cp1252.
El contenedor siguió ejecutándose; se recuperó su salida sin duplicar
la ejecución. Los informes finales y el código de tests confirmaron
el resultado aprobado. Los siguientes guiones usarán UTF-8 explícito.

## Evidencias privadas locales

- deploy/.testing/evidence/dependencies-20261029-153857/
- deploy/.testing/evidence/certifi-fix-20261029-154307/
- deploy/.testing/evidence/certifi-tests-20261029-160424/
- deploy/.integration/evidence/

Los informes originales permanecen fuera de Git.
El resultado del escaneo refleja las fuentes consultadas en esa fecha;
no garantiza ausencia de vulnerabilidades desconocidas.
