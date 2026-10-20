# Despliegue continuo de Core

Estado: candidato en preparaci?n. No activado ni probado de extremo a extremo.

## Flujo
Push a main -> build, lint y tests exitosos -> trabajo deploy -> OIDC -> SSM.
Los pull requests y las otras ramas no despliegan.

Variables de GitHub por repositorio:
- CORE_CD_ENABLED: ausente o false desactiva el trabajo; true lo habilita.
- CORE_CD_MODE: --check valida sin aplicar; --apply actualiza servicios.
Si CORE_CD_MODE no existe, se usa --check.
Desactivar el trabajo no cancela comandos SSM que ya se enviaron.

## Servidor
El documento Core-DeployApplication, versi?n 1, invoca
/usr/local/sbin/core-deploy. El script instalado no se actualiza solo al
modificar su copia del repositorio: requiere instalaci?n administrativa.

El ejecutor exige repositorio limpio y el ?ltimo commit de main.
Un bloqueo en el servidor serializa los despliegues de ambos repositorios.
Antes de aplicar, respalda PostgreSQL y conserva una etiqueta de la imagen anterior.
Rechaza cambios en las rutas protegidas de infraestructura, modelos, seed
y configuraci?n de base del backend. Esto no reemplaza revisar las migraciones.

Verifica readiness HTTPS y consumidores de core.inbox y q.dlq.
No ejecuta login, pruebas funcionales completas ni restauraci?n de respaldo.

## Fallos y recuperaci?n
No existe rollback autom?tico. Un fallo puede dejar el c?digo actualizado
o servicios parcialmente recreados. Revisar la salida SSM, commits e im?genes
antes de intervenir; no restaurar la base autom?ticamente ni usar down -v.
El timeout del monitor no garantiza que el comando remoto haya terminado.
Conservar el CommandId y comprobar su estado antes de repetir.

Las im?genes anteriores se conservan sin limpieza autom?tica por ahora:
vigilar el espacio y definir una pol?tica de retenci?n antes del uso sostenido.

## Activaci?n pendiente
1. Validar CI de ambos candidatos.
2. Integrar en main las versiones completas de front y back.
3. Probar GitHub/OIDC/SSM usando --check.
4. Probar --apply en ambos componentes y comprobar la aplicaci?n.
5. Probar y documentar recuperaci?n ante un despliegue fallido.
6. Registrar evidencia antes de considerar cerrado el CD.
