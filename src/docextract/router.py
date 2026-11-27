"""Router: decide si un PDF va por la ruta de texto (2a) o por la de imagen (2b).

Criterio: si la capa de texto de las primeras páginas tiene al menos ``min_chars``
caracteres alfanuméricos, el documento se lee como texto. Un escaneo con OCR invisible
(capa de texto encima de la imagen) también cuenta como texto. Un PDF que solo contiene una
imagen, como las modalidades de escaneo y foto, va a la ruta de imagen.
"""

from dataclasses import dataclass
from enum import StrEnum

from docextract.layout import TextLayout

__all__ = ["DEFAULT_MIN_CHARS", "InvalidPdfError", "Route", "RouteKind", "route"]

DEFAULT_MIN_CHARS = 40
"""Un documento real con capa de texto tiene cientos de caracteres; una imagen, cero."""


class InvalidPdfError(ValueError):
    """El archivo no se pudo abrir como PDF (dañado, cifrado o de otro tipo)."""


class RouteKind(StrEnum):
    TEXT = "texto"
    IMAGE = "imagen"


@dataclass(frozen=True)
class Route:
    kind: RouteKind
    layout: TextLayout
    """La capa de texto leída (vacía en la ruta de imagen)."""
    alnum_chars: int


def route(pdf: bytes, *, min_chars: int = DEFAULT_MIN_CHARS) -> Route:
    if not pdf.lstrip()[:5].startswith(b"%PDF"):
        raise InvalidPdfError("El archivo no es un PDF.")
    try:
        layout = TextLayout.from_pdf(pdf)
    except Exception as error:  # pdfminer lanza excepciones de muchos tipos
        # El mensaje original no se propaga: podría incluir contenido del documento.
        raise InvalidPdfError(f"No se pudo leer el PDF ({type(error).__name__}).") from None
    chars = layout.alnum_chars
    kind = RouteKind.TEXT if chars >= min_chars else RouteKind.IMAGE
    return Route(kind=kind, layout=layout, alnum_chars=chars)
