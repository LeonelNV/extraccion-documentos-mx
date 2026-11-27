"""Constancia de situación fiscal sintética.

Sigue la estructura de una constancia real, medida con ``make esqueleto`` sin ver sus datos
(posición de cada línea, fuentes y etiquetas):

* Página 1: cédula de identificación fiscal (RFC, nombre completo, idCIF y QR) y, a la
  derecha, título, lugar y fecha de emisión y el RFC bajo unas barras. "Datos de
  Identificación del Contribuyente:" es una tabla: etiquetas a la izquierda y valores en una
  columna. "Datos del domicilio registrado" lleva dos pares por renglón, cada valor justo
  después de su etiqueta.
* Página 2: actividades económicas, regímenes, avisos y sellos.

**Sin caracteres de espacio.** La constancia real dibuja cada palabra por separado, a menos
de 3 pt de la anterior y sin carácter de espacio; aquí igual (``ESPACIO``). Con la tolerancia
fija de pdfplumber eso juntaba "PrimerApellido:", que es lo que falló con la constancia
real. El código postal va pegado a su etiqueta, como en la real.

No lleva escudos, logotipos, el texto legal del SAT ni sellos reales: los avisos y sellos
son texto de muestra y el QR trae datos sintéticos, no una URL de la autoridad fiscal.
"""

import io
from datetime import date

from reportlab.lib.colors import Color, HexColor, white
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

from synth.render.common import (
    MESES,
    PAGE_H,
    PAGE_W,
    DocContext,
    Rendered,
    draw_qr,
    draw_watermark,
    fea,
    fecha_dmy,
    finish,
    new_canvas,
)

TEMPLATE = "csf_constancia"

BOLD, REGULAR = "Helvetica-Bold", "Helvetica"
ESPACIO = 0.25
"""Separación entre palabras, en em (un espacio de Helvetica mide 0.278 em)."""
GRIS = HexColor("#555555")
NEGRO = HexColor("#111111")

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


def ancho(text: str, font: str, size: float) -> float:
    words = text.split()
    return sum(stringWidth(w, font, size) for w in words) + ESPACIO * size * (len(words) - 1)


def texto(
    c: Canvas,
    x: float,
    top: float,
    text: str,
    *,
    font: str = REGULAR,
    size: float = 8,
    max_width: float | None = None,
    color: Color | None = None,
    centro: bool = False,
) -> float:
    """Dibuja ``text`` palabra por palabra, sin caracteres de espacio, con su parte de arriba
    en ``top`` (medido desde el borde superior, como pdfplumber). Devuelve la x final."""
    if max_width is not None:
        while size > 5 and ancho(text, font, size) > max_width:
            size -= 0.5
    if centro:
        x -= ancho(text, font, size) / 2
    c.setFont(font, size)
    c.setFillColor(color or NEGRO)
    baseline = PAGE_H - top - 0.78 * size
    for word in text.split():
        c.drawString(x, baseline, word)
        x += stringWidth(word, font, size) + ESPACIO * size
    return x - ESPACIO * size


def _wrap(text: str, font: str, size: float, max_width: float) -> list[str]:
    lines: list[str] = []
    for word in text.split():
        if lines and ancho(f"{lines[-1]} {word}", font, size) <= max_width:
            lines[-1] += f" {word}"
        else:
            lines.append(word)
    return lines or [""]


