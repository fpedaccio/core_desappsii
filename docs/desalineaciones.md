# Desalineaciones de eventos entre equipos

> Generado cruzando el board de Miro con lo que el Core tiene cargado.
> Vista en vivo: `GET /api/v1/dashboard/integration-alerts`

El Core no valida reglas de negocio, pero **sí ve el mapa completo** de quién
declara publicar qué y quién declara consumir qué. Cruzando esas dos listas
aparecen los agujeros solos — antes de que alguien despliegue y descubra que el
evento no le llega.

Estas son las que hay hoy. **Ninguna se puede arreglar desde el Core**: son dos
equipos que le pusieron nombres distintos a la misma cosa, y lo tienen que
acordar entre ellos.

---

## A. El mismo evento con dos nombres

Alguien publica con un nombre y el otro escucha con otro. **El evento se publica,
entra al Core y no le llega a nadie.**

| Publica | Espera | Detalle |
|---|---|---|
| `debtOverdue` — rentas | `overdueDebt` — desarrollo-social | Palabras invertidas. |
| `streetClousureEnded` — transito | `streetClosureEnded` — obras | Typo en "Clousure". Ambiente consume la versión con typo, obras la correcta. |
| `commercialFineGenerated` — habilitaciones | `commercialFineIssued` — ambiente | "Generated" vs "Issued". |

**Acción:** que los dos equipos de cada fila elijan un nombre. El que cambie tiene
que actualizar su suscripción o su publicación en el dashboard.

---

## B. Un evento paraguas contra varios granulares

Un equipo publica un evento con el estado adentro del `data`, y el otro espera un
evento distinto por cada estado.

| Publica | Espera | Detalle |
|---|---|---|
| `closureUpdate` (`ORDERED` / `LIFTED`) — habilitaciones | `closureOrdered` y `violationDismissed` — ambiente | |
| `paymentRegistered`, `paymentReversed`, `debtSettled` — rentas | `paymentUpdated` — ciudadanos | Ciudadanos espera el paraguas, rentas manda los granulares. |
| `exemptionApproved`, `exemptionRejected` — rentas | `exemptionUpdated` — ciudadanos | Igual que el anterior. |

Lo mismo pasa con `permitUpdate` e `inspectionUpdate` de habilitaciones, que
llevan el estado adentro (`PROVISIONAL`, `APPROVED`, `SCHEDULED`…).

**Acción:** decidir un criterio y aplicarlo a todos. Las dos formas funcionan:

- **Paraguas** (`paymentUpdated` con un campo `status`): menos tipos, pero el
  consumidor tiene que mirar el `data` para saber si le interesa.
- **Granular** (`paymentApproved`, `paymentRejected`): el consumidor se suscribe
  solo a lo que le importa, y el Core no le entrega el resto.

Para un pasamanos la granular anda mejor: el filtrado lo hace el ruteo en vez del
consumidor. Pero lo importante es que sea uno de los dos, no una mezcla.

---

## C. Typos dentro de un mismo módulo

Ambiente tiene dos typos distintos en sus propios eventos:

| Nombre en el board | Debería ser |
|---|---|
| `enviromentalInspectionScheduled` | `environmentalInspectionScheduled` |
| `enviromentalInspectionCompleted` | `environmentalInspectionCompleted` |
| `envirometnalViolationDetected` | `environmentalViolationDetected` |

Nótese que son **dos typos diferentes**: `enviromental` (le falta la n) y
`envirometnal` (además tiene las letras invertidas).

**Acción:** los cargué tal como están en el board, porque corregirlos acá no
arreglaría nada — si ambiente publica `enviromental...` y el Core espera
`environmental...`, el evento tampoco encuentra destino. Que ambiente decida el
nombre y lo actualice en los dos lados.

---

## D. Eventos que nadie publica

Alguien está suscripto y esperando, pero ningún módulo declaró publicarlos.

| Evento | Lo espera | Probable causa |
|---|---|---|
| `overdueDebt` | desarrollo-social | Es el caso A: rentas publica `debtOverdue`. |
| `streetClosureEnded` | obras | Caso A: transito publica `streetClousureEnded`. |
| `commercialFineIssued` | ambiente | Caso A: habilitaciones publica `commercialFineGenerated`. |
| `closureOrdered` | ambiente | Caso B: habilitaciones publica `closureUpdate`. |
| `violationDismissed` | ambiente | Caso B. |
| `paymentUpdated` | ciudadanos | Caso B. |
| `exemptionUpdated` | ciudadanos | Caso B. |

---

## E. Eventos que nadie consume

Se declaran como publicados y ningún módulo está suscripto. Puede ser que
todavía no se necesiten, o que falte una suscripción.

`closureUpdate`, `containerOverflow`, `debtOverdue`,
`enviromentalInspectionScheduled`, `enviromentalInspectionCompleted`,
`eventRejected`, `infractionRegistered`, `infractionAnulled`,
`paymentPlanGranted`, `paymentPlanRejected`, `ticketInProgress`,
`trafficOperationCreated`, `urbanServiceStarted`, `urbanServiceDelayed`,
`urbanServiceCompleted`, `vehicleImpounded`, `vehicleReleased`,
`zoneNotServiced`

Algunos son claramente internos de su módulo (`trafficOperationCreated`,
`vehicleImpounded`) y está bien que nadie los consuma. Otros llaman la atención:
**`urbanServiceStarted/Delayed/Completed` los publica ambiente diciendo que van a
atención ciudadana, pero atención ciudadana no está suscripto a ninguno.**

**Acción:** que cada equipo revise su columna en el dashboard y confirme si falta
una suscripción del otro lado.

---

## F. Eventos que ya no existen

`notificationSent` y `notificationFailed` los declaran como consumidos rentas y
desarrollo-social. Los publicaba el módulo de notificaciones del Core, que
**quedó fuera del alcance**: el Core ahora es solo un pasamanos y no manda mails.

**Acción:** los dos equipos los pueden sacar de su lista de consumidos. Si
necesitan notificar a un ciudadano, tiene que salir del módulo que tiene el dato
de contacto.

---

## Resumen de lo que hay que acordar

| # | Quiénes | Qué |
|---|---|---|
| 1 | rentas ↔ desarrollo-social | `debtOverdue` o `overdueDebt` |
| 2 | transito ↔ obras ↔ ambiente | `streetClosureEnded` o `streetClousureEnded` |
| 3 | habilitaciones ↔ ambiente | `commercialFineGenerated` o `commercialFineIssued` |
| 4 | habilitaciones ↔ ambiente | `closureUpdate` paraguas, o `closureOrdered` + `violationDismissed` |
| 5 | rentas ↔ ciudadanos | `paymentUpdated` / `exemptionUpdated` paraguas, o los granulares |
| 6 | ambiente (interno) | los tres typos de `environmental` |
| 7 | ambiente ↔ atencion-ciudadana | ¿atención se suscribe a `urbanService*`? |
| 8 | rentas, desarrollo-social | sacar `notificationSent` / `notificationFailed` |

Los 6 primeros son de nombres y los detecta el Core solo. Los dos últimos salen de
leer el mapa.
