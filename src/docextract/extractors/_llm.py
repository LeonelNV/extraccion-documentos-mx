"""Lo que comparten los extractores B y C1: llamar al modelo y armar el resultado."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from docextract.llm.bedrock import BedrockClient, ModeloBedrock, Respuesta
from docextract.llm.postprocess import CATALOGO_DESCARGADO, build_fields
from docextract.llm.prompts import SISTEMA, json_schema, validar
from docextract.schemas import DocType, ExtractedField, ExtractionResult, ModelUsage

MAX_TOKENS = 700
"""Tope de salida por llamada. El JSON más largo (CSF, 13 campos) usa ~300 tokens."""


@dataclass(frozen=True)
class LlmRouteResult:
    result: ExtractionResult
    respuesta: Respuesta
    valida: bool
    """Si la respuesta cumplió el esquema. Si no, los campos quedan vacíos."""


def llamar(
    bedrock: BedrockClient,
    model: ModeloBedrock,
    doc_type: DocType,
    content: list[dict[str, Any]],
    *,
    name: str,
    latencia_previa_ms: float,
    catalog: object = CATALOGO_DESCARGADO,
) -> LlmRouteResult:
    respuesta = bedrock.extraer(
        model,
        system=SISTEMA,
        content=content,
        schema=json_schema(doc_type),
        max_tokens=MAX_TOKENS,
    )
    raw = validar(doc_type, respuesta.datos)
    fields: dict[str, ExtractedField] = {}
    if raw is not None:
        fields = build_fields(doc_type, raw, catalog=catalog)
    result = ExtractionResult(
        doc_type=doc_type,
        extractor=name,
        fields=fields,
        latency_ms=latencia_previa_ms + respuesta.latencia_ms,
        usage=ModelUsage(
            input_tokens=respuesta.input_tokens,
            output_tokens=respuesta.output_tokens,
            estimated_cost_usd=respuesta.costo_usd,
        ),
    )
    return LlmRouteResult(result, respuesta, raw is not None)
