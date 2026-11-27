"""Constancia de CURP sintética.

Sigue la estructura de una constancia real, medida con ``make esqueleto`` sin ver sus datos
(posición de cada línea, fuentes y etiquetas):

* El título del encabezado es una imagen, no texto: no aparece en la capa de texto.
* "Clave:" con la CURP abajo; "Nombre" con el nombre completo abajo, en un solo renglón
  (nombre(s) y luego apellidos); "Entidad de registro:" con su valor en el mismo renglón.
* A la derecha, la leyenda de CURP certificada; a la izquierda, un número de 15 dígitos.
* Una carta: el nombre repetido en chico, "PRESENTE", lugar y fecha, párrafos, la firma de
  quien la emite y su cargo, un QR, avisos, "TRÁMITE GRATUITO" y el aviso de privacidad.

**No imprime** sexo, fecha de nacimiento, entidad de nacimiento ni nacionalidad: el parser
los deduce de la CURP. Tampoco separa nombre y apellidos: el parser los divide con la CURP.

Sin escudos, logotipos ni el texto legal de la autoridad: los párrafos son redacción propia,
el firmante es un nombre ficticio con un cargo genérico, el teléfono, el correo y la
dirección son de ejemplo y el QR trae datos sintéticos.
"""

import io
from datetime import date
from functools import cache

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.colors import Color, HexColor
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

from docextract.entidades import por_clave_curp
from synth.persona import NOMBRES_H, NOMBRES_M
from synth.render.common import (
    MESES,
    PAGE_H,
    PAGE_W,
    DocContext,
    Rendered,
    draw_qr,
    fea,
    finish,
    new_canvas,
)

TEMPLATE = "curp_constancia"

BOLD, REGULAR = "Helvetica-Bold", "Helvetica"
NEGRO = HexColor("#111111")
GRIS = HexColor("#444444")
MARGEN, ANCHO_TEXTO = 21.0, PAGE_W - 21.0 - 18.0
INTERLINEA = 9.3

TITULO = "CONSTANCIA DE LA CLAVE UNICA DE REGISTRO DE POBLACION"
CERTIFICADA = "CURP Certificada: verificada con el Registro Civil"
CARGO = "TITULAR DE LA DEPENDENCIA EMISORA"
APELLIDOS_FIRMANTE = (
    "Ortega", "Salinas", "Medina", "Carrillo", "Valdez", "Cordero", "Ibarra", "Montes",
    "Galindo", "Estrada", "Robles", "Quintero", "Villegas", "Cervantes", "Navarro", "Zamora",
)  # fmt: skip

PARRAFOS = (
    "La identidad es un derecho de todas las personas. Esta constancia es una muestra "
    "sintética: reproduce la organización de una constancia para probar sistemas que leen "
    "documentos de identidad de forma automática, y todos los datos que contiene, incluidos "
    "el nombre, la clave y el folio, son ficticios.",
    "La Clave Única de Registro de Población (CURP) identifica de forma individual a cada "
    "persona registrada y le permite consultar sus datos y realizar trámites y servicios, en "
    "línea o en ventanilla, con una sola clave, desde cualquier lugar con acceso a internet "
    "dentro o fuera del país.",
    "Revisa que los datos de la constancia sean correctos. Si encuentras un error, solicita "
    "su corrección en la oficina de registro que corresponda; mantener los datos al día ayuda "
    "a que el registro de población sea completo y confiable, y protege tu información "
    "personal.",
    "Gracias por tu participación.",
)
PRIVACIDAD = (
    "Los datos personales de esta muestra son ficticios. En una constancia real, los datos que "
    "forman parte de la Base de Datos Nacional de la Clave Única de Registro de Población se "
    "usan para asignar y actualizar la Clave Única de Registro de Población, conforme a la ley "
    "aplicable. Para ejercer tus derechos sobre tus datos personales puedes escribir a "
    "privacidad@ejemplo.mx o acudir a Calle Ficticia no. 123, Col. Centro, C.P. 00000. "
    "Consulta el aviso de privacidad de ejemplo en https://www.ejemplo.mx/aviso-de-privacidad"
)


def fecha_carta(d: date) -> str:
    """``7 de octubre de 2026``."""
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"


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
    alinear: str = "izquierda",
) -> float:
    """Dibuja ``text`` con su parte de arriba en ``top`` (medido desde el borde superior, como
    pdfplumber). ``alinear``: izquierda, centro o derecha respecto a ``x``. Devuelve la x
    final."""
    if max_width is not None:
        while size > 5 and stringWidth(text, font, size) > max_width:
            size -= 0.5
    ancho = stringWidth(text, font, size)
    if alinear == "centro":
        x -= ancho / 2
    elif alinear == "derecha":
        x -= ancho
    c.setFont(font, size)
    c.setFillColor(color or NEGRO)
    c.drawString(x, PAGE_H - top - 0.78 * size, text)
    return x + ancho


