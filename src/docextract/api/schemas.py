"""Esquemas HTTP de la API.

Envuelven los esquemas de dominio (:mod:`docextract.schemas`) para que los extractores
no dependan de la capa de API. La API se implementa en la fase 8.
"""

from typing import Literal

from pydantic import BaseModel

from docextract.schemas import PrefilledForm


class ExtractResponse(PrefilledForm):
    """Respuesta de ``POST /extract``: el formulario prellenado y las advertencias globales."""


class HealthResponse(BaseModel):
    """Respuesta de ``GET /health``."""

    status: Literal["ok"] = "ok"
    version: str
