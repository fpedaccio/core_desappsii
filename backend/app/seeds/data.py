"""Datos iniciales del Core.

El catalogo de eventos y las suscripciones salen de las tablas "Posibles eventos
asincronicos" y "Flujo de informacion con otras areas" del enunciado. Sembrarlos
deja la plataforma lista para que los otros 8 equipos publiquen desde el primer
dia, y hace que `docs/catalogo-eventos.md` se genere con contenido real.

Los schemas se declaran con una notacion compacta y se expanden a JSON Schema
draft 2020-12:

    "reclamoId": "string!"                -> string requerido
    "afectados": "integer"                 -> integer opcional
    "prioridad": ["BAJA", "ALTA"]          -> enum opcional
    "estado!": ["ABIERTO", "CERRADO"]      -> enum requerido
"""

from __future__ import annotations

from typing import Any, NamedTuple

# ----------------------------------------------------------------------
# Modulos de la plataforma
# ----------------------------------------------------------------------
class ModuleSpec(NamedTuple):
    name: str
    display_name: str
    team: str
    description: str


MODULES: tuple[ModuleSpec, ...] = (
    ModuleSpec(
        "ciudadanos",
        "Ciudadanos, organizaciones y expedientes digitales",
        "Equipo 1",
        "Identidad municipal de ciudadanos y organizaciones, y expedientes digitales.",
    ),
    ModuleSpec(
        "atencion-ciudadana",
        "Atencion ciudadana, reclamos y solicitudes",
        "Equipo 2",
        "Recepcion, clasificacion, derivacion y seguimiento de reclamos.",
    ),
    ModuleSpec(
        "obras",
        "Obras publicas, infraestructura y mantenimiento urbano",
        "Equipo 3",
        "Proyectos de obra, ordenes de trabajo e intervenciones en el espacio publico.",
    ),
    ModuleSpec(
        "habilitaciones",
        "Habilitaciones, inspecciones y control comercial",
        "Equipo 4",
        "Establecimientos, habilitaciones, inspecciones, actas y clausuras.",
    ),
    ModuleSpec(
        "rentas",
        "Rentas, tributos, deudas y planes de pago",
        "Equipo 5",
        "Tasas, liquidaciones, pagos, intereses, exenciones y planes de regularizacion.",
    ),
    ModuleSpec(
        "ambiente",
        "Ambiente, higiene y servicios urbanos",
        "Equipo 6",
        "Recoleccion, limpieza, contenedores, arbolado y operativos ambientales.",
    ),
    ModuleSpec(
        "transito",
        "Transito, estacionamiento y seguridad vial",
        "Equipo 7",
        "Infracciones, operativos, accidentes, cortes de calle y estacionamiento medido.",
    ),
    ModuleSpec(
        "desarrollo-social",
        "Desarrollo social, salud comunitaria y beneficios",
        "Equipo 8",
        "Programas de asistencia, beneficios municipales, visitas sociales y turnos.",
    ),
)


# ----------------------------------------------------------------------
# Catalogo de eventos
# ----------------------------------------------------------------------
class EventSpec(NamedTuple):
    name: str
    owner: str
    description: str
    fields: dict[str, Any]


_CIUDADANO = {"ciudadanoId": "string!", "dni": "string", "nombreCompleto": "string", "email": "string"}
_RECLAMO = {"reclamoId": "string!", "categoria": "string", "ciudadanoId": "string"}

