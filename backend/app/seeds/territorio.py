"""Catalogo territorial inicial: zonas y barrios, mas los catalogos globales.

Es **dato de arranque, no el padron real**. El municipio del TP es ficticio, asi
que esto da una base coherente para que los nueve modulos puedan integrar hoy
usando los mismos identificadores. Cuando la catedra o el equipo definan la
lista de verdad, se reemplaza con `POST /api/v1/catalogos/barrios` sin tocar
codigo.

Los `codigo` son slugs estables: son lo que viaja en el `data` de los eventos.
"""

from __future__ import annotations

ZONAS: list[tuple[str, str, str]] = [
    ("centro", "Centro", "Casco historico y area administrativa"),
    ("norte", "Zona Norte", "Barrios residenciales del norte"),
    ("sur", "Zona Sur", "Area industrial y residencial del sur"),
    ("oeste", "Zona Oeste", "Barrios del oeste y periferia"),
    ("ribera", "Ribera", "Barrios costeros y area portuaria"),
]

# (codigo, nombre, zona)
BARRIOS: list[tuple[str, str, str]] = [
    ("plaza-mayor", "Plaza Mayor", "centro"),
    ("tribunales", "Tribunales", "centro"),
    ("mercado-viejo", "Mercado Viejo", "centro"),
    ("villa-elisa", "Villa Elisa", "norte"),
    ("los-aromos", "Los Aromos", "norte"),
    ("alto-verde", "Alto Verde", "norte"),
    ("san-cayetano", "San Cayetano", "norte"),
    ("parque-industrial", "Parque Industrial", "sur"),
    ("barrio-obrero", "Barrio Obrero", "sur"),
    ("las-quintas", "Las Quintas", "sur"),
    ("santa-rita", "Santa Rita", "oeste"),
    ("el-molino", "El Molino", "oeste"),
    ("loma-linda", "Loma Linda", "oeste"),
    ("puerto-viejo", "Puerto Viejo", "ribera"),
    ("costanera", "Costanera", "ribera"),
    ("isla-verde", "Isla Verde", "ribera"),
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
