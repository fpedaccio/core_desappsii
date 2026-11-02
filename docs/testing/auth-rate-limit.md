# Limitacion local de solicitudes de autenticacion

## Comportamiento

Se admiten hasta diez solicitudes con payload valido por identidad y
endpoint en una ventana fija de sesenta segundos:

- POST /api/v1/auth/login: identidad basada en el email.
- POST /api/v1/auth/module-token: identidad basada en el modulo.

La solicitud siguiente responde HTTP 429, code RATE_LIMITED,
Retry-After con los segundos restantes y Cache-Control: no-store.
La respuesta conserva la estructura de errores y traceId del Core.
OpenAPI documenta la respuesta 429 en ambos endpoints.

Se cuentan solicitudes admitidas tanto exitosas como fallidas.
No se reinicia el contador por un login exitoso.
Payloads rechazados por la validacion del endpoint no consumen este
contador.

La identidad se normaliza mediante strip y casefold y se guarda como
SHA-256 junto con el path. No se almacenan contrasenas ni secretos en
las claves del limitador. El hash no equivale a anonimato garantizado.

No se modifico el bloqueo de cuenta existente tras cinco contrasenas
incorrectas ni se agregaron limites a la publicacion de eventos.

## Estado y limites

- Contador en memoria por instancia de la aplicacion.
- No compartido entre procesos, replicas o servidores.
- Se reinicia al reiniciar la API.
- Ventana fija: puede permitir dos rafagas cercanas a un cambio de ventana.
- Capacidad maxima de 5.000 claves activas.
- Al llenarse, se rechazan nuevas claves temporalmente en lugar de
  expulsar contadores activos.
- Una identidad puede ser limitada aunque sus credenciales sean validas.
- No hay limitacion adicional por IP, dispositivo o origen.
- Rotar identidades puede evitar el limite individual hasta alcanzar
  la capacidad. No acredita defensa completa contra ataques distribuidos,
  enumeracion de cuentas o agotamiento de recursos.
- No usa X-Forwarded-For para decidir el limite.

La proteccion debe reevaluarse si se despliega con multiples procesos
o replicas. Este cambio local no se presenta como solucion distribuida.

## Pruebas

Ruff aprobado. Seis pruebas nuevas verifican:

- Limite de ventana y calculo de Retry-After.
- Recuperacion al llegar exactamente al fin de ventana, con reloj controlado.
- Independencia de claves.
- Capacidad acotada sin expulsar contadores activos.
- Admisiones concurrentes acotadas.
- Integracion HTTP de ambos endpoints, mediante casos parametrizados.

Suite completa: 211 pruebas aprobadas en 332,82 segundos.
Cobertura combinada de lineas y ramas: 89,37 %.

Despues de reconstruir la API local, se verificaron los hashes del
codigo y diez comprobaciones HTTP reales:

- Primeros diez intentos con identidades inexistentes: 401.
- Intento once: 429 RATE_LIMITED y Retry-After valido.
- Variante de mayusculas de la identidad: mismo contador.
- Otra identidad: 401, sin heredar el bloqueo.
- GET /events sin token: 401.
- Liveness: 200.

La expiracion de ventana se probo con reloj controlado; no se espero
una ventana real en esta comprobacion HTTP.
No se crearon ni desactivaron cuentas para esta prueba.

## Evidencia

- deploy/.testing/evidence/auth-rate-limit-tests-20261031-162253/
- deploy/.testing/evidence/auth-rate-limit-http-20261031-163029/

El intento previo detenido por formato de Ruff tambien se conserva.
Los informes originales permanecen fuera de Git.

## Estado de entrega

Verificado en la API local muni-core-testing-zap.
CI verificado en el candidato descendiente 9adafb0: build, Ruff, PyTest, integracion, bootstrap limpio y seis E2E aprobados en push y PR.
No desplegado en AWS. No acredita por si solo el cierre del requisito
completo de fuerza bruta ni de G1-G9.