EVENT_TYPES: tuple[EventSpec, ...] = (
    # --- Ciudadanos ---------------------------------------------------
    EventSpec(
        "CiudadanoRegistrado",
        "ciudadanos",
        "Un ciudadano se registro. El Core provisiona su cuenta de acceso.",
        {**_CIUDADANO, "nombreCompleto": "string!"},
    ),
    EventSpec(
        "CiudadanoActualizado",
        "ciudadanos",
        "Cambiaron los datos de un ciudadano.",
        _CIUDADANO,
    ),
    EventSpec(
        "DomicilioActualizado",
        "ciudadanos",
        "Un ciudadano cambio su domicilio principal.",
        {"ciudadanoId": "string!", "domicilioId": "string", "barrio": "string", "esPrincipal": "boolean"},
    ),
    EventSpec(
        "OrganizacionRegistrada",
        "ciudadanos",
        "Se registro una empresa, comercio, asociacion o institucion.",
        {"organizacionId": "string!", "cuit": "string!", "razonSocial": "string!", "email": "string"},
    ),
    EventSpec(
        "RepresentacionOtorgada",
        "ciudadanos",
        "Un ciudadano quedo habilitado como representante de una organizacion.",
        {"organizacionId": "string!", "ciudadanoId": "string!", "vigenciaHasta": "string"},
    ),
    EventSpec(
        "DocumentacionSolicitada",
        "ciudadanos",
        "Se le pidio documentacion a un ciudadano u organizacion.",
        {"expedienteId": "string", "ciudadanoId": "string", "documentos": "array"},
    ),
    EventSpec(
        "ExpedienteIniciado",
        "ciudadanos",
        "Se abrio un expediente digital.",
        {"expedienteId": "string!", "tipo": "string", "areaOrigen": "string"},
    ),
    EventSpec(
        "ExpedienteResuelto",
        "ciudadanos",
        "Se resolvio un expediente digital.",
        {"expedienteId": "string!", "resultado!": ["APROBADO", "RECHAZADO", "ARCHIVADO"]},
    ),
    # --- Atencion ciudadana -------------------------------------------
    EventSpec(
        "ReclamoCreado",
        "atencion-ciudadana",
        "Un vecino presento un reclamo, solicitud o denuncia.",
        {**_RECLAMO, "categoria": "string!", "ubicacion": "object", "urgencia": ["BAJA", "MEDIA", "ALTA"]},
    ),
    EventSpec(
        "ReclamoClasificado",
        "atencion-ciudadana",
        "Se clasifico un reclamo y se calculo su prioridad inicial.",
        {**_RECLAMO, "subcategoria": "string", "prioridad": ["BAJA", "MEDIA", "ALTA", "CRITICA"]},
    ),
    EventSpec(
        "ReclamoDuplicadoDetectado",
        "atencion-ciudadana",
        "Se detecto un reclamo duplicado y se lo asocio a un caso principal.",
        {"reclamoId": "string!", "casoPrincipalId": "string!"},
    ),
    EventSpec(
        "ReclamoDerivado",
        "atencion-ciudadana",
        "Un reclamo se derivo al area responsable de resolverlo.",
        {**_RECLAMO, "areaDestino": "string!", "prioridad": ["BAJA", "MEDIA", "ALTA", "CRITICA"]},
    ),
    EventSpec(
        "ReclamoAsignado",
        "atencion-ciudadana",
        "Un reclamo se asigno a un responsable.",
        {"reclamoId": "string!", "responsable": "string", "areaDestino": "string"},
    ),
    EventSpec(
        "ReclamoEscalado",
        "atencion-ciudadana",
        "Un reclamo se escalo por criticidad o por vencimiento de su SLA.",
        {"reclamoId": "string!", "motivo": "string", "areaDestino": "string"},
    ),
    EventSpec(
        "ReclamoVencido",
        "atencion-ciudadana",
        "Vencio el plazo de atencion de un reclamo.",
        {"reclamoId": "string!", "vencidoDesde": "string"},
    ),
    EventSpec(
        "ReclamoResuelto",
        "atencion-ciudadana",
        "Se registro la solucion de un reclamo.",
        {**_RECLAMO, "solucion": "string", "email": "string"},
    ),
    EventSpec(
        "ReclamoCerrado",
        "atencion-ciudadana",
        "Se cerro un reclamo con solucion o con motivo de rechazo.",
        {"reclamoId": "string!", "motivoCierre": "string", "ciudadanoId": "string"},
    ),
    EventSpec(
        "ReclamoReabierto",
        "atencion-ciudadana",
        "Se reabrio un reclamo cerrado.",
        {"reclamoId": "string!", "motivo": "string"},
    ),
    EventSpec(
        "InformacionAdicionalSolicitada",
        "atencion-ciudadana",
        "Se le pidio informacion adicional al ciudadano.",
        {"reclamoId": "string!", "ciudadanoId": "string", "detalle": "string", "email": "string"},
    ),
    # --- Obras ---------------------------------------------------------
    EventSpec(
        "ProyectoObraCreado",
        "obras",
        "Se creo un proyecto de obra.",
        {"proyectoId": "string!", "alcance": "string", "presupuesto": "number"},
    ),
    EventSpec(
        "ObraAprobada",
        "obras",
        "Se aprobo un proyecto de obra.",
        {"proyectoId": "string!", "expedienteId": "string"},
    ),
    EventSpec(
        "ObraIniciada", "obras", "Comenzo la ejecucion de una obra.", {"proyectoId": "string!"}
    ),
    EventSpec(
        "ObraSuspendida",
        "obras",
        "Se suspendio una obra en ejecucion.",
        {"proyectoId": "string!", "motivo": "string"},
    ),
    EventSpec(
        "ObraProgramada",
        "obras",
        "Se programo una obra en la via publica.",
        {"proyectoId": "string!", "desde": "string", "hasta": "string"},
    ),
    EventSpec(
        "AvanceObraRegistrado",
        "obras",
        "Se registro avance fisico o presupuestario.",
        {"proyectoId": "string!", "avancePorcentaje": "number"},
    ),
    EventSpec(
        "ObraFinalizada",
        "obras",
        "Se finalizo una obra.",
        {"proyectoId": "string!", "expedienteId": "string"},
    ),
    EventSpec(
        "OrdenTrabajoCreada",
        "obras",
        "Se creo una orden de trabajo, manual o a partir de un reclamo.",
        {"ordenId": "string!", "reclamoId": "string", "tipoIntervencion": "string"},
    ),
    EventSpec(
        "OrdenTrabajoAsignada",
        "obras",
        "Se asigno una cuadrilla a una orden de trabajo.",
        {"ordenId": "string!", "cuadrilla": "string"},
    ),
    EventSpec(
        "OrdenTrabajoIniciada", "obras", "Comenzo la ejecucion de una orden.", {"ordenId": "string!"}
    ),
    EventSpec(
        "OrdenTrabajoDemorada",
        "obras",
        "Una orden de trabajo se demoro respecto de lo programado.",
        {"ordenId": "string!", "motivo": "string"},
    ),
    EventSpec(
        "OrdenTrabajoFinalizada",
        "obras",
        "Se finalizo una orden de trabajo con su evidencia.",
        {"ordenId": "string!", "reclamoId": "string", "resultado": "string"},
    ),
    EventSpec(
        "CorteCalleSolicitado",
        "obras",
        "Obras pide autorizacion a Transito para cortar una calle.",
        {"solicitudId": "string!", "calle": "string!", "desde": "string", "hasta": "string"},
    ),
    EventSpec(
        "RiesgoUrbanoDetectado",
        "obras",
        "Se detecto una situacion de riesgo en el espacio publico.",
        {"ubicacion": "object", "descripcion": "string", "nivel": ["BAJO", "MEDIO", "ALTO"]},
    ),
    # --- Habilitaciones -----------------------------------------------
    EventSpec(
        "SolicitudHabilitacionIniciada",
        "habilitaciones",
        "Se inicio una solicitud de habilitacion comercial.",
        {"solicitudId": "string!", "organizacionId": "string", "rubro": "string"},
    ),
    EventSpec(
        "DocumentacionHabilitacionObservada",
        "habilitaciones",
        "Falta o esta observada la documentacion de una solicitud.",
        {"solicitudId": "string!", "observaciones": "array", "email": "string"},
    ),
    EventSpec(
        "InspeccionProgramada",
        "habilitaciones",
        "Se programo una inspeccion y se asigno un inspector.",
        {"inspeccionId": "string!", "solicitudId": "string", "fecha": "string"},
    ),
    EventSpec(
        "InspeccionRealizada",
        "habilitaciones",
        "Se realizo una inspeccion y se registro su resultado.",
        {"inspeccionId": "string!", "resultado!": ["FAVORABLE", "DESFAVORABLE", "CON_OBSERVACIONES"]},
    ),
    EventSpec(
        "InspeccionDesfavorable",
        "habilitaciones",
        "Una inspeccion resulto desfavorable e impide la aprobacion.",
        {"inspeccionId": "string!", "incumplimientos": "array"},
    ),
    EventSpec(
        "HabilitacionProvisoriaOtorgada",
        "habilitaciones",
        "Se otorgo una habilitacion provisoria.",
        {"habilitacionId": "string!", "organizacionId": "string", "vigenciaHasta": "string"},
    ),
    EventSpec(
        "HabilitacionAprobada",
        "habilitaciones",
        "Se aprobo una habilitacion definitiva.",
        {"habilitacionId": "string!", "organizacionId": "string", "email": "string"},
    ),
    EventSpec(
        "HabilitacionRechazada",
        "habilitaciones",
        "Se rechazo una solicitud de habilitacion con fundamento.",
        {"solicitudId": "string!", "motivo": "string!", "email": "string"},
    ),
    EventSpec(
        "HabilitacionSuspendida",
        "habilitaciones",
        "Se suspendio una habilitacion vigente.",
        {"habilitacionId": "string!", "motivo": "string"},
    ),
    EventSpec(
        "HabilitacionVencida",
        "habilitaciones",
        "Vencio una habilitacion: el comercio no puede operar.",
        {"habilitacionId": "string!", "vencioEl": "string"},
    ),
    EventSpec(
        "ClausuraDispuesta",
        "habilitaciones",
        "Se dispuso una clausura asociada a un acta.",
        {"clausuraId": "string!", "actaId": "string!", "establecimientoId": "string"},
    ),
    EventSpec(
        "ClausuraLevantada",
        "habilitaciones",
        "Se levanto una clausura.",
        {"clausuraId": "string!"},
    ),
    EventSpec(
        "TasaHabilitacionGenerada",
        "habilitaciones",
        "Se genero la tasa de una habilitacion, para que Rentas liquide.",
        {"solicitudId": "string!", "contribuyenteId": "string!", "importe": "number!"},
    ),
    EventSpec(
        "MultaComercialGenerada",
        "habilitaciones",
        "Se genero una multa comercial, para que Rentas la cobre.",
        {"multaId": "string!", "contribuyenteId": "string!", "importe": "number!"},
    ),
    # --- Rentas --------------------------------------------------------
    EventSpec(
        "LiquidacionGenerada",
        "rentas",
        "Se genero una liquidacion de tributos.",
        {"liquidacionId": "string!", "contribuyenteId": "string!", "importe": "number!"},
    ),
    EventSpec(
        "BoletaEmitida",
        "rentas",
        "Se emitio una boleta de pago.",
        {"boletaId": "string!", "contribuyenteId": "string!", "vencimiento": "string", "email": "string"},
    ),
    EventSpec(
        "DeudaGenerada",
        "rentas",
        "Se registro una deuda a nombre de un contribuyente.",
        {"deudaId": "string!", "contribuyenteId": "string!", "importe": "number!"},
    ),
    EventSpec(
        "DeudaVencida",
        "rentas",
        "Vencio una deuda sin pago.",
        {"deudaId": "string!", "contribuyenteId": "string!", "importe": "number", "email": "string"},
    ),
    EventSpec(
        "PagoRegistrado",
        "rentas",
        "Se registro un pago. Lo consumen Habilitaciones y Transito.",
        {"pagoId": "string!", "contribuyenteId": "string!", "importe": "number!", "referencia": "string"},
    ),
    EventSpec(
        "PagoRevertido",
        "rentas",
        "Se revirtio un pago con autorizacion.",
        {"pagoId": "string!", "motivo": "string"},
    ),
    EventSpec(
        "DeudaCancelada",
        "rentas",
        "Se cancelo una deuda por completo.",
        {"deudaId": "string!", "contribuyenteId": "string!"},
    ),
    EventSpec(
        "PlanPagoSolicitado",
        "rentas",
        "Un contribuyente solicito un plan de pago.",
        {"planId": "string!", "contribuyenteId": "string!", "cuotas": "integer"},
    ),
    EventSpec(
        "PlanPagoOtorgado",
        "rentas",
        "Se otorgo un plan de pago.",
        {"planId": "string!", "contribuyenteId": "string!", "cuotas": "integer", "email": "string"},
    ),
    EventSpec(
        "PlanPagoIncumplido",
        "rentas",
        "Un plan de pago cayo en incumplimiento.",
        {"planId": "string!", "contribuyenteId": "string!"},
    ),
    EventSpec(
        "ExencionSolicitada",
        "rentas",
        "Se solicito una exencion tributaria.",
        {"exencionId": "string!", "contribuyenteId": "string!"},
    ),
    EventSpec(
        "ExencionAprobada",
        "rentas",
        "Se aprobo una exencion tributaria.",
        {"exencionId": "string!", "contribuyenteId": "string!", "email": "string"},
    ),
    EventSpec(
        "ExencionRechazada",
        "rentas",
        "Se rechazo una exencion tributaria.",
        {"exencionId": "string!", "motivo": "string"},
    ),
    EventSpec(
        "SaldoFavorGenerado",
        "rentas",
        "Se genero un saldo a favor del contribuyente.",
        {"contribuyenteId": "string!", "importe": "number!"},
    ),
    # --- Ambiente ------------------------------------------------------
    EventSpec(
        "ServicioUrbanoProgramado",
        "ambiente",
        "Se programo un servicio urbano en una zona.",
        {"servicioId": "string!", "zona": "string!", "tipo": "string"},
    ),
    EventSpec(
        "ServicioUrbanoIniciado", "ambiente", "Comenzo un servicio urbano.", {"servicioId": "string!"}
    ),
    EventSpec(
        "ServicioUrbanoDemorado",
        "ambiente",
        "Un servicio urbano se demoro por clima o indisponibilidad.",
        {"servicioId": "string!", "motivo": "string"},
    ),
    EventSpec(
        "ServicioUrbanoFinalizado",
        "ambiente",
        "Se finalizo un servicio urbano.",
        {"servicioId": "string!", "reclamoId": "string", "resultado": "string"},
    ),
    EventSpec(
        "ZonaNoAtendida",
        "ambiente",
        "Una zona quedo sin atender en un recorrido.",
        {"servicioId": "string!", "zona": "string!", "motivo": "string"},
    ),
    EventSpec(
        "ContenedorDesbordado",
        "ambiente",
        "Se detecto un contenedor desbordado.",
        {"contenedorId": "string!", "ubicacion": "object"},
    ),
    EventSpec(
        "ContenedorDanado",
        "ambiente",
        "Se detecto un contenedor danado.",
        {"contenedorId": "string!", "detalle": "string"},
    ),
    EventSpec(
        "RiesgoArboladoDetectado",
        "ambiente",
        "Se detecto un arbol con riesgo alto: requiere intervencion urgente.",
        {"arbolId": "string!", "nivel!": ["MEDIO", "ALTO"], "ubicacion": "object"},
    ),
    EventSpec(
        "PodaProgramada",
        "ambiente",
        "Se programo una poda, extraccion o tratamiento.",
        {"arbolId": "string!", "fecha": "string"},
    ),
    EventSpec(
        "IncumplimientoAmbientalDetectado",
        "ambiente",
        "Se detecto un incumplimiento ambiental de un comercio.",
        {"establecimientoId": "string", "detalle": "string!", "actaId": "string"},
    ),
    EventSpec(
        "ServicioUrbanoSolicitaReparacion",
        "ambiente",
        "Ambiente pide a Obras una reparacion de infraestructura.",
        {"solicitudId": "string!", "ubicacion": "object", "detalle": "string"},
    ),
    EventSpec(
        "AlertaMeteorologicaRecibida",
        "ambiente",
        "Se recibio una alerta meteorologica simulada.",
        {"alertaId": "string!", "severidad": ["BAJA", "MEDIA", "ALTA"]},
    ),
    # --- Transito ------------------------------------------------------
    EventSpec(
        "InfraccionRegistrada",
        "transito",
        "Se registro una infraccion con su evidencia.",
        {"infraccionId": "string!", "dominio": "string!", "tipo": "string", "importe": "number"},
    ),
    EventSpec(
        "InfraccionApelada",
        "transito",
        "El ciudadano presento un descargo: la infraccion no queda firme.",
        {"infraccionId": "string!", "ciudadanoId": "string", "descargo": "string"},
    ),
    EventSpec(
        "InfraccionConfirmada",
        "transito",
        "La infraccion quedo firme. Solo estas llegan a Rentas.",
        {"infraccionId": "string!", "contribuyenteId": "string!", "importe": "number!"},
    ),
    EventSpec(
        "InfraccionAnulada",
        "transito",
        "Se anulo una infraccion con autorizacion.",
        {"infraccionId": "string!", "motivo": "string!"},
    ),
    EventSpec(
        "OperativoTransitoCreado",
        "transito",
        "Se creo un operativo de control.",
        {"operativoId": "string!", "ubicacion": "object", "fecha": "string"},
    ),
    EventSpec(
        "AccidenteVialRegistrado",
        "transito",
        "Se registro un accidente vial.",
        {"accidenteId": "string!", "ubicacion": "object", "gravedad": ["LEVE", "GRAVE", "FATAL"]},
    ),
    EventSpec(
        "IncidenteVialRegistrado",
        "transito",
        "Se registro un incidente vial con dano de infraestructura.",
        {"incidenteId": "string!", "ubicacion": "object"},
    ),
    EventSpec(
        "IncidenteTransitoAtendido",
        "transito",
        "Se atendio un incidente de transito.",
        {"incidenteId": "string!", "reclamoId": "string", "resultado": "string"},
    ),
    EventSpec(
        "CorteCalleAutorizado",
        "transito",
        "Transito autorizo un corte de calle y definio los desvios.",
        {"solicitudId": "string!", "desvios": "array", "desde": "string", "hasta": "string"},
    ),
    EventSpec(
        "CorteCalleRechazado",
        "transito",
        "Transito rechazo una solicitud de corte.",
        {"solicitudId": "string!", "motivo": "string!"},
    ),
    EventSpec(
        "CorteCalleActivado", "transito", "Se activo un corte de calle.", {"solicitudId": "string!"}
    ),
    EventSpec(
        "CorteCalleFinalizado",
        "transito",
        "Se finalizo un corte de calle.",
        {"solicitudId": "string!"},
    ),
    EventSpec(
        "VehiculoRetenido",
        "transito",
        "Se retuvo un vehiculo y se registro su ingreso al deposito.",
        {"dominio": "string!", "depositoId": "string", "motivo": "string"},
    ),
    EventSpec(
        "VehiculoLiberado",
        "transito",
        "Se libero un vehiculo retenido con los requisitos cumplidos.",
        {"dominio": "string!", "importeAcarreo": "number"},
    ),
    # --- Desarrollo social --------------------------------------------
    EventSpec(
        "ProgramaSocialCreado",
        "desarrollo-social",
        "Se creo un programa social con requisitos y cupos.",
        {"programaId": "string!", "nombre": "string!", "cupos": "integer"},
    ),
    EventSpec(
        "SolicitudBeneficioSocialCreada",
        "desarrollo-social",
        "Se registro una solicitud de beneficio social.",
        {"solicitudId": "string!", "ciudadanoId": "string!", "programaId": "string"},
    ),
    EventSpec(
        "DocumentacionSocialSolicitada",
        "desarrollo-social",
        "Se pidio documentacion faltante para una solicitud social.",
        {"solicitudId": "string!", "ciudadanoId": "string", "documentos": "array", "email": "string"},
    ),
    EventSpec(
        "VisitaSocialProgramada",
        "desarrollo-social",
        "Se programo una visita domiciliaria o entrevista.",
        {"visitaId": "string!", "ciudadanoId": "string!", "fecha": "string", "email": "string"},
    ),
    EventSpec(
        "VisitaSocialRealizada",
        "desarrollo-social",
        "Se realizo la visita social y se registro la evaluacion.",
        {"visitaId": "string!", "vulnerabilidad": ["BAJA", "MEDIA", "ALTA", "CRITICA"]},
    ),
    EventSpec(
        "BeneficioSocialAprobado",
        "desarrollo-social",
        "Se aprobo un beneficio social. Rentas lo usa para exenciones.",
        {"beneficioId": "string!", "ciudadanoId": "string!", "programaId": "string", "email": "string"},
    ),
    EventSpec(
        "BeneficioSocialRechazado",
        "desarrollo-social",
        "Se rechazo una solicitud de beneficio social.",
        {"solicitudId": "string!", "motivo": "string!", "email": "string"},
    ),
    EventSpec(
        "BeneficioSocialSuspendido",
        "desarrollo-social",
        "Se suspendio un beneficio social.",
        {"beneficioId": "string!", "motivo": "string"},
    ),
    EventSpec(
        "BeneficioSocialFinalizado",
        "desarrollo-social",
        "Finalizo la vigencia de un beneficio social.",
        {"beneficioId": "string!"},
    ),
    EventSpec(
        "TurnoSaludMunicipalOtorgado",
        "desarrollo-social",
        "Se otorgo un turno en un centro municipal de salud.",
        {"turnoId": "string!", "ciudadanoId": "string!", "fecha": "string", "email": "string"},
    ),
    EventSpec(
        "AtencionComunitariaRegistrada",
        "desarrollo-social",
        "Se registro una atencion comunitaria.",
        {"atencionId": "string!", "ciudadanoId": "string"},
    ),
    EventSpec(
        "SituacionVulnerabilidadCriticaDetectada",
        "desarrollo-social",
        "Se detecto una situacion de vulnerabilidad critica.",
        {"ciudadanoId": "string!", "detalle": "string"},
    ),
    # --- Core ----------------------------------------------------------
    EventSpec(
        "NotificacionEnviada",
        "core",
        "El Core envio una notificacion. Lo consumen los modulos que la originaron.",
        {
            "notificationId": "string!",
            "channel!": ["EMAIL", "IN_APP", "SMS", "PUSH"],
            "recipient": "string!",
            "originEventId": "string",
            "originEventType": "string",
            "templateCode": "string",
            "status": "string",
            "error": "null_string",
        },
    ),
    EventSpec(
        "NotificacionFallida",
        "core",
        "El Core no pudo enviar una notificacion.",
        {
            "notificationId": "string!",
            "channel!": ["EMAIL", "IN_APP", "SMS", "PUSH"],
            "recipient": "string!",
            "originEventId": "string",
            "originEventType": "string",
            "templateCode": "string",
            "status": "string",
            "error": "null_string",
        },
    ),
)


