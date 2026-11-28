"""Extractor A: OCR (Tesseract) + las mismas reglas de la ruta de texto.

El OCR produce un ``TextLayout`` marcado como ``ocr``: las etiquetas toleran una letra mal
leída y la CURP y el RFC se corrigen por su estructura y su dígito verificador. Después
corre el parser del tipo de documento, igual que con un PDF digital.

Es la línea base de la ruta de imagen: sin modelos entrenados ni servicios externos.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from docextract.classify import Classification, classify_text, verify_doc_type
from docextract.ocr import OcrCache, OcrConfig, OcrResult, ocr_images, ocr_pdf
from docextract.parsers import PARSERS
from docextract.schemas import DocType, ExtractionResult

if TYPE_CHECKING:
    from PIL.Image import Image

__all__ = ["NAME", "OcrRouteResult", "OcrRulesExtractor"]

NAME = "ocr_reglas"


@dataclass(frozen=True)
class OcrRouteResult:
    ocr: OcrResult
    classification: Classification
    result: ExtractionResult | None
    """``None`` si no hay parser para el tipo de documento."""


class OcrRulesExtractor:
    name = NAME

    def __init__(self, config: OcrConfig | None = None, cache: OcrCache | None = None) -> None:
        self.config = config or OcrConfig()
        self.cache = cache
        """Solo para datos sintéticos (evaluación y entrenamiento): guarda el texto en disco."""

    def ocr(self, pdf: bytes) -> OcrResult:
        if self.cache is not None:
            return self.cache.get(pdf, self.config)
        return ocr_pdf(pdf, self.config)

    def extract(self, images: Sequence[Image], doc_type: DocType) -> ExtractionResult:
        """Interfaz común de los extractores de imagen."""
        route = self._parse(ocr_images(list(images), self.config), doc_type)
        if route.result is None:
            return ExtractionResult(doc_type=doc_type, extractor=NAME)
        return route.result

    def extract_pdf(self, pdf: bytes, doc_type: DocType) -> OcrRouteResult:
        return self._parse(self.ocr(pdf), doc_type)

    def _parse(self, ocr: OcrResult, doc_type: DocType) -> OcrRouteResult:
        start = time.perf_counter()
        layout = ocr.layout
        classification = classify_text(layout)
        parser = PARSERS.get(doc_type)
        if parser is None:
            return OcrRouteResult(ocr, classification, None)
        result = parser.parse(layout)
        warnings = result.warnings + tuple(verify_doc_type(doc_type, classification))
        latency = ocr.seconds * 1000 + (time.perf_counter() - start) * 1000
        result = result.model_copy(
            update={"extractor": NAME, "warnings": warnings, "latency_ms": latency}
        )
        return OcrRouteResult(ocr, classification, result)
