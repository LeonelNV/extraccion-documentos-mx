"""Evaluación de la ruta de texto sobre el dataset sintético (``make eval``).

Mide, sobre un split:

- **Router:** si cada documento fue por la ruta correcta (digital → texto; escaneo y foto →
  imagen).
- **Clasificador de texto:** si reconoce el tipo de los documentos que van por texto.
- **Parsers:** exactitud por campo tras normalizar, CER, porcentaje de documentos con todos
  los campos correctos y latencia p50/p95 (lectura del PDF + clasificación + parser).

Comparación tras normalizar: nombres y texto con la clave de comparación, domicilio con las
abreviaturas expandidas, fechas como fecha, CP a 5 dígitos, estado como entidad e
identificadores sin espacios. Un valor ``None`` (no encontrado) nunca coincide.
"""

import statistics
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from rapidfuzz.distance import Levenshtein

from docextract.dataset import DocumentTruth, Modality
from docextract.entidades import find_entidad
from docextract.normalize import (
    address_key,
    clean_identifier,
    comparison_key,
    normalize_codigo_postal,
    parse_date,
)
from docextract.parsers import PARSERS, extract_text_route
from docextract.router import RouteKind

__all__ = [
    "DocumentEval",
    "cer",
    "evaluate_documents",
    "field_matches",
    "load_manifest",
    "normalize_value",
    "summarize",
    "to_csv_rows",
    "to_markdown",
]

FECHAS = {"fecha_nacimiento", "fecha_emision"}
IDENTIFICADORES = {"curp", "rfc", "clave_elector"}
ENTIDADES = {"estado", "entidad_nacimiento"}
DOMICILIO = {
    "calle",
    "numero_exterior",
    "numero_interior",
    "colonia",
    "ciudad",
    "municipio",
    "tipo_vialidad",
    "nombre_vialidad",
}
SEXOS = {"HOMBRE": "H", "MUJER": "M", "NO BINARIO": "X", "H": "H", "M": "M", "X": "X"}


def normalize_value(field_name: str, value: str | None) -> str | None:
    """Forma canónica de un valor para comparar extracción y verdad."""
    if value is None:
        return None
    if field_name in IDENTIFICADORES:
        return clean_identifier(value)
    if field_name in FECHAS:
        fecha = parse_date(value, allow_two_digit_year=field_name == "fecha_emision")
        return fecha.isoformat() if fecha else comparison_key(value)
    if field_name == "codigo_postal":
        return normalize_codigo_postal(value) or comparison_key(value)
    if field_name in ENTIDADES:
        entidad = find_entidad(value)
        return entidad.clave_curp if entidad else comparison_key(value)
    if field_name == "sexo":
        key = comparison_key(value)
        return SEXOS.get(key, key)
    if field_name in DOMICILIO:
        return address_key(value)
    return comparison_key(value)


def field_matches(field_name: str, predicted: str | None, truth: str) -> bool:
    pred = normalize_value(field_name, predicted)
    return pred is not None and pred == normalize_value(field_name, truth)


def cer(field_name: str, predicted: str | None, truth: str) -> float:
    """Tasa de error por carácter sobre los valores normalizados (1.0 si no se encontró)."""
    expected = normalize_value(field_name, truth) or ""
    pred = normalize_value(field_name, predicted)
    if pred is None:
        return 1.0
    if not expected:
        return 0.0 if not pred else 1.0
    return Levenshtein.distance(pred, expected) / len(expected)


# ---------------------------------------------------------------------------
# Por documento
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FieldEval:
    match: bool
    cer: float
    confidence: float
    predicted: str | None
    truth: str


@dataclass(frozen=True)
class DocumentEval:
    truth: DocumentTruth
    route: RouteKind
    predicted_type: str | None
    fields: dict[str, FieldEval] = field(default_factory=dict)
    latency_ms: float | None = None

    @property
    def route_ok(self) -> bool:
        expected = RouteKind.TEXT if self.truth.modality is Modality.DIGITAL else RouteKind.IMAGE
        return self.route is expected

    @property
    def parsed(self) -> bool:
        return bool(self.fields)

    @property
    def all_correct(self) -> bool:
        return all(f.match for f in self.fields.values())


def load_manifest(root: Path, split: str) -> list[DocumentTruth]:
    path = root / split / "manifest.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    return [DocumentTruth.model_validate_json(line) for line in lines if line.strip()]


def evaluate_document(root: Path, truth: DocumentTruth) -> DocumentEval:
    pdf = (root / truth.pdf).read_bytes()
    start = time.perf_counter()
    out = extract_text_route(pdf, truth.doc_type)
    latency = (time.perf_counter() - start) * 1000
    predicted_type = None
    if out.classification is not None and out.classification.doc_type is not None:
        predicted_type = out.classification.doc_type.value
    if out.result is None:
        return DocumentEval(truth, out.route.kind, predicted_type)
    fields = {}
    for name in PARSERS[truth.doc_type].fields:
        if name not in truth.fields:
            continue
        extracted = out.result.fields.get(name)
        predicted = extracted.value if extracted else None
        fields[name] = FieldEval(
            match=field_matches(name, predicted, truth.fields[name]),
            cer=cer(name, predicted, truth.fields[name]),
            confidence=extracted.confidence if extracted else 0.0,
            predicted=predicted,
            truth=truth.fields[name],
        )
    return DocumentEval(truth, out.route.kind, predicted_type, fields, latency)