# ----------------------------------------------------------------------
# Suscripciones iniciales (tabla "Eventos que consume" del enunciado)
# ----------------------------------------------------------------------
SUBSCRIPTIONS: dict[str, tuple[str, ...]] = {
    "ciudadanos": (
        "ReclamoCreado",
        "ReclamoResuelto",
        "SolicitudHabilitacionIniciada",
        "HabilitacionAprobada",
        "PlanPagoSolicitado",
        "ExencionSolicitada",
        "ObraAprobada",
        "BeneficioSocialAprobado",
        "InfraccionApelada",
    ),
    "atencion-ciudadana": (
        "OrdenTrabajoCreada",
        "OrdenTrabajoIniciada",
        "OrdenTrabajoFinalizada",
        "InspeccionProgramada",
        "InspeccionRealizada",
        "ServicioUrbanoProgramado",
        "ServicioUrbanoFinalizado",
        "CorteCalleFinalizado",
        "IncidenteTransitoAtendido",
        "BeneficioSocialAprobado",
        "NotificacionEnviada",
        "NotificacionFallida",
    ),
    "obras": (
        "ReclamoDerivado",
        "ReclamoEscalado",
        "RiesgoUrbanoDetectado",
        "IncidenteVialRegistrado",
        "ServicioUrbanoSolicitaReparacion",
        "CorteCalleAutorizado",
        "CorteCalleRechazado",
        "ExpedienteResuelto",
    ),
    "habilitaciones": (
        "OrganizacionRegistrada",
        "RepresentacionOtorgada",
        "PagoRegistrado",
        "DeudaCancelada",
        "ReclamoDerivado",
        "IncumplimientoAmbientalDetectado",
        "ExpedienteIniciado",
        "NotificacionEnviada",
    ),
    "rentas": (
        "CiudadanoRegistrado",
        "OrganizacionRegistrada",
        "TasaHabilitacionGenerada",
        "MultaComercialGenerada",
        "InfraccionConfirmada",
        "InfraccionAnulada",
        "BeneficioSocialAprobado",
        "HabilitacionSuspendida",
    ),
    "ambiente": (
        "ReclamoDerivado",
        "ReclamoEscalado",
        "OrdenTrabajoFinalizada",
        "CorteCalleAutorizado",
        "CorteCalleFinalizado",
        "AlertaMeteorologicaRecibida",
        "NotificacionEnviada",
    ),
    "transito": (
        "CorteCalleSolicitado",
        "ObraProgramada",
        "ObraFinalizada",
        "ServicioUrbanoProgramado",
        "PagoRegistrado",
        "DeudaCancelada",
        "ReclamoDerivado",
        "ExpedienteResuelto",
    ),
    "desarrollo-social": (
        "CiudadanoRegistrado",
        "DomicilioActualizado",
        "ReclamoDerivado",
        "ExpedienteIniciado",
        "DeudaVencida",
        "ExencionAprobada",
        "NotificacionEnviada",
        "NotificacionFallida",
    ),
}


