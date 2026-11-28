"""Comparación de extractores de imagen (A, B, C1...) sobre los mismos documentos.

Solo escaneos y fotos: los digitales van por la capa de texto y no pasan por estos
extractores. Por extractor se reporta:

- documentos con todos los campos correctos y exactitud de campos;
- lo mismo por tipo de documento y modalidad, y en el diseño de comprobante no visto;
- exactitud por campo;
- latencia p50/p95 y costo por documento (tokens reales x precio de Bedrock);
- respuestas que no cumplieron el esquema.
"""

from __future__ import annotations

import statistics
from collections import defaultdict

from docextract.evaluation import MODALIDADES, DocumentEval, _percentile
from docextract.llm.bedrock import precios

__all__ = ["etiqueta", "summarize_comparison", "to_csv_rows", "to_markdown"]


def etiqueta(extractor: str) -> str:
    """Nombre legible: ``ocr_llm/amazon.nova-lite-v1:0`` -> ``B: OCR + Nova Lite``."""
    familia, _, model_id = extractor.partition("/")
    nombre = precios()["modelos"].get(model_id, {}).get("nombre", model_id)
    if familia == "ocr_reglas":
        return "A: OCR + reglas"
    if familia == "ocr_llm":
        return f"B: OCR + {nombre}"
    if familia == "bedrock_vlm":
        return f"C1: {nombre} (imagen)"
    return extractor


def _bloque(docs: list[DocumentEval]) -> dict[str, float]:
    campos = [f.match for e in docs for f in e.fields.values()]
    return {
        "documentos": len(docs),
        "documentos_100": sum(e.all_correct for e in docs) / len(docs),
        "exactitud_campos": sum(campos) / len(campos) if campos else 0.0,
    }


def summarize_comparison(evals: list[DocumentEval]) -> dict[str, object]:
    por_extractor: dict[str, list[DocumentEval]] = defaultdict(list)
    for e in evals:
        if e.extractor:
            por_extractor[e.extractor].append(e)
    out: dict[str, object] = {}
    for name, docs in por_extractor.items():
        latencias = [e.latency_ms for e in docs if e.latency_ms is not None]
        por_documento: dict[str, dict[str, object]] = {}
        campos: dict[str, dict[str, float]] = {}
        for doc_type in sorted({e.truth.doc_type.value for e in docs}):
            del_tipo = [e for e in docs if e.truth.doc_type.value == doc_type]
            por_documento[doc_type] = {
                m: _bloque(d)
                for m in MODALIDADES
                if (d := [e for e in del_tipo if e.truth.modality == m])
            }
            matches: dict[str, list[bool]] = defaultdict(list)
            for e in del_tipo:
                for field_name, f in e.fields.items():
                    matches[field_name].append(f.match)
            campos[doc_type] = {k: sum(v) / len(v) for k, v in matches.items()}
        no_vista = [e for e in docs if not e.truth.template_seen_in_train]
        costos = [e.costo_usd for e in docs]
        out[name] = {
            "etiqueta": etiqueta(name),
            **_bloque(docs),
            "respuestas_invalidas": sum(not e.respuesta_valida for e in docs),
            "latencia_p50_ms": _percentile(latencias, 50),
            "latencia_p95_ms": _percentile(latencias, 95),
            "costo_usd_por_documento": statistics.fmean(costos) if costos else 0.0,
            "costo_usd_total": sum(costos),
            "por_documento": por_documento,
            "plantilla_no_vista": _bloque(no_vista) if no_vista else None,
            "campos": campos,
        }
    return {"extractores": out}


def _pct(value: float) -> str:
    return f"{100 * value:.1f}%"


def _usd(value: float) -> str:
    return f"${value:.5f}" if value else "$0"


def to_markdown(summary: dict, *, title: str, nota: str = "") -> str:
    extractores: dict[str, dict] = summary["extractores"]
    names = list(extractores)
    info = precios()
    lines = [
        f"# {title}",
        "",
        "Generado por `eval/evaluate_llm.py`. No editar a mano. Solo escaneos y fotos (los "
        "digitales van por la capa de texto). Todos los extractores leen los mismos documentos.",
        "",
        f"Costo: tokens que reporta Bedrock x precios de {info['fuente']} ({info['region']}, "
        f"consultados el {info['fecha']}).",
    ]
    if nota:
        lines += ["", nota]
    lines += [
        "",
        "## Resumen",
        "",
        "| Extractor | Documentos | 100% correctos | Campos correctos | p50 | p95 "
        "| Costo por documento | Respuestas inválidas |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name in names:
        d = extractores[name]
        lines.append(
            f"| {d['etiqueta']} | {d['documentos']} | {_pct(d['documentos_100'])} | "
            f"{_pct(d['exactitud_campos'])} | {d['latencia_p50_ms'] / 1000:.1f} s | "
            f"{d['latencia_p95_ms'] / 1000:.1f} s | {_usd(d['costo_usd_por_documento'])} | "
            f"{d['respuestas_invalidas']} |"
        )

    lines += [
        "",
        "## Documentos con todos los campos correctos, por tipo y modalidad",
        "",
        "| Documento | Modalidad | n | "
        + " | ".join(extractores[n]["etiqueta"] for n in names)
        + " |",
        "|---|---|---:|" + "---:|" * len(names),
    ]
    primero = extractores[names[0]]["por_documento"]
    for doc_type, modalidades in primero.items():
        for modalidad, bloque in modalidades.items():
            cells = []
            for name in names:
                b = extractores[name]["por_documento"].get(doc_type, {}).get(modalidad)
                cells.append(_pct(b["documentos_100"]) if b else "")
            lines.append(
                f"| {doc_type} | {modalidad} | {bloque['documentos']} | " + " | ".join(cells) + " |"
            )
    if extractores[names[0]]["plantilla_no_vista"]:
        cells = []
        for name in names:
            b = extractores[name]["plantilla_no_vista"]
            cells.append(f"{_pct(b['documentos_100'])} ({_pct(b['exactitud_campos'])} campos)")
        n = extractores[names[0]]["plantilla_no_vista"]["documentos"]
        lines.append(
            "| comprobante, diseño no visto | escaneo y foto | "
            + f"{n} | "
            + " | ".join(cells)
            + " |"
        )

    for doc_type in primero:
        field_names: list[str] = []
        for name in names:
            field_names += [
                f for f in extractores[name]["campos"].get(doc_type, {}) if f not in field_names
            ]
        lines += [
            "",
            f"## {doc_type}: exactitud por campo",
            "",
            "| Campo | " + " | ".join(extractores[n]["etiqueta"] for n in names) + " |",
            "|---|" + "---:|" * len(names),
        ]
        for field_name in field_names:
            cells = []
            for name in names:
                v = extractores[name]["campos"].get(doc_type, {}).get(field_name)
                cells.append(_pct(v) if v is not None else "")
            lines.append(f"| {field_name} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def to_csv_rows(summary: dict, *, split: str) -> list[dict[str, object]]:
    rows = []
    for name, d in summary["extractores"].items():
        for doc_type, modalidades in d["por_documento"].items():
            for modalidad, b in modalidades.items():
                rows.append(
                    {
                        "extractor": name,
                        "split": split,
                        "doc_type": doc_type,
                        "modalidad": modalidad,
                        "documentos": b["documentos"],
                        "documentos_100": round(b["documentos_100"], 4),
                        "exactitud_campos": round(b["exactitud_campos"], 4),
                        "latencia_p50_ms": round(d["latencia_p50_ms"], 1),
                        "costo_usd_por_documento": round(d["costo_usd_por_documento"], 6),
                    }
                )
    return rows
