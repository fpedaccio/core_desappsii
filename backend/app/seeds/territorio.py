"""Catalogo territorial inicial: zonas y barrios, mas los catalogos globales.

**Barrios y comunas reales de la Ciudad Autonoma de Buenos Aires** (Ley 2650):
48 barrios agrupados en 15 comunas. Las `zonas` del catalogo son las comunas;
el `codigo` de cada barrio es el slug estable que viaja en el `data` de los
eventos, asi que no cambia aunque cambie el nombre mostrado.

Los nombres con acento o eñe van sin acentos en el `codigo` (es la regla de
slug: minusculas, numeros y guiones), pero el `nombre` mostrado los conserva:
`nunez` -> "Nuñez", `velez-sarsfield` -> "Velez Sarsfield".
"""

from __future__ import annotations

# Las "zonas" del catalogo son las 15 comunas de CABA. La descripcion es una
# referencia corta; los barrios que agrupa cada comuna estan en BARRIOS.
_C = "Comuna de la Ciudad Autonoma de Buenos Aires"
ZONAS: list[tuple[str, str, str]] = [
    ("comuna-1", "Comuna 1", _C),
    ("comuna-2", "Comuna 2", _C),
    ("comuna-3", "Comuna 3", _C),
    ("comuna-4", "Comuna 4", _C),
    ("comuna-5", "Comuna 5", _C),
    ("comuna-6", "Comuna 6", _C),
    ("comuna-7", "Comuna 7", _C),
    ("comuna-8", "Comuna 8", _C),
    ("comuna-9", "Comuna 9", _C),
    ("comuna-10", "Comuna 10", _C),
    ("comuna-11", "Comuna 11", _C),
    ("comuna-12", "Comuna 12", _C),
    ("comuna-13", "Comuna 13", _C),
    ("comuna-14", "Comuna 14", _C),
    ("comuna-15", "Comuna 15", _C),
]

# (codigo, nombre, comuna). Los 48 barrios oficiales de CABA.
BARRIOS: list[tuple[str, str, str]] = [
    ("retiro", "Retiro", "comuna-1"),
    ("san-nicolas", "San Nicolas", "comuna-1"),
    ("puerto-madero", "Puerto Madero", "comuna-1"),
    ("san-telmo", "San Telmo", "comuna-1"),
    ("montserrat", "Montserrat", "comuna-1"),
    ("constitucion", "Constitucion", "comuna-1"),
    ("recoleta", "Recoleta", "comuna-2"),
    ("balvanera", "Balvanera", "comuna-3"),
    ("san-cristobal", "San Cristobal", "comuna-3"),
    ("la-boca", "La Boca", "comuna-4"),
    ("barracas", "Barracas", "comuna-4"),
    ("parque-patricios", "Parque Patricios", "comuna-4"),
    ("nueva-pompeya", "Nueva Pompeya", "comuna-4"),
    ("almagro", "Almagro", "comuna-5"),
    ("boedo", "Boedo", "comuna-5"),
    ("caballito", "Caballito", "comuna-6"),
    ("flores", "Flores", "comuna-7"),
    ("parque-chacabuco", "Parque Chacabuco", "comuna-7"),
    ("villa-soldati", "Villa Soldati", "comuna-8"),
    ("villa-riachuelo", "Villa Riachuelo", "comuna-8"),
    ("villa-lugano", "Villa Lugano", "comuna-8"),
    ("liniers", "Liniers", "comuna-9"),
    ("mataderos", "Mataderos", "comuna-9"),
    ("parque-avellaneda", "Parque Avellaneda", "comuna-9"),
    ("villa-real", "Villa Real", "comuna-10"),
    ("monte-castro", "Monte Castro", "comuna-10"),
    ("versalles", "Versalles", "comuna-10"),
    ("floresta", "Floresta", "comuna-10"),
    ("velez-sarsfield", "Velez Sarsfield", "comuna-10"),
    ("villa-luro", "Villa Luro", "comuna-10"),
    ("villa-general-mitre", "Villa General Mitre", "comuna-11"),
    ("villa-devoto", "Villa Devoto", "comuna-11"),
    ("villa-del-parque", "Villa del Parque", "comuna-11"),
    ("villa-santa-rita", "Villa Santa Rita", "comuna-11"),
    ("coghlan", "Coghlan", "comuna-12"),
    ("saavedra", "Saavedra", "comuna-12"),
    ("villa-urquiza", "Villa Urquiza", "comuna-12"),
    ("villa-pueyrredon", "Villa Pueyrredon", "comuna-12"),
    ("nunez", "Nuñez", "comuna-13"),
    ("belgrano", "Belgrano", "comuna-13"),
    ("colegiales", "Colegiales", "comuna-13"),
    ("palermo", "Palermo", "comuna-14"),
    ("chacarita", "Chacarita", "comuna-15"),
    ("villa-crespo", "Villa Crespo", "comuna-15"),
    ("la-paternal", "La Paternal", "comuna-15"),
    ("villa-ortuzar", "Villa Ortuzar", "comuna-15"),
    ("agronomia", "Agronomia", "comuna-15"),
    ("parque-chas", "Parque Chas", "comuna-15"),
]

# catalogo -> [(codigo, nombre, descripcion, orden)]
CATALOGOS: dict[str, list[tuple[str, str, str, int]]] = {
    "categorias-reclamo": [
        ("alumbrado", "Alumbrado publico", "Luminarias apagadas, intermitentes o rotas", 10),
        ("recoleccion", "Recoleccion de residuos", "Recoleccion no realizada o incompleta", 20),
        ("calzada", "Calzada y veredas", "Baches, hundimientos, veredas rotas", 30),
        ("arbolado", "Arbolado urbano", "Poda, extraccion, riesgo de caida", 40),
        ("agua", "Agua y cloacas", "Perdidas, obstrucciones, falta de presion", 50),
        ("transito", "Transito y senalizacion", "Semaforos, senales, demarcacion", 60),
        ("espacios-verdes", "Espacios verdes", "Plazas, parques, mobiliario urbano", 70),
        ("otros", "Otros", "Lo que no entra en las demas categorias", 999),
    ],
    "prioridades": [
        ("baja", "Baja", "Se resuelve en el curso normal del trabajo", 10),
        ("media", "Media", "Requiere atencion en los proximos dias", 20),
        ("alta", "Alta", "Afecta el servicio o la circulacion", 30),
        ("urgente", "Urgente", "Riesgo para personas o bienes", 40),
    ],
    "tipos-documento": [
        ("dni", "DNI", "Documento Nacional de Identidad", 10),
        ("cuit", "CUIT", "Clave Unica de Identificacion Tributaria", 20),
        ("cuil", "CUIL", "Codigo Unico de Identificacion Laboral", 30),
        ("pasaporte", "Pasaporte", "", 40),
    ],
    "estados-tramite": [
        ("iniciado", "Iniciado", "Ingresado y pendiente de asignacion", 10),
        ("en-proceso", "En proceso", "Asignado a un area y en curso", 20),
        ("derivado", "Derivado", "Pasado a otra area responsable", 30),
        ("resuelto", "Resuelto", "Finalizado con resultado", 40),
        ("rechazado", "Rechazado", "No procede, con motivo registrado", 50),
    ],
}