# ----------------------------------------------------------------------
# Catalogos globales
# ----------------------------------------------------------------------
DEPENDENCIAS: tuple[tuple[str, str], ...] = (
    ("INTENDENCIA", "Intendencia"),
    ("ATENCION_CIUDADANA", "Atencion Ciudadana"),
    ("OBRAS_PUBLICAS", "Obras Publicas e Infraestructura"),
    ("HABILITACIONES", "Habilitaciones y Control Comercial"),
    ("RENTAS", "Rentas y Tributos"),
    ("AMBIENTE", "Ambiente, Higiene y Servicios Urbanos"),
    ("TRANSITO", "Transito y Seguridad Vial"),
    ("DESARROLLO_SOCIAL", "Desarrollo Social y Salud Comunitaria"),
    ("SISTEMAS", "Sistemas y Modernizacion"),
)

ZONAS: tuple[tuple[str, str], ...] = (
    ("ZONA_NORTE", "Zona Norte"),
    ("ZONA_SUR", "Zona Sur"),
    ("ZONA_ESTE", "Zona Este"),
    ("ZONA_OESTE", "Zona Oeste"),
    ("ZONA_CENTRO", "Zona Centro"),
)

BARRIOS: tuple[tuple[str, str, str, str], ...] = (
    ("CENTRO", "Centro", "ZONA_CENTRO", "1000"),
    ("PARQUE_NORTE", "Parque Norte", "ZONA_NORTE", "1010"),
    ("VILLA_UNION", "Villa Union", "ZONA_NORTE", "1012"),
    ("SAN_MARTIN", "San Martin", "ZONA_SUR", "1020"),
    ("LOS_TILOS", "Los Tilos", "ZONA_SUR", "1022"),
    ("LA_RIBERA", "La Ribera", "ZONA_ESTE", "1030"),
    ("EL_MIRADOR", "El Mirador", "ZONA_ESTE", "1032"),
    ("SANTA_ROSA", "Santa Rosa", "ZONA_OESTE", "1040"),
    ("LOMAS_DEL_OESTE", "Lomas del Oeste", "ZONA_OESTE", "1042"),
    ("INDUSTRIAL", "Distrito Industrial", "ZONA_OESTE", "1044"),
)

