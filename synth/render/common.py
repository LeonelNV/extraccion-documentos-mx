"""Utilidades de dibujo compartidas por las plantillas.

Reglas de las plantillas (PLAN §5): inspiradas en los documentos, **no réplicas**. Llevan
una marca de agua "MUESTRA / SPECIMEN" grande y visible; no llevan logotipos, escudos,
hologramas ni elementos de seguridad, y el rostro es una silueta.
"""

import io
import math
import random
from dataclasses import dataclass
from datetime import date
from functools import cache

from PIL import Image, ImageDraw, ImageFont
from reportlab import rl_config
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.colors import Color, HexColor
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

import synth
from docextract.normalize import to_form_format
from synth.persona import Domicilio, Persona

__all__ = [
    "MESES",
    "MESES_ABR",
    "PAGE_H",
    "PAGE_W",
    "DocContext",
    "Rendered",
    "draw_fitted",
    "draw_qr",
    "draw_silhouette",
    "fea",
    "fecha_dmy",
    "fecha_larga",
    "fecha_mes_abr",
    "finish",
    "new_canvas",
]

# Flujos binarios en lugar de ASCII85: PDFs 25% más chicos y mucho más rápidos (sin la
# extensión en C de reportlab, el codificador ASCII85 es Python puro).
rl_config.useA85 = 0

PAGE_W, PAGE_H = letter
MESES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
    "octubre", "noviembre", "diciembre",
)  # fmt: skip
MESES_ABR = tuple(m[:3].upper() for m in MESES)

GRIS = HexColor("#555555")
GRIS_CLARO = HexColor("#DDDDDD")


@dataclass(frozen=True)
class DocContext:
    """Lo que una plantilla necesita para dibujar un documento de una persona.

    Nombre y domicilio vienen aparte de ``persona`` porque una inconsistencia inyectada
    puede cambiarlos solo en este documento.
    """

    persona: Persona
    nombre: str
    apellido_paterno: str
    apellido_materno: str
    domicilio: Domicilio
    reference_date: date
    fecha_emision: date
    rng: random.Random


@dataclass(frozen=True)
class Rendered:
    pdf: bytes
    fields: dict[str, str]
    """Cada campo tal como quedó impreso."""


# ---------------------------------------------------------------------------
# Formatos de texto y fecha
# ---------------------------------------------------------------------------
def fea(text: str) -> str:
    """Mayúsculas sin acentos (con Ñ), como imprimen la CURP y la INE."""
    return to_form_format(text) or ""


def fecha_dmy(d: date, sep: str = "/") -> str:
    return f"{d.day:02d}{sep}{d.month:02d}{sep}{d.year}"


def fecha_mes_abr(d: date, sep: str = " ") -> str:
    return f"{d.day:02d}{sep}{MESES_ABR[d.month - 1]}{sep}{d.year}"


def fecha_larga(d: date) -> str:
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"


# ---------------------------------------------------------------------------
# Lienzo, marca de agua y cierre
# ---------------------------------------------------------------------------
def new_canvas(buffer: io.BytesIO, *, title: str, pagesize: tuple[float, float] = letter) -> Canvas:
    """Lienzo con metadatos que identifican el PDF como sintético.

    ``invariant=1`` quita fechas e identificadores aleatorios: misma entrada, mismos bytes.
    """
    canvas = Canvas(buffer, pagesize=pagesize, invariant=1, pageCompression=1)
    canvas.setTitle(f"{title} - MUESTRA")
    canvas.setAuthor("docextract synth (datos sintéticos)")
    canvas.setSubject(
        "Documento sintético para pruebas. MUESTRA / SPECIMEN. No es un documento oficial."
    )
    canvas.setCreator(f"docextract synth {synth.__version__}")
    return canvas


