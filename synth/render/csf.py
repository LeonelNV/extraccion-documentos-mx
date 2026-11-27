"""Constancia de situación fiscal sintética.

La estructura sigue a la constancia real (orden de secciones, texto de las etiquetas y forma
de acomodar etiqueta y valor), descrita sin datos personales:

* Página 1: cédula (RFC, nombre completo, idCIF y QR) a la izquierda; título, lugar y fecha
  de emisión a la derecha; "Datos de Identificación del Contribuyente:" con un par
  etiqueta-valor por renglón; "Datos del domicilio registrado" con dos pares por renglón.
* Página 2: actividades económicas, regímenes, avisos y sellos.

Cada valor va justo después de su etiqueta en el mismo renglón. El código postal va pegado a
su etiqueta, sin espacio, como en la real; en el resto la separación varía y a veces queda
por debajo de los 3 pt con los que pdfplumber separa palabras.

No lleva escudos, logotipos, el texto legal del SAT ni sellos reales: los avisos y sellos
son texto de muestra y el QR trae datos sintéticos, no una URL de la autoridad fiscal.
"""

import io
from datetime import date

from reportlab.lib.colors import HexColor, white
from reportlab.pdfbase.pdfmetrics import stringWidth

from synth.render.common import (
    MESES,
    PAGE_H,
    PAGE_W,
    DocContext,
    Rendered,
    draw_fitted,
    draw_qr,
    draw_watermark,
    fea,
    fecha_dmy,
    finish,
    new_canvas,
)

TEMPLATE = "csf_constancia"

BOLD, REGULAR = "Helvetica-Bold", "Helvetica"
LEFT, RIGHT_COL = 42.0, PAGE_W / 2 + 6
GRIS = HexColor("#555555")

ACTIVIDADES = (
    ("Asalariado", "Régimen de Sueldos y Salarios e Ingresos Asimilados a Salarios"),
    ("Otros servicios profesionales, científicos y técnicos", "Régimen Simplificado de Confianza"),
    (
        "Comercio al por menor de artículos de papelería",
        "Régimen de las Personas Físicas con Actividades Empresariales y Profesionales",
    ),
)


def fecha_constancia(d: date) -> str:
    """``07 DE OCTUBRE DE 2026``."""
    return f"{d.day:02d} DE {MESES[d.month - 1].upper()} DE {d.year}"


def _wrap(text: str, font: str, size: float, max_width: float) -> list[str]:
    lines: list[str] = []
    for word in text.split():
        if lines and stringWidth(f"{lines[-1]} {word}", font, size) <= max_width:
            lines[-1] += f" {word}"
        else:
            lines.append(word)
    return lines or [""]


