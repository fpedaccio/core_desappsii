# Comprobaciones locales de seguridad HTTP

Fecha de ejecuci?n: 31 de octubre de 2026.
Entorno: muni-core-testing-e2e, en Docker Desktop local.
No se ejecutaron estas pruebas contra AWS.

## Resultados

| Grupo | Comprobaciones | Resultado |
| --- | ---: | --- |
| Sin token | 5 | Aprobado |
| Tokens malformados o falsificados | 10 | Aprobado |
| Firma v?lida: control, expiraci?n, emisor y audiencia | 8 | Aprobado |
| Permisos entre m?dulos | 9 | Aprobado |

Total: 32 comprobaciones aprobadas. Incluye controles positivos
y verificaciones del estado posterior a las operaciones prohibidas.

## Alcance comprobado

- Cinco rutas rechazan solicitudes sin token con HTTP 401.
- Se rechazan tokens malformados, sin firma y con firmas falsas.
- Tokens correctamente firmados permiten comprobar por separado
  expiraci?n, emisor y audiencia, con controles v?lidos de referencia.
- El productor puede consultar su evento; otro m?dulo no puede
  consultarlo por identificador ni encontrarlo en su listado.
- Se rechaza reemplazar el schema de otro m?dulo y se conserva
  el schema y su due?o.
- Se rechaza publicar por HTTP declarando el origen de otro m?dulo;
  el evento rechazado por autorizaci?n no queda registrado.
- Un m?dulo com?n no puede editar un m?dulo mediante la ruta
  administrativa; el nombre original permanece sin cambios.
- Los dos m?dulos sint?ticos creados se desactivaron al terminar.

## Evidencia

- `deploy/.testing/evidence/security-no-token-20261031-133222/results.json`
- `deploy/.testing/evidence/security-invalid-tokens-20261031-133321/results.json`
- `deploy/.testing/evidence/security-signed-tokens-20261031-133450/results.json`
- `deploy/.testing/evidence/security-module-permissions-20261031-133616/results.json`

Los informes originales permanecen fuera de Git.
No contienen claves, secretos ni tokens de autenticaci?n.

## L?mites y pendientes

- Estas ejecuciones fueron locales y guiadas por scripts;
  no forman todav?a una suite de seguridad incorporada al CI.
- No prueban todos los endpoints, roles ni combinaciones de permisos.
- No acreditan el control de identidad por AMQP.
- Quedan por evaluar los dem?s criterios de seguridad del TP,
  incluidos rate limiting, asignaci?n de campos no autorizados,
  inyecci?n, cabeceras, CORS, registros y escaneo autenticado.
- Este informe no constituye una aprobaci?n global de seguridad
  ni reemplaza la matriz de cumplimiento y el registro de defectos.

## Continuacion y punto de pausa del 31 de octubre

Se agregaron nueve comprobaciones aprobadas de campos no autorizados
y escalamiento de privilegios. Total acumulado: 41 comprobaciones
aprobadas, incluyendo controles positivos y verificaciones de estado.

En los casos ensayados, enviar isAdmin, role o cambios de modulo no
otorgo privilegios. Los campos desconocidos fueron ignorados; no se
considera una vulnerabilidad por si solo si no alteran los permisos.
Evidencia: deploy/.testing/evidence/security-mass-assignment-20261031-133930/results.json

Se observo ademas el comportamiento de una cuenta sintetica ante seis
logins fallidos, con un login valido inicial de control:
- Los seis intentos devolvieron 401 INVALID_CREDENTIALS.
- La cuenta termino desactivada.
- El login posterior con la contrase?a correcta devolvio
  403 ACCOUNT_INACTIVE.
- No se observo HTTP 429 ni Retry-After en esta secuencia.
- El modulo sintetico quedo desactivado y no hubo errores de ejecucion.

Esta observacion NO se contabiliza como aprobacion de rate limiting.
El bloqueo de cuenta y la limitacion de frecuencia son controles distintos.
Evidencia: deploy/.testing/evidence/security-login-attempts-20261031-134035/results.json

Al retomar: evaluar el requisito de rate limiting contra la implementacion,
registrar el hallazgo que corresponda y continuar los controles pendientes.
Las comprobaciones nuevas siguen siendo ejecuciones locales; aun no
estan incorporadas como suite de seguridad en CI.