CATALOGS: tuple[tuple[str, str, str, tuple[tuple[str, str, dict], ...]], ...] = (
    (
        "CATEGORIA_RECLAMO",
        "Categorias de reclamo",
        "atencion-ciudadana",
        (
            ("INFRAESTRUCTURA", "Infraestructura y via publica", {"areaDestino": "obras", "slaHoras": 72}),
            ("AMBIENTE", "Ambiente e higiene urbana", {"areaDestino": "ambiente", "slaHoras": 48}),
            ("TRANSITO", "Transito y seguridad vial", {"areaDestino": "transito", "slaHoras": 24}),
            ("COMERCIAL", "Denuncias comerciales", {"areaDestino": "habilitaciones", "slaHoras": 96}),
            ("SOCIAL", "Asistencia social", {"areaDestino": "desarrollo-social", "slaHoras": 48}),
            ("TRIBUTARIO", "Consultas tributarias", {"areaDestino": "rentas", "slaHoras": 72}),
        ),
    ),
    (
        "PRIORIDAD",
        "Niveles de prioridad",
        "core",
        (
            ("BAJA", "Baja", {"peso": 1}),
            ("MEDIA", "Media", {"peso": 2}),
            ("ALTA", "Alta", {"peso": 3}),
            ("CRITICA", "Critica", {"peso": 4, "escalaAutomaticamente": True}),
        ),
    ),
    (
        "CANAL_ATENCION",
        "Canales de atencion al ciudadano",
        "atencion-ciudadana",
        (
            ("WEB", "Portal web", {}),
            ("MOBILE", "Aplicacion mobile", {}),
            ("TELEFONICO", "Call center", {}),
            ("PRESENCIAL", "Mesa de entradas", {}),
        ),
    ),
    (
        "RUBRO_COMERCIAL",
        "Rubros comerciales",
        "habilitaciones",
        (
            ("GASTRONOMIA", "Gastronomia", {"riesgo": "ALTO", "requiereInspeccionPrevia": True}),
            ("ALMACEN", "Almacen y autoservicio", {"riesgo": "MEDIO"}),
            ("INDUMENTARIA", "Indumentaria", {"riesgo": "BAJO"}),
            ("TALLER", "Taller mecanico", {"riesgo": "ALTO", "requiereInspeccionPrevia": True}),
            ("OFICINA", "Oficina de servicios", {"riesgo": "BAJO"}),
        ),
    ),
)