def render(ctx: DocContext) -> Rendered:
    p, d, rng = ctx.persona, ctx.domicilio, ctx.rng
    # La mitad de las constancias conserva los acentos en mayúsculas.
    estilo = (lambda s: s.upper()) if rng.random() < 0.5 else fea
    fields = {
        "rfc": p.rfc,
        "curp": p.curp,
        "nombre": estilo(ctx.nombre),
        "apellido_paterno": estilo(ctx.apellido_paterno),
        "apellido_materno": estilo(ctx.apellido_materno),
        "codigo_postal": d.codigo_postal,
        "tipo_vialidad": estilo(d.tipo_vialidad),
        "nombre_vialidad": estilo(d.nombre_vialidad),
        "numero_exterior": estilo(d.numero_exterior),
        "numero_interior": estilo(d.numero_interior),
        "colonia": estilo(d.colonia),
        "ciudad": estilo(d.ciudad),
        "municipio": estilo(d.municipio),
        "estado": estilo(d.estado),
    }
    fields["calle"] = f"{fields['tipo_vialidad']} {fields['nombre_vialidad']}"

    inicio = p.fecha_nacimiento.replace(year=p.fecha_nacimiento.year + 18)
    inicio = min(inicio, ctx.reference_date)
    id_cif = "".join(rng.choice("0123456789") for _ in range(11))
    actividad, regimen = rng.choice(ACTIVIDADES)
    # Separación entre etiqueta y valor: a veces menor que la tolerancia de pdfplumber.
    gap = rng.choice((1.5, 4.0))
    dy = rng.uniform(-6, 6)
    barra = HexColor(rng.choice(("#5B6770", "#6D4C41", "#455A64")))

    buffer = io.BytesIO()
    c = new_canvas(buffer, title="Constancia de situación fiscal")

    def pagina(numero: int) -> None:
        draw_fitted(c, PAGE_W - 110, PAGE_H - 28, f"Página {numero} de 2", size=7, color=GRIS)

    def seccion(titulo: str, y: float) -> None:
        c.setFillColor(barra)
        c.rect(36, y - 4, PAGE_W - 72, 15, stroke=0, fill=1)
        draw_fitted(c, LEFT, y, titulo, font=BOLD, size=9, color=white)

    def par(x: float, y: float, etiqueta: str, valor: str, ancho: float, sep: float) -> None:
        """Etiqueta en negritas y el valor justo después, en el mismo renglón."""
        draw_fitted(c, x, y, etiqueta, font=BOLD, size=8)
        xv = x + stringWidth(etiqueta, BOLD, 8) + sep
        if valor:
            draw_fitted(c, xv, y, valor, size=8, max_width=max(ancho - (xv - x), 30))

    # ---------------------------------------------------------------- página 1
    pagina(1)
    top = PAGE_H - 48 + dy

    # Cédula de identificación fiscal (izquierda)
    c.setStrokeColor(HexColor("#999999"))
    c.rect(36, top - 196, 262, 206, stroke=1, fill=0)
    draw_fitted(c, 46, top - 6, "CÉDULA DE IDENTIFICACIÓN FISCAL", font=BOLD, size=9)
    draw_qr(c, f"MUESTRA|RFC={p.rfc}|idCIF={id_cif}", 46, top - 150, 100)
    draw_fitted(c, 54, top - 166, "VALIDA TU INFORMACIÓN", font=BOLD, size=6.5)
    draw_fitted(c, 80, top - 175, "FISCAL", font=BOLD, size=6.5)
    x = 158
    draw_fitted(c, x, top - 36, fields["rfc"], font=BOLD, size=10)
    draw_fitted(c, x, top - 47, "Registro Federal de", size=6.5, color=GRIS)
    draw_fitted(c, x, top - 55, "Contribuyentes", size=6.5, color=GRIS)
    nombre_completo = " ".join(
        v for v in (fields["nombre"], fields["apellido_paterno"], fields["apellido_materno"]) if v
    )
    y = top - 76
    for renglon in _wrap(nombre_completo, BOLD, 8, 132)[:3]:
        draw_fitted(c, x, y, renglon, font=BOLD, size=8, max_width=132)
        y -= 10
    draw_fitted(c, x, y - 1, "Nombre, denominación o razón", size=6.5, color=GRIS)
    draw_fitted(c, x, y - 9, "social", size=6.5, color=GRIS)
    draw_fitted(c, x, y - 28, f"idCIF: {id_cif}", font=BOLD, size=8)
    draw_fitted(c, 46, top - 190, "MUESTRA - DOCUMENTO SINTÉTICO SIN VALIDEZ", size=6, color=GRIS)

    # Título, lugar y fecha de emisión (derecha)
    xr = 316
    draw_fitted(c, xr, top - 18, "CONSTANCIA DE SITUACIÓN FISCAL", font=BOLD, size=12)
    draw_fitted(c, xr, top - 52, "Lugar y Fecha de Emisión", size=7.5, color=GRIS)
    lugar = f"{fields['municipio']} , {fields['estado']} A {fecha_constancia(ctx.fecha_emision)}"
    draw_fitted(c, xr, top - 64, lugar, font=BOLD, size=8, max_width=PAGE_W - xr - 40)
    # Barras decorativas con el RFC debajo (no es un código de barras legible).
    c.setFillColor(HexColor("#222222"))
    bx = xr + 20
    while bx < xr + 200:
        w = rng.choice((0.8, 1.2, 2.0))
        c.rect(bx, top - 120, w, 34, stroke=0, fill=1)
        bx += w + rng.choice((0.8, 1.4, 2.2))
    draw_fitted(c, xr + 70, top - 132, fields["rfc"], size=8)

    # Datos de identificación: un par por renglón
    y = top - 228
    seccion("Datos de Identificación del Contribuyente:", y)
    identificacion = [
        ("RFC:", fields["rfc"]),
        ("CURP:", fields["curp"]),
        ("Nombre (s):", fields["nombre"]),
        ("Primer Apellido:", fields["apellido_paterno"]),
        ("Segundo Apellido:", fields["apellido_materno"]),
        ("Fecha inicio de operaciones:", fecha_constancia(inicio)),
        ("Estatus en el padrón:", "ACTIVO"),
        ("Fecha de último cambio de estado:", fecha_constancia(inicio)),
        ("Nombre Comercial:", ""),
    ]
    y -= 20
    for etiqueta, valor in identificacion:
        par(LEFT, y, etiqueta, valor, PAGE_W - 2 * LEFT, gap)
        y -= 14

    # Domicilio: dos pares por renglón
    y -= 8
    seccion("Datos del domicilio registrado", y)
    domicilio = [
        ("Código Postal:", fields["codigo_postal"]),
        ("Tipo de Vialidad:", fields["tipo_vialidad"]),
        ("Nombre de Vialidad:", fields["nombre_vialidad"]),
        ("Número Exterior:", fields["numero_exterior"]),
        ("Número Interior:", fields["numero_interior"]),
        ("Nombre de la Colonia:", fields["colonia"]),
        ("Nombre de la Localidad:", fields["ciudad"]),
        ("Nombre del Municipio o Demarcación Territorial:", fields["municipio"]),
        ("Nombre de la Entidad Federativa:", fields["estado"]),
        ("Entre Calle:", ""),
        ("Y Calle:", ""),
    ]
    y -= 20
    for i, (etiqueta, valor) in enumerate(domicilio):
        x, ancho = (
            (LEFT, RIGHT_COL - LEFT - 10) if i % 2 == 0 else (RIGHT_COL, PAGE_W - 24 - RIGHT_COL)
        )
        sep = 0.0 if etiqueta == "Código Postal:" else gap
        par(x, y, etiqueta, valor, ancho, sep)
        if i % 2 == 1:
            y -= 14

    draw_watermark(c)
    c.showPage()

    # ---------------------------------------------------------------- página 2
    pagina(2)
    y = PAGE_H - 60
    seccion("Actividades Económicas:", y)
    y -= 20
    columnas = ((LEFT, "Orden"), (80, "Actividad Económica"), (360, "Porcentaje"))
    columnas += ((430, "Fecha Inicio"), (500, "Fecha Fin"))
    for x, titulo in columnas:
        draw_fitted(c, x, y, titulo, font=BOLD, size=8)
    y -= 14
    draw_fitted(c, LEFT + 8, y, "1", size=8)
    draw_fitted(c, 80, y, actividad, size=8, max_width=270)
    draw_fitted(c, 370, y, "100", size=8)
    draw_fitted(c, 430, y, fecha_dmy(inicio), size=8)

    y -= 30
    seccion("Regímenes:", y)
    y -= 20
    for x, titulo in ((LEFT, "Régimen"), (430, "Fecha Inicio"), (500, "Fecha Fin")):
        draw_fitted(c, x, y, titulo, font=BOLD, size=8)
    y -= 14
    draw_fitted(c, LEFT, y, regimen, size=8, max_width=380)
    draw_fitted(c, 430, y, fecha_dmy(inicio), size=8)

    y -= 40
    aviso = (
        "Documento generado con datos ficticios para pruebas de software. No es una constancia "
        "oficial, no fue emitida por ninguna autoridad y no tiene validez legal ni fiscal. "
        "Cualquier parecido con una persona real es coincidencia."
    )
    for renglon in _wrap(aviso, REGULAR, 7, PAGE_W - 2 * LEFT):
        draw_fitted(c, LEFT, y, renglon, size=7, color=GRIS)
        y -= 10

    y -= 20
    sello = "".join(rng.choice("0123456789abcdef") for _ in range(96))
    cadena = (
        f"||{ctx.fecha_emision:%Y/%m/%d}|{p.rfc}|CONSTANCIA DE SITUACIÓN FISCAL|"
        f"MUESTRA SIN VALIDEZ|{sello[:24]}||"
    )
    for etiqueta, texto in (("Cadena Original Sello:", cadena), ("Sello Digital:", sello)):
        draw_fitted(c, LEFT, y, etiqueta, font=BOLD, size=7)
        xv = LEFT + stringWidth(etiqueta, BOLD, 7) + 4
        draw_fitted(c, xv, y, texto, size=7, max_width=PAGE_W - LEFT - xv)
        y -= 16

    return Rendered(pdf=finish(c, buffer), fields=fields)
