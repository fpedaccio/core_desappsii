// Plantilla del entregable. Se usa con:
//   pandoc doc.md --pdf-engine=typst --template=plantilla.typ
//
// Lo que arregla respecto del template por defecto de pandoc:
//   - las tablas centraban y justificaban todo, quedaban ilegibles
//   - el texto justificado dejaba huecos feos en las celdas angostas
//   - los bloques de codigo no se distinguian del cuerpo
//   - los encabezados no tenian jerarquia visual

#let tinta = rgb("#1a1a2e")
#let suave = rgb("#5b6472")
#let linea = rgb("#d8dee9")
#let acento = rgb("#1e5f3f")
#let fondoCodigo = rgb("#f6f8fa")

#set page(
  paper: "a4",
  margin: (x: 2.2cm, top: 2.4cm, bottom: 2.2cm),
  numbering: "1",
  number-align: center,
)

#set text(font: ("Helvetica Neue", "Helvetica", "Arial"), size: 10pt, fill: tinta, lang: "es")
// Sin justificar: en columnas angostas el justificado abre huecos enormes.
#set par(justify: false, leading: 0.72em, spacing: 1.1em)

// ---------- Encabezados ----------
#show heading.where(level: 1): it => block(breakable: false, above: 1.9em, below: 0.9em)[
  #set text(size: 17pt, weight: "bold")
  #it.body
  #v(-0.45em)
  #line(length: 100%, stroke: 1.2pt + acento)
]

#show heading.where(level: 2): it => block(breakable: false, above: 1.5em, below: 0.7em)[
  #set text(size: 13pt, weight: "bold")
  #it.body
]

#show heading.where(level: 3): it => block(breakable: false, above: 1.2em, below: 0.5em)[
  #set text(size: 11pt, weight: "bold", fill: acento)
  #it.body
]

#show heading.where(level: 4): it => block(above: 1em, below: 0.4em)[
  #set text(size: 10pt, weight: "bold", fill: suave)
  #it.body
]

// ---------- Codigo ----------
#show raw.where(block: false): it => box(
  fill: fondoCodigo, inset: (x: 3.5pt, y: 0pt), outset: (y: 3.5pt), radius: 2.5pt,
)[#set text(font: ("Menlo", "Monaco"), size: 8.8pt); #it]

#show raw.where(block: true): it => block(
  fill: fondoCodigo, inset: 9pt, radius: 4pt, width: 100%, breakable: true,
  stroke: (left: 2.5pt + acento),
)[#set text(font: ("Menlo", "Monaco"), size: 8.2pt); #set par(justify: false, leading: 0.62em); #it]

// ---------- Tablas ----------
// Alineadas a la izquierda y sin justificar: es lo que estaba mal.
#set table(
  inset: (x: 7pt, y: 5.5pt),
  stroke: (x, y) => (bottom: if y == 0 { 1pt + tinta } else { 0.5pt + linea }),
  align: left + top,
)
#show table.cell.where(y: 0): set text(weight: "bold", size: 9.2pt)
// Pegadas al margen izquierdo: si no, las tablas angostas quedan flotando
// en el medio de la pagina y parece un error de maquetado.
#show table: it => align(left, it)
#show table: set text(size: 9.2pt)
#show table: set par(justify: false, leading: 0.6em)

#show link: set text(fill: acento)
#set list(indent: 0.6em, spacing: 0.75em)
#set enum(indent: 0.6em, spacing: 0.75em)

#let horizontalrule = block(above: 1.4em, below: 1.4em)[
  #line(length: 100%, stroke: 0.5pt + linea)
]

#show terms: it => it.children.map(c => [
  #strong[#c.term] #block(inset: (left: 1.2em, top: -0.5em))[#c.description]
]).join()

// ---------- Portada ----------
#align(center)[
  #v(2.6cm)
  #text(size: 11pt, fill: acento, weight: "bold", tracking: 1.6pt)[
    DESARROLLO DE APLICACIONES II
  ]
  #v(0.5cm)
  #text(size: 25pt, weight: "bold")[$title$]
  $if(subtitle)$
  #v(0.25cm)
  #text(size: 13pt, fill: suave)[$subtitle$]
  $endif$
  #v(0.7cm)
  #line(length: 42%, stroke: 1pt + acento)
  #v(0.7cm)
  $for(author)$
  #text(size: 12pt)[$author$]
  $endfor$
  $if(date)$
  #v(0.3cm)
  #text(size: 10.5pt, fill: suave)[$date$]
  $endif$
]

#v(1fr)
#align(center)[
  #block(width: 86%, inset: 13pt, radius: 5pt, fill: fondoCodigo, stroke: 0.5pt + linea)[
    #set text(size: 9.5pt, fill: suave)
    #set par(justify: false)
    #align(left)[$if(abstract)$$abstract$$endif$]
  ]
]
#pagebreak()

$if(toc)$
#outline(depth: 2, indent: auto, title: [Contenido])
#pagebreak()
$endif$

$body$