# ----------------------------------------------------------------------
# Notificaciones
# ----------------------------------------------------------------------
class TemplateSpec(NamedTuple):
    code: str
    name: str
    channel: str
    subject: str
    body: str


TEMPLATES: tuple[TemplateSpec, ...] = (
    TemplateSpec(
        "RECLAMO_RESUELTO_EMAIL",
        "Reclamo resuelto (email al ciudadano)",
        "EMAIL",
        "Tu reclamo {{ data.reclamoId }} fue resuelto",
        "Hola,\n\n"
        "Te informamos que el reclamo {{ data.reclamoId }} fue resuelto.\n"
        "{% if data.solucion %}Solucion registrada: {{ data.solucion }}\n{% endif %}"
        "Fecha: {{ occurredAt }}\n\n"
        "Municipalidad de Ciudad UADE",
    ),
    TemplateSpec(
        "HABILITACION_APROBADA_EMAIL",
        "Habilitacion aprobada (email al comercio)",
        "EMAIL",
        "Habilitacion {{ data.habilitacionId }} aprobada",
        "Hola,\n\n"
        "Tu habilitacion {{ data.habilitacionId }} fue aprobada el {{ occurredAt }}.\n\n"
        "Municipalidad de Ciudad UADE",
    ),
    TemplateSpec(
        "DEUDA_VENCIDA_EMAIL",
        "Deuda vencida (aviso al contribuyente)",
        "EMAIL",
        "Tenes una deuda vencida",
        "Hola,\n\n"
        "La deuda {{ data.deudaId }}"
        "{% if data.importe %} por ${{ data.importe }}{% endif %} se encuentra vencida.\n"
        "Podes regularizarla solicitando un plan de pago.\n\n"
        "Municipalidad de Ciudad UADE",
    ),
    TemplateSpec(
        "BENEFICIO_APROBADO_EMAIL",
        "Beneficio social aprobado",
        "EMAIL",
        "Tu solicitud de beneficio fue aprobada",
        "Hola,\n\n"
        "Tu beneficio {{ data.beneficioId }} fue aprobado el {{ occurredAt }}.\n"
        "Te vamos a contactar con los proximos pasos.\n\n"
        "Municipalidad de Ciudad UADE",
    ),
    TemplateSpec(
        "TURNO_OTORGADO_EMAIL",
        "Turno de salud otorgado",
        "EMAIL",
        "Turno confirmado para el {{ data.fecha }}",
        "Hola,\n\n"
        "Tu turno {{ data.turnoId }} quedo confirmado para el {{ data.fecha }}.\n\n"
        "Municipalidad de Ciudad UADE",
    ),
    TemplateSpec(
        "RIESGO_ARBOLADO_INTERNO",
        "Riesgo de arbolado (aviso interno)",
        "IN_APP",
        "Riesgo de arbolado nivel {{ data.nivel }}",
        "Se detecto un arbol con riesgo {{ data.nivel }} (id {{ data.arbolId }}). "
        "Requiere intervencion urgente.",
    ),
    TemplateSpec(
        "VULNERABILIDAD_CRITICA_INTERNO",
        "Vulnerabilidad critica (aviso interno)",
        "IN_APP",
        "Situacion de vulnerabilidad critica detectada",
        "Se detecto una situacion critica para el ciudadano {{ data.ciudadanoId }}. "
        "{{ data.detalle }}",
    ),
)


