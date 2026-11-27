"""Ruta 2a: documentos con capa de texto, leídos con reglas y sin ML.

Los parsers trabajan sobre un ``TextLayout`` (palabras con posición). En esta fase viene de
la capa de texto del PDF; en la fase 5, del OCR, con los mismos parsers.

Hay parser para CURP y CSF, que casi siempre llegan como PDF digital. INE y comprobante
van por la ruta de imagen (fase 5) aunque tengan capa de texto.
"""

from dataclasses import dataclass

from docextract.classify import Classification, classify_text, verify_doc_type
from docextract.parsers.base import EXTRACTOR_NAME, TextParser
from docextract.parsers.csf import CsfParser
from docextract.parsers.curp import CurpParser
from docextract.router import Route, RouteKind, route
from docextract.schemas import DocType, ExtractionResult

__all__ = ["EXTRACTOR_NAME", "PARSERS", "TextRouteResult", "extract_text_route"]

PARSERS: dict[DocType, TextParser] = {
    DocType.CURP: CurpParser(),
    DocType.CSF: CsfParser(),
}


@dataclass(frozen=True)
class TextRouteResult:
    route: Route
    classification: Classification | None
    """Solo en la ruta de texto."""
    result: ExtractionResult | None
    """``None`` si el documento va por la ruta de imagen o no hay parser para su tipo."""


def extract_text_route(pdf: bytes, expected: DocType) -> TextRouteResult:
    """Lee un PDF por la ruta de texto, si aplica.

    ``expected`` es el tipo del campo donde se subió el documento. El clasificador lo
    verifica y, si no coincide, la extracción lleva ``DOCUMENTO_NO_RECONOCIDO``.
    """
    decision = route(pdf)
    if decision.kind is not RouteKind.TEXT:
        return TextRouteResult(decision, None, None)
    classification = classify_text(decision.layout)
    parser = PARSERS.get(expected)
    if parser is None:
        return TextRouteResult(decision, classification, None)
    result = parser.parse(decision.layout)
    warnings = verify_doc_type(expected, classification)
    if warnings:
        result = result.model_copy(update={"warnings": result.warnings + tuple(warnings)})
    return TextRouteResult(decision, classification, result)
