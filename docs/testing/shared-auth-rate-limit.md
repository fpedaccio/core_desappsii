# Limitador de autenticacion compartido

## Implementacion candidata

En PostgreSQL, login y module-token comparten contadores entre procesos
que utilizan la misma base de datos. Se conserva el limite de diez
solicitudes admitidas por identidad y endpoint durante sesenta segundos.

La clave contiene el path y el SHA-256 de la identidad normalizada.
No contiene passwords ni secrets. El hash no garantiza anonimato.

Una transaccion independiente registra cada admision antes de comprobar
las credenciales. Un fallo posterior de autenticacion no revierte ese
contador. Un advisory lock transaccional coordina las admisiones y la
capacidad maxima de 5.000 claves activas.

Las ventanas vencidas se eliminan durante las comprobaciones.
Se utiliza el reloj de PostgreSQL despues de adquirir el bloqueo.
Las solicitudes bloqueadas no extienden la ventana.

HTTP 429 conserva RATE_LIMITED, Retry-After y Cache-Control: no-store.
Los errores de almacenamiento contemplados devuelven HTTP 503 con
AUTH_RATE_LIMIT_UNAVAILABLE, sin recurrir a contadores locales.

SQLite en desarrollo conserva el limitador local. Produccion requiere
PostgreSQL para esta implementacion.

## Instalacion

AuthRateLimitBucket se registra en Base.metadata.
El seed existente utiliza create_all para crear la tabla faltante,
sin modificar ni eliminar las tablas existentes.

Debe ejecutarse el seed con la imagen candidata antes de atender
autenticaciones con esa imagen. No utilizar --drop.

La aplicacion usa core_app, que tiene permisos de creacion en public
segun el script versionado de inicializacion de PostgreSQL.

## Validacion ejecutada

- Ruff aprobado.
- Suite de backend: 237 pruebas aprobadas.
- Cobertura de esa suite: 88,26 %, superior al minimo de 85 %.
- Integracion con PostgreSQL y RabbitMQ: 17 pruebas aprobadas.
- Cuatro casos especificos verifican instancias compartidas, claves
  independientes, capacidad, recuperacion tras expiracion, persistencia
  frente a rollback de otra transaccion y concurrencia entre procesos.
- Cuatro procesos realizaron 32 comprobaciones sobre una misma clave:
  se admitieron exactamente diez.
- Seis casos HTTP verifican 503 ante errores simulados de almacenamiento
  en ambos endpoints y ausencia de datos sensibles en esas respuestas.

La cobertura de la suite SQLite no incluye la ejecucion de integracion.

Evidencia:
deploy/.testing/evidence/shared-auth-tests-20261102T105529Z/

## Alcance y pendientes

El candidato 91d8e9416c9229829ba0dad5cfdcca96d97f070c fue reconstruido
y verificado mediante HTTP real en el entorno local de rendimiento.
Aprobaron once comprobaciones: diez intentos admitidos y posterior 429
en ambos endpoints, normalizacion de identidad, independencia entre
identidades y conservacion de los contadores tras reiniciar la API
dentro de la ventana vigente.

Evidencia HTTP:
deploy/.testing/evidence/shared-auth-http-20261102T110746Z/

La comprobacion HTTP uso un proceso. La coordinacion entre cuatro
procesos se verifico por separado en integracion con PostgreSQL.
No se ejecuto aun una carga de rendimiento con este cambio.

El advisory lock serializa las comprobaciones de autenticacion.
No se utiliza en las consultas de historial, dashboard o publicacion.
No acredita resistencia completa a ataques ni capacidad de autenticacion
bajo carga. Rotar identidades puede agotar la capacidad temporalmente.

Los contadores sobreviven a reinicios de la API mientras persista la base.
Las ventanas dependen del reloj del servidor de PostgreSQL.
Todos los procesos deben utilizar la misma configuracion del limitador.
No coordina instalaciones que usen bases de datos distintas.

La prueba anterior de cinco minutos con dos procesos, sin este cambio,
no aprobo: p95 de publicacion 520,56 ms frente al limite de 500 ms.
Historial y dashboard aprobaron y los 10.113 eventos esperados coincidieron
con eventos unicos persistidos y total_received.

Evidencia anterior:
deploy/.testing/evidence/two-process-full-20261102T103845Z/

No desplegado en AWS. No acredita el cierre completo del TP.
