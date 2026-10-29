# Cinco escenarios candidatos de navegador real

Estado inicial: preparados; no se declaran aprobados hasta ejecutarlos.
Asociación a HU/criterios de Jira pendiente: no se inventan identificadores.

## Ejecución local

En una copia separada con Docker local y Python, después de preparar
`deploy/e2e_up.py`, ejecutar:

```powershell
py -3 deploy/e2e_up.py
py -3 deploy/e2e_run.py
```

El arranque E2E utiliza frontend 4a2fb0b569297a2fe75aef650780d6e9d39dbcaf,
backend identificado en bootstrap-result.json, puerto 18083 y proyecto
muni-core-testing-e2e. No cambia el bootstrap general ni comparte volúmenes con
muni-core-testing-clean. No utilizar este guion en AWS.

Playwright Python y la imagen de navegadores están fijados a 1.64.1.
El runner instala el paquete únicamente dentro del contenedor temporal.
No se simulan respuestas, no se inyecta una sesión preautenticada y no se usan
SQLite ni FakeBroker. Los datos de preparación se crean mediante HTTP real.
Cada ejecución genera módulos, cuentas y tipos sintéticos con nombres únicos.

| ID candidato | Recorrido y aserciones principales |
| --- | --- |
| E2E-01 | Login real por UI, historial, recarga con sesión conservada, perfil y logout; storage sin sesión al terminar |
| E2E-02 | Contraseña inválida: HTTP 401 real, mensaje visible, login conserva estado no autenticado |
| E2E-03 | Alta y baja de suscripción por UI, confirmación de active/maxAttempts en API y persistencia al recargar |
| E2E-04 | Suscripción, publicación HTTP válida, contenido en cola real de RabbitMQ y detalle del mismo evento visible al destinatario |
| E2E-05 | Data inválido: HTTP422, evento REJECTED/SCHEMA_VIOLATION sin entregas, dead letter y rechazo visible en UI del productor |

La observación de cola de E2E-04 usa la API de administración del broker,
devuelve el mensaje a su cola y no equivale a probar un adaptador AMQP de otro
módulo ni su procesamiento de negocio. Las dos pruebas negativas cubren 2/5
casos de esta suite; no prueban el porcentaje negativo del plan completo.

## Evidencia, seguridad y límites

Los informes quedan en deploy/.testing/evidence/e2e-*/: JUnit XML, resumen,
log saneado, identificadores sintéticos y metadatos de imágenes y revisiones.
No se generan trazas de navegador, storageState, videos ni capturas con tokens.
La configuración privada se elimina en finally; nunca se sube el directorio
.testing como artefacto completo. El runner rechaza motores Docker remotos y
contenedores que no pertenezcan al proyecto previsto.

Al terminar la clase de tests se desactivan los módulos sintéticos creados.
Se conservan sus registros, eventos, suscripciones y colas para auditoría y
para diagnosticar fallos. No son datos reales; pertenecen a los volúmenes E2E.
Una interrupción externa puede impedir la limpieza: revisar antes de repetir.
No se detiene el stack completo al terminar el runner de navegador.

Un resultado exitoso requiere exactamente cinco tests, sin fallos, errores ni
omisiones. Preparar o validar sintaxis no cuenta como ejecución aprobada.
Falta integrar esta suite al CI después de su primera ejecución real, relacionar
los casos con las HU acordadas y revisar su representatividad con el equipo.
No sustituye pruebas de seguridad completas, concurrencia, accesibilidad,
performance, caídas ni validación de todos los endpoints.

## Incorporaci?n al CI

Se agreg? `.github/workflows/core-e2e.yml` para ejecutar cinco escenarios
con Chromium real en cada push y pull request, sobre un entorno aislado.
El job verifica la revisi?n del backend, el frontend seleccionado, el
arranque desde estado vac?o y los cinco resultados sin omisiones.
Los artefactos se limitan a informes; no incluyen archivos de credenciales.

Estado: workflow preparado, pendiente de su primera ejecuci?n en GitHub.
La ejecuci?n local aprob? cinco casos en 11,700 segundos.