def evaluate_documents(
    root: Path,
    documents: Iterable[DocumentTruth],
    *,
    progress: Callable[[int], None] | None = None,
) -> list[DocumentEval]:
    results = []
    for i, truth in enumerate(documents, 1):
        results.append(evaluate_document(root, truth))
        if progress:
            progress(i)
    return results


# ---------------------------------------------------------------------------
# Resumen
# ---------------------------------------------------------------------------
def _percentile(values: list[float], q: float) -> float:
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[int(q) - 1]


def _no_vista(text_docs: list[DocumentEval]) -> dict[str, float] | None:
    docs = [e for e in text_docs if not e.truth.template_seen_in_train]
    if not docs:
        return None
    ok = sum(e.predicted_type == e.truth.doc_type.value for e in docs)
    return {"documentos": len(docs), "exactitud": ok / len(docs)}


def summarize(evals: list[DocumentEval]) -> dict[str, object]:
    """Métricas agregadas, listas para JSON."""
    router_ok = sum(e.route_ok for e in evals)
    confusion = Counter(f"{e.truth.modality}->{e.route}" for e in evals)
    text_docs = [e for e in evals if e.route is RouteKind.TEXT]
    clasif_por_tipo: dict[str, list[bool]] = defaultdict(list)
    for e in text_docs:
        clasif_por_tipo[e.truth.doc_type.value].append(e.predicted_type == e.truth.doc_type.value)

    parsers: dict[str, object] = {}
    for doc_type in PARSERS:
        docs = [e for e in evals if e.truth.doc_type is doc_type and e.parsed]
        if not docs:
            continue
        por_campo: dict[str, dict[str, float]] = {}
        for name in PARSERS[doc_type].fields:
            values = [e.fields[name] for e in docs if name in e.fields]
            if values:
                por_campo[name] = {
                    "n": len(values),
                    "exactitud": sum(v.match for v in values) / len(values),
                    "cer": statistics.fmean(v.cer for v in values),
                }
        latencias = [e.latency_ms for e in docs if e.latency_ms is not None]
        parsers[doc_type.value] = {
            "documentos": len(docs),
            "documentos_100": sum(e.all_correct for e in docs) / len(docs),
            "latencia_p50_ms": _percentile(latencias, 50),
            "latencia_p95_ms": _percentile(latencias, 95),
            "costo_usd_por_documento": 0.0,
            "campos": por_campo,
        }

    return {
        "documentos": len(evals),
        "router": {
            "exactitud": router_ok / len(evals) if evals else 0.0,
            "matriz": dict(sorted(confusion.items())),
        },
        "clasificador_texto": {
            "documentos": len(text_docs),
            "exactitud": (
                sum(ok for oks in clasif_por_tipo.values() for ok in oks) / len(text_docs)
                if text_docs
                else 0.0
            ),
            "por_tipo": {t: sum(oks) / len(oks) for t, oks in sorted(clasif_por_tipo.items())},
            # Generalización: documentos cuya plantilla no aparece en train.
            "plantilla_no_vista": _no_vista(text_docs),
        },
        "parsers": parsers,
    }


def _pct(value: float) -> str:
    return f"{100 * value:.1f}%"


def to_markdown(summary: dict, *, title: str) -> str:
    router = summary["router"]
    clasif = summary["clasificador_texto"]
    lines = [
        f"# {title}",
        "",
        "Generado por `make eval`. No editar a mano.",
        "",
        "## Router y clasificador",
        "",
        "| Métrica | Documentos | Exactitud |",
        "|---|---:|---:|",
        f"| Router (texto vs. imagen) | {summary['documentos']} | {_pct(router['exactitud'])} |",
        f"| Clasificador de texto | {clasif['documentos']} | {_pct(clasif['exactitud'])} |",
    ]
    for doc_type, acc in clasif["por_tipo"].items():
        lines.append(f"| Clasificador: {doc_type} | | {_pct(acc)} |")
    if no_vista := clasif.get("plantilla_no_vista"):
        lines.append(
            f"| Clasificador: plantilla no vista en train | {no_vista['documentos']} | "
            f"{_pct(no_vista['exactitud'])} |"
        )
    for doc_type, data in summary["parsers"].items():
        lines += [
            "",
            f"## Parser de texto: {doc_type}",
            "",
            f"{data['documentos']} documentos digitales · {_pct(data['documentos_100'])} con todos "
            f"los campos correctos · latencia p50 {data['latencia_p50_ms']:.0f} ms, "
            f"p95 {data['latencia_p95_ms']:.0f} ms · costo $0",
            "",
            "| Campo | n | Exactitud | CER |",
            "|---|---:|---:|---:|",
        ]
        for name, values in data["campos"].items():
            lines.append(
                f"| {name} | {values['n']} | {_pct(values['exactitud'])} | {values['cer']:.3f} |"
            )
    return "\n".join(lines) + "\n"


def to_csv_rows(summary: dict, *, extractor: str, split: str) -> list[dict[str, object]]:
    rows = []
    for doc_type, data in summary["parsers"].items():
        for name, values in data["campos"].items():
            rows.append(
                {
                    "extractor": extractor,
                    "split": split,
                    "doc_type": doc_type,
                    "campo": name,
                    "n": values["n"],
                    "exactitud": round(values["exactitud"], 4),
                    "cer": round(values["cer"], 4),
                    "latencia_p50_ms": round(data["latencia_p50_ms"], 1),
                    "latencia_p95_ms": round(data["latencia_p95_ms"], 1),
                    "costo_usd": 0.0,
                }
            )
    return rows
