"""Extractores de imagen detrás de una interfaz común (ver :mod:`docextract.extractors.base`).

- A. ``ocr_rules``: OCR + reglas (fase 5).
- B. ``ocr_llm``: OCR + LLM con salida validada por pydantic (fase 6).
- C1. ``bedrock_vlm``: modelo multimodal en Amazon Bedrock (fase 6).
- C2. ``donut``: Donut con fine-tuning (fase 7).
- C3. ``local_vlm``: VLM abierto local vía Ollama (opcional).
"""

from docextract.extractors.base import Extractor

__all__ = ["Extractor"]