class RuleSpec(NamedTuple):
    event_type: str
    template_code: str
    recipient_source: str
    recipient_expression: str


NOTIFICATION_RULES: tuple[RuleSpec, ...] = (
    RuleSpec("ReclamoResuelto", "RECLAMO_RESUELTO_EMAIL", "PAYLOAD_FIELD", "email"),
    RuleSpec("HabilitacionAprobada", "HABILITACION_APROBADA_EMAIL", "PAYLOAD_FIELD", "email"),
    RuleSpec("DeudaVencida", "DEUDA_VENCIDA_EMAIL", "PAYLOAD_FIELD", "email"),
    RuleSpec("BeneficioSocialAprobado", "BENEFICIO_APROBADO_EMAIL", "PAYLOAD_FIELD", "email"),
    RuleSpec("TurnoSaludMunicipalOtorgado", "TURNO_OTORGADO_EMAIL", "PAYLOAD_FIELD", "email"),
    # Avisos internos por rol: no necesitan un email en el payload.
    RuleSpec("RiesgoArboladoDetectado", "RIESGO_ARBOLADO_INTERNO", "ROLE", "OPERADOR_TECNICO"),
    RuleSpec(
        "SituacionVulnerabilidadCriticaDetectada",
        "VULNERABILIDAD_CRITICA_INTERNO",
        "ROLE",
        "OPERADOR_TECNICO",
    ),
)