def parrafo(c: Canvas, top: float, text: str, *, x: float = MARGEN, size: float = 8) -> float:
    """Párrafo justificado a la izquierda. Devuelve el ``top`` del renglón siguiente."""
    renglones: list[str] = []
    for word in text.split():
        if renglones and stringWidth(f"{renglones[-1]} {word}", REGULAR, size) <= ANCHO_TEXTO:
            renglones[-1] += f" {word}"
        else:
            renglones.append(word)
    for renglon in renglones:
        texto(c, x, top, renglon, size=size)
        top += INTERLINEA
    return top


@cache
def _titulo_png(width_px: int, height_px: int, color: tuple[int, int, int]) -> bytes:
    """El título como imagen: en la constancia real no está en la capa de texto."""
    img = Image.new("RGB", (width_px, height_px), color)
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=10)
    size = int(10 * 0.9 * width_px / draw.textlength(TITULO, font=font))
    font = ImageFont.load_default(size=min(size, int(height_px * 0.45)))
    w = draw.textlength(TITULO, font=font)
    draw.text(((width_px - w) / 2, height_px * 0.27), TITULO, font=font, fill=(255, 255, 255))
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _firmante(rng) -> str:
    nombre = rng.choice(NOMBRES_H + NOMBRES_M)
    paterno, materno = rng.sample(APELLIDOS_FIRMANTE, 2)
    return fea(f"{nombre} {paterno} {materno}")


def render(ctx: DocContext) -> Rendered:
    p, rng = ctx.persona, ctx.rng
    entidad = por_clave_curp(p.clave_entidad_nacimiento)
    if entidad is None:  # nacido en el extranjero: registrado en alguna entidad del país
        entidad = por_clave_curp(rng.choice(("DF", "JC", "NL", "NT", "MC", "BC")))
    fields = {
        "curp": p.curp,
        "nombre": fea(ctx.nombre),
        "apellido_paterno": fea(ctx.apellido_paterno),
        "apellido_materno": fea(ctx.apellido_materno),
        "entidad_registro": fea(entidad.nombre),
    }
    nombre_completo = " ".join(
        v for v in (fields["nombre"], fields["apellido_paterno"], fields["apellido_materno"]) if v
    )

    buffer = io.BytesIO()
    c = new_canvas(buffer, title="Constancia de CURP")
    color = rng.choice(((107, 44, 62), (60, 74, 99), (47, 93, 80)))

    # Encabezado: el título es imagen.
    c.drawImage(ImageReader(io.BytesIO(_titulo_png(1140, 70, color))), 36, PAGE_H - 106, 540, 33)

    # Datos de la clave, con un marco claro a la izquierda donde la real lleva imágenes.
    c.setStrokeColor(HexColor("#BBBBBB"))
    c.setLineWidth(0.6)
    c.roundRect(36, PAGE_H - 294, PAGE_W - 72, 172, 6, stroke=1, fill=0)
    c.setFillColor(HexColor("#EEEEEE"))
    c.roundRect(48, PAGE_H - 284, 118, 152, 4, stroke=0, fill=1)
    texto(c, 178, 134, "Clave:", font=BOLD, size=10)
    texto(c, 178, 150, fields["curp"], font=BOLD, size=15)
    texto(c, 178, 172, "Nombre", font=BOLD, size=10)
    texto(c, 178, 189, nombre_completo, font=BOLD, size=14, max_width=PAGE_W - 178 - 40)
    texto(c, 178, 229, "Entidad de registro:", size=10)
    texto(c, 289, 229, fields["entidad_registro"], font=BOLD, size=10, max_width=PAGE_W - 330)
    texto(c, 439, 304, CERTIFICADA, size=7, color=GRIS)
    folio = "".join(rng.choice("0123456789") for _ in range(15))
    texto(c, 50, 318, folio)

    # Carta
    texto(c, 22, 372, nombre_completo, font=BOLD)
    texto(c, 22, 417, "PRESENTE")
    texto(c, PAGE_W - 15, 417, f"Ciudad de México, a {fecha_carta(ctx.fecha_emision)}",
          alinear="derecha")  # fmt: skip
    for parr, top in zip(PARRAFOS, (437, 459, 496, 534), strict=True):
        parrafo(c, top, parr)
    texto(c, PAGE_W / 2, 559, _firmante(rng), font=BOLD, size=10, alinear="centro")
    texto(c, PAGE_W / 2, 589, CARGO, size=9, alinear="centro")
    payload = "|".join(("CURP", p.curp, fea(nombre_completo), folio, "MUESTRA"))
    draw_qr(c, payload, PAGE_W - 78, PAGE_H - 622, 66)

    x = texto(c, 22, 626, "Para cualquier aclaración o duda sobre tu clave, comunícate al",
              size=7)  # fmt: skip
    texto(c, x + 2, 626, "CENTRO DE ATENCIÓN DE EJEMPLO, teléfono 800 000 00 00", font=BOLD,
          size=7)  # fmt: skip
    texto(c, 22, 652, "Esta constancia es una muestra sintética y no es válida para ningún "
          "trámite.", font=BOLD, size=7)  # fmt: skip
    texto(c, PAGE_W / 2, 663, "TRÁMITE GRATUITO", font=BOLD, size=10, alinear="centro")
    parrafo(c, 686, PRIVACIDAD, x=25)
    return Rendered(pdf=finish(c, buffer), fields=fields)
