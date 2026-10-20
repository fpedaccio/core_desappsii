# ADR-004 · La capa de repositorios es una fabricación pura

- **Estado:** aceptado
- **Fecha:** 2026-10-20
- **Patrón:** Pure Fabrication + Indirection (GRASP)
- **Componente:** `app/repositories/`

## Contexto

Por *Experto en Información*, la clase que tiene los datos debería hacer las
operaciones sobre ellos: un `EventLog` sabría buscarse, paginarse y contarse.
Llevado al código eso termina en entidades que saben de sesiones, de `select()`
y de dialectos de SQL.

Y acá se nota más que en otros módulos: el Core corre sobre SQLite en las
pruebas y sobre PostgreSQL desplegado. Hay consultas que difieren entre los dos
—truncar una fecha a la hora, el tipo JSON— y no queríamos esa diferencia
desparramada por la lógica del hub.

## Decisión

Se fabrica una capa que **no corresponde a ningún concepto del dominio**: los
repositorios. No existe un "repositorio" en el municipio; existe porque
concentra el acceso a datos y deja a los servicios hablando de eventos y
entregas.

La regla, que es lo que le da valor:

- Los **repositorios** son el único lugar que construye queries.
- Los **servicios** reciben repositorios, no sesiones. Por eso no pueden
  escribir SQL ni saltarse la capa, aunque quieran.
- Los **routers** reciben servicios, no repositorios.

`BaseRepository` además resuelve una vez lo que todos repetirían —`paginate`,
`get_required`, `find_one`—, con las subclases aportando sólo la consulta
propia: es un Template Method dentro de la fabricación.

## Consecuencias

**A favor.** El hub se prueba sin base de verdad y las dos diferencias reales
entre motores quedaron encapsuladas: `JSONType` con su variante `JSONB`, y
`hourly_volume`, que agrupa en Python en vez de usar la función de truncado de
cada motor. Ningún servicio se enteró.

**En contra.** Hay más archivos y una consulta simple pasa por un método más.
Para un CRUD chico sería ceremonia; acá, con cuatro servicios compartiendo las
mismas entidades, paga.

**Lo verificado.** `grep -l sqlalchemy app/services/*.py` no devuelve nada y
`grep -l Repository app/api/v1/*.py` tampoco: la presentación habla con
servicios y la lógica no conoce el ORM. Si eso deja de ser cierto, la
fabricación se volvió decorativa.
