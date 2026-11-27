"""Interfaz común de los extractores de imagen."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    # Pillow se agrega como dependencia en la fase 3; aquí solo se usa para el tipo.
    from PIL.Image import Image

    from docextract.schemas import DocType, ExtractionResult


@runtime_checkable
class Extractor(Protocol):
    """Extrae los campos de un documento a partir de las imágenes de sus páginas.

    Los extractores no deciden ``needs_review``: devuelven valores y confianzas, y la
    fusión aplica el umbral configurable.
    """

    name: str

    def extract(self, images: Sequence[Image], doc_type: DocType) -> ExtractionResult: ...