@cache
def _watermark_png(width_px: int, height_px: int) -> bytes:
    """Marca de agua diagonal como imagen PNG transparente.

    Es una imagen y no texto para que no aparezca en la capa de texto del PDF (no ensucia a
    los parsers), pero sí se ve, y la leerá el OCR en las modalidades de imagen.
    """
    diagonal = int((width_px**2 + height_px**2) ** 0.5)
    band = Image.new("RGBA", (diagonal, diagonal // 4), (0, 0, 0, 0))
    draw = ImageDraw.Draw(band)
    color = (200, 30, 30, 70)
    # La fuente integrada de Pillow no tiene acentos: el texto va sin ellos.
    lines = (
        ("MUESTRA / SPECIMEN", 0.72, 0.10),  # texto, ancho relativo a la diagonal, y relativa
        ("Documento sintetico - sin validez oficial", 0.55, 0.62),
    )
    for text, relative_width, y in lines:
        size = 10
        font = ImageFont.load_default(size=size)
        size = int(size * relative_width * diagonal / draw.textlength(text, font=font))
        font = ImageFont.load_default(size=size)
        w = draw.textlength(text, font=font)
        draw.text(((diagonal - w) / 2, band.height * y), text, font=font, fill=color)
    # Rotación antihoraria a lo largo de la diagonal de la página.
    angle = math.degrees(math.atan2(height_px, width_px))
    rotated = band.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)
    page = Image.new("RGBA", (width_px, height_px), (0, 0, 0, 0))
    page.alpha_composite(
        rotated, ((width_px - rotated.width) // 2, (height_px - rotated.height) // 2)
    )
    out = io.BytesIO()
    page.save(out, format="PNG", optimize=True)
    return out.getvalue()


def draw_watermark(canvas: Canvas, width: float = PAGE_W, height: float = PAGE_H) -> None:
    png = _watermark_png(int(width), int(height))
    canvas.drawImage(ImageReader(io.BytesIO(png)), 0, 0, width, height, mask="auto")


def finish(
    canvas: Canvas, buffer: io.BytesIO, *, width: float = PAGE_W, height: float = PAGE_H
) -> bytes:
    """Dibuja la marca de agua encima de todo, cierra la página y devuelve el PDF."""
    draw_watermark(canvas, width, height)
    canvas.showPage()
    canvas.save()
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Elementos
# ---------------------------------------------------------------------------
def draw_fitted(
    canvas: Canvas,
    x: float,
    y: float,
    text: str,
    *,
    font: str = "Helvetica",
    size: float = 10,
    max_width: float | None = None,
    color: Color | None = None,
) -> None:
    """Texto que se reduce de tamaño si no cabe en ``max_width``."""
    if max_width is not None:
        while size > 5 and stringWidth(text, font, size) > max_width:
            size -= 0.5
    canvas.setFont(font, size)
    canvas.setFillColor(color or HexColor("#111111"))
    canvas.drawString(x, y, text)


def draw_qr(canvas: Canvas, data: str, x: float, y: float, size: float) -> None:
    widget = QrCodeWidget(data, barLevel="M")
    x0, y0, x1, y1 = widget.getBounds()
    drawing = Drawing(size, size, transform=[size / (x1 - x0), 0, 0, size / (y1 - y0), 0, 0])
    drawing.add(widget)
    renderPDF.draw(drawing, canvas, x, y)


def draw_silhouette(canvas: Canvas, x: float, y: float, w: float, h: float) -> None:
    """Silueta genérica en lugar de una fotografía (nunca rostros reales)."""
    canvas.saveState()
    frame = canvas.beginPath()
    frame.rect(x, y, w, h)
    canvas.clipPath(frame, stroke=0, fill=0)
    canvas.setFillColor(GRIS_CLARO)
    canvas.rect(x, y, w, h, stroke=0, fill=1)
    canvas.setFillColor(HexColor("#9A9A9A"))
    canvas.circle(x + w / 2, y + h * 0.62, w * 0.2, stroke=0, fill=1)  # cabeza
    canvas.ellipse(x + w * 0.12, y - h * 0.15, x + w * 0.88, y + h * 0.42, stroke=0, fill=1)
    canvas.restoreState()
