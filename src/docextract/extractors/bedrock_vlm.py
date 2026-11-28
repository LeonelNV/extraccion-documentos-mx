"""Extractor C1: un modelo multimodal en Amazon Bedrock lee la imagen del documento.

Sin OCR: cada página se manda como JPEG (lado mayor de ``lado`` píxeles, en color). La
respuesta se valida y post-procesa igual que en el extractor B.

El tamaño de la imagen fija el costo (los tokens de entrada crecen con los píxeles) y la
legibilidad de los caracteres chicos; se elige en val.
"""

from __future__ import annotations

import io
import threading
import time
from collections.abc import Sequence
from typing import TYPE_CHECKING

from docextract.extractors._llm import LlmRouteResult, llamar
from docextract.llm.bedrock import BedrockClient, modelo
from docextract.llm.postprocess import CATALOGO_DESCARGADO
from docextract.llm.prompts import mensaje_imagen
from docextract.schemas import DocType, ExtractionResult

if TYPE_CHECKING:
    from PIL.Image import Image

__all__ = ["DEFAULT_MODEL", "NAME", "BedrockVlmExtractor", "pdf_a_imagenes"]

NAME = "bedrock_vlm"
DEFAULT_MODEL = "amazon.nova-lite-v1:0"
LADO = 1600
CALIDAD_JPEG = 85
MAX_PAGINAS = 2

_PDFIUM = threading.Lock()
"""PDFium no es seguro entre hilos: la evaluación llama a Bedrock en paralelo."""


def _jpeg(image: Image, lado: int) -> bytes:
    image = image.convert("RGB")
    escala = lado / max(image.size)
    if escala < 1:
        size = (round(image.width * escala), round(image.height * escala))
        image = image.resize(size)
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=CALIDAD_JPEG)
    return buffer.getvalue()


def pdf_a_imagenes(pdf: bytes, *, lado: int = LADO, max_paginas: int = MAX_PAGINAS) -> list[bytes]:
    """Las primeras páginas del PDF como JPEG en color."""
    import pypdfium2 as pdfium

    with _PDFIUM:
        document = pdfium.PdfDocument(pdf)
        try:
            paginas = []
            for i in range(min(len(document), max_paginas)):
                page = document[i]
                scale = lado / max(page.get_size())
                paginas.append(page.render(scale=scale).to_pil())
        finally:
            document.close()
    return [_jpeg(pagina, lado) for pagina in paginas]


class BedrockVlmExtractor:
    def __init__(
        self,
        model_id: str = DEFAULT_MODEL,
        *,
        bedrock: BedrockClient | None = None,
        lado: int = LADO,
        catalog: object = CATALOGO_DESCARGADO,
    ) -> None:
        self.model = modelo(model_id)
        if not self.model.vision:
            raise ValueError(f"{model_id} no acepta imágenes")
        self.name = f"{NAME}/{model_id}"
        self.bedrock = bedrock or BedrockClient()
        self.lado = lado
        self.catalog = catalog

    def extract(self, images: Sequence[Image], doc_type: DocType) -> ExtractionResult:
        """Interfaz común de los extractores de imagen."""
        start = time.perf_counter()
        jpegs = [_jpeg(image, self.lado) for image in list(images)[:MAX_PAGINAS]]
        return self._llamar(jpegs, doc_type, (time.perf_counter() - start) * 1000).result

    def extract_pdf(self, pdf: bytes, doc_type: DocType) -> LlmRouteResult:
        start = time.perf_counter()
        jpegs = pdf_a_imagenes(pdf, lado=self.lado)
        return self._llamar(jpegs, doc_type, (time.perf_counter() - start) * 1000)

    def _llamar(self, jpegs: list[bytes], doc_type: DocType, previa_ms: float) -> LlmRouteResult:
        return llamar(
            self.bedrock,
            self.model,
            doc_type,
            mensaje_imagen(doc_type, jpegs),
            name=self.name,
            latencia_previa_ms=previa_ms,
            catalog=self.catalog,
        )