# ----------------------------------------------------------------------
# Expansion de la notacion compacta a JSON Schema
# ----------------------------------------------------------------------
_TYPE_MAP = {
    "string": {"type": "string"},
    "integer": {"type": "integer"},
    "number": {"type": "number"},
    "boolean": {"type": "boolean"},
    "object": {"type": "object"},
    "array": {"type": "array"},
    "null_string": {"type": ["string", "null"]},
}


def build_json_schema(fields: dict[str, Any]) -> dict[str, Any]:
    """Expande la notacion compacta de `EventSpec.fields` a JSON Schema.

    `additionalProperties` queda en `true` a proposito: los modulos pueden
    enriquecer su payload sin romper a los consumidores. Cerrarlo convertiria
    cualquier campo nuevo en un cambio incompatible.
    """
    properties: dict[str, Any] = {}
    required: list[str] = []

    for raw_name, spec in fields.items():
        name = raw_name.rstrip("!")
        is_required = raw_name.endswith("!")

        if isinstance(spec, list):
            properties[name] = {"type": "string", "enum": list(spec)}
        else:
            text = str(spec)
            if text.endswith("!"):
                is_required = True
                text = text[:-1]
            properties[name] = dict(_TYPE_MAP.get(text, {"type": "string"}))

        if is_required:
            required.append(name)

    schema: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": properties,
        "additionalProperties": True,
    }
    if required:
        schema["required"] = sorted(required)
    return schema


def build_example(fields: dict[str, Any]) -> dict[str, Any]:
    """Ejemplo valido para la documentacion del catalogo."""
    example: dict[str, Any] = {}
    for raw_name, spec in fields.items():
        name = raw_name.rstrip("!")
        if isinstance(spec, list):
            example[name] = spec[0]
            continue
        text = str(spec).rstrip("!")
        if text == "integer":
            example[name] = 1
        elif text == "number":
            example[name] = 1000.0
        elif text == "boolean":
            example[name] = True
        elif text == "object":
            example[name] = {"barrio": "CENTRO", "calle": "Av. Siempre Viva 742"}
        elif text == "array":
            example[name] = ["ejemplo"]
        elif text == "null_string":
            example[name] = None
        else:
            example[name] = f"{name}-ejemplo"
    return example
