"""Extractor B: OCR (Tesseract, igual que el extractor A) + un LLM en Amazon Bedrock.

El texto del OCR va al modelo, que devuelve los campos con la herramienta forzada; la
respuesta se valida con pydantic y cada valor pasa por los mismos validadores que las
reglas (:mod:`docextract.llm.postprocess`).

La latencia suma el OCR y la llamada al modelo. El costo sale de los tokens reales.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from docextract.extractors._llm import LlmRouteResult, llamar
from docextract.llm.bedrock import BedrockClient, modelo
from docextract.llm.postprocess import CATALOGO_DESCARGADO
from docextract.llm.prompts import mensaje_texto
from docextract.ocr import OcrCache, OcrConfig, OcrResult, ocr_images, ocr_pdf
from docextract.schemas import DocType, ExtractionResult

if TYPE_CHECKING:
    from PIL.Image import Image

__all__ = ["DEFAULT_MODEL", "NAME", "OcrLlmExtractor"]

NAME = "ocr_llm"
DEFAULT_MODEL = "amazon.nova-lite-v1:0"


class OcrLlmExtractor:
    def __init__(
        self,
        model_id: str = DEFAULT_MODEL,
        *,
        bedrock: BedrockClient | None = None,
        ocr_config: OcrConfig | None = None,
        ocr_cache: OcrCache | None = None,
        catalog: object = CATALOGO_DESCARGADO,
    ) -> None:
        self.model = modelo(model_id)
        self.name = f"{NAME}/{model_id}"
        self.bedrock = bedrock or BedrockClient()
        self.ocr_config = ocr_config or OcrConfig()
        self.ocr_cache = ocr_cache
        """Solo para datos sintéticos (evaluación): guarda el texto en disco."""
        self.catalog = catalog

    def extract(self, images: Sequence[Image], doc_type: DocType) -> ExtractionResult:
        """Interfaz común de los extractores de imagen."""
        return self.from_ocr(ocr_images(list(images), self.ocr_config), doc_type).result

    def extract_pdf(self, pdf: bytes, doc_type: DocType) -> LlmRouteResult:
        if self.ocr_cache is not None:
            ocr = self.ocr_cache.get(pdf, self.ocr_config)
        else:
            ocr = ocr_pdf(pdf, self.ocr_config)
        return self.from_ocr(ocr, doc_type)

    def from_ocr(self, ocr: OcrResult, doc_type: DocType) -> LlmRouteResult:
        return llamar(
            self.bedrock,
            self.model,
            doc_type,
            mensaje_texto(doc_type, ocr.layout.text),
            name=self.name,
            latencia_previa_ms=ocr.seconds * 1000,
            catalog=self.catalog,
        )