def _wrap_chars(text: str, font: str, size: float, max_width: float) -> list[str]:
    """Para cadenas sin espacios (sellos): corta por caracteres."""
    lines = [""]
    for ch in text:
        if stringWidth(lines[-1] + ch, font, size) > max_width:
            lines.append("")
        lines[-1] += ch
    return lines


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
    dy = rng.uniform(-6, 6)  # desplazamiento vertical de toda la página 1
    barra = HexColor(rng.choice(("#5B6770", "#6D4C41", "#455A64")))

    buffer = io.BytesIO()
    c = new_canvas(buffer, title="Constancia de situación fiscal")

    def pie(numero: int) -> None:
        texto(c, 509, 776, f"Página {numero} de 2", size=8, color=GRIS)

    def seccion(titulo: str, top: float) -> None:
        c.setFillColor(barra)
        c.rect(36, PAGE_H - top - 12, PAGE_W - 72, 15, stroke=0, fill=1)
        texto(c, PAGE_W / 2, top, titulo, font=BOLD, size=10, color=white, centro=True)

    # ---------------------------------------------------------------- página 1
    # Cédula: recuadro con el QR a la izquierda y el texto centrado en x≈220.
    c.setStrokeColor(HexColor("#999999"))
    c.rect(40, PAGE_H - 314 - dy, 260, 201, stroke=1, fill=0)
    texto(c, 69, 128 + dy, "CÉDULA DE IDENTIFICACIÓN FISCAL", font=BOLD, size=10)
    draw_qr(c, f"MUESTRA|RFC={p.rfc}|idCIF={id_cif}", 48, PAGE_H - 262 - dy, 95)
    centro = 222
    texto(c, centro, 188 + dy, fields["rfc"], font=BOLD, size=8, centro=True)
    texto(c, centro, 197 + dy, "Registro Federal de", centro=True)
    texto(c, centro, 206 + dy, "Contribuyentes", centro=True)
    nombre_completo = " ".join(
        v for v in (fields["nombre"], fields["apellido_paterno"], fields["apellido_materno"]) if v
    )
    top = 228 + dy
    for renglon in _wrap(nombre_completo, BOLD, 8, 140)[:3]:
        texto(c, centro, top, renglon, font=BOLD, size=8, max_width=140, centro=True)
        top += 9.5
    texto(c, centro, top + 1, "Nombre, denominación o razón", centro=True)
    texto(c, centro, top + 10, "social", centro=True)
    texto(c, centro, 277 + dy, f"idCIF: {id_cif}", font=BOLD, size=8, centro=True)
    texto(c, centro, 287 + dy, "VALIDA TU INFORMACIÓN", font=BOLD, size=8, centro=True)
    texto(c, centro, 296 + dy, "FISCAL", font=BOLD, size=8, centro=True)
    texto(c, 46, 306 + dy, "MUESTRA - DOCUMENTO SINTÉTICO SIN VALIDEZ", size=6, color=GRIS)

    # Título, lugar y fecha de emisión, RFC bajo unas barras decorativas (no es un código de
    # barras legible).
    texto(c, 334, 182 + dy, "CONSTANCIA DE SITUACIÓN FISCAL", font=BOLD, size=12)
    texto(c, 382, 228 + dy, "Lugar y Fecha de Emisión", font=BOLD, size=8)
    lugar = f"{fields['municipio']} , {fields['estado']} A {fecha_constancia(ctx.fecha_emision)}"
    texto(c, 445, 240 + dy, lugar, font=BOLD, size=8, max_width=PAGE_W - 345, centro=True)
    c.setFillColor(HexColor("#222222"))
    bx = 360.0
    while bx < 540:
        w = rng.choice((0.8, 1.2, 2.0))
        c.rect(bx, PAGE_H - 292 - dy, w, 34, stroke=0, fill=1)
        bx += w + rng.choice((0.8, 1.4, 2.2))
    texto(c, 408, 296 + dy, fields["rfc"], size=8)

    # Datos de identificación: tabla con los valores en una columna.
    seccion("Datos de Identificación del Contribuyente:", 323 + dy)
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
    top = 345 + dy
    for etiqueta, valor in identificacion:
        texto(c, 43, top, etiqueta, font=BOLD, size=8)
        if valor:
            texto(c, 236, top, valor, size=8, max_width=PAGE_W - 236 - 40)
        top += 21.9

    # Domicilio: dos pares por renglón, cada valor justo después de su etiqueta.
    seccion("Datos del domicilio registrado", 552 + dy)
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
    top = 575 + dy
    for i, (etiqueta, valor) in enumerate(domicilio):
        x, limite = (43, 300) if i % 2 == 0 else (311, PAGE_W - 24)
        fin = texto(c, x, top, etiqueta, font=BOLD, size=8)
        # El código postal va pegado a su etiqueta; los demás valores, a un espacio.
        xv = fin if etiqueta == "Código Postal:" else fin + ESPACIO * 8
        if valor:
            texto(c, xv, top, valor, size=8, max_width=max(limite - xv, 30))
        if i % 2 == 1:
            top += 21.9

    pie(1)
    draw_watermark(c)
    c.showPage()

    # ---------------------------------------------------------------- página 2
    seccion("Actividades Económicas:", 141)
    encabezado = ((45, "Orden"), (176, "Actividad Económica"), (377, "Porcentaje"))
    encabezado += ((440, "Fecha Inicio"), (516, "Fecha Fin"))
    for x, titulo in encabezado:
        texto(c, x, 160, titulo, font=BOLD, size=10)
    texto(c, 38, 174, "1")
    texto(c, 82, 174, actividad, max_width=280)
    texto(c, 372, 174, "100")
    texto(c, 449, 174, fecha_dmy(inicio))

    seccion("Regímenes:", 212)
    for x, titulo in ((214, "Régimen"), (440, "Fecha Inicio"), (516, "Fecha Fin")):
        texto(c, x, 231, titulo, font=BOLD, size=10)
    texto(c, 38, 245, regimen, max_width=400)
    texto(c, 449, 245, fecha_dmy(inicio))

    aviso = (
        "Documento generado con datos ficticios para pruebas de software. No es una constancia "
        "oficial, no fue emitida por ninguna autoridad y no tiene validez legal ni fiscal. "
        "Cualquier parecido con una persona real es coincidencia."
    )
    top = 279
    for renglon in _wrap(aviso, REGULAR, 8, PAGE_W - 84):
        texto(c, 42, top, renglon, color=GRIS)
        top += 9.5

    sello = "".join(rng.choice("0123456789abcdef") for _ in range(160))
    cadena = (
        f"||{ctx.fecha_emision:%Y/%m/%d}|{p.rfc}|CONSTANCIA DE SITUACIÓN FISCAL|"
        f"MUESTRA SIN VALIDEZ|{sello[:40]}||"
    )
    top = 391
    for etiqueta, contenido in (("Cadena Original Sello:", cadena), ("Sello Digital:", sello)):
        texto(c, 48, top, etiqueta, font=BOLD, size=8)
        for renglon in _wrap_chars(contenido, REGULAR, 8, PAGE_W - 162 - 36):
            texto(c, 162, top, renglon)
            top += 9.3
        top += 9

    pie(2)
    return Rendered(pdf=finish(c, buffer), fields=fields)
