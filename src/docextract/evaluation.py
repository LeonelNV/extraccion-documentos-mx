"""Evaluación sobre el dataset sintético (``make eval``).

Cada documento va por su ruta: los digitales por la capa de texto (``texto_reglas``) y los
escaneos y fotos por el extractor A (``ocr_reglas``: OCR + las mismas reglas). Mide, sobre
un split:

- **Router:** si cada documento fue por la ruta correcta (digital → texto; escaneo y foto →
  imagen).
- **Clasificador de palabras clave:** si reconoce el tipo, por separado con el texto del PDF
  y con el del OCR.
- **Extracción, por tipo de documento y modalidad:** exactitud por campo tras normalizar,
  CER, porcentaje de documentos con todos los campos correctos y latencia p50/p95 (lectura
  del PDF, OCR si aplica, clasificación y parser).

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
from docextract.extractors.ocr_rules import NAME as OCR_NAME
from docextract.extractors.ocr_rules import OcrRulesExtractor
from docextract.normalize import (
    address_key,
    clean_identifier,
    comparison_key,
    normalize_codigo_postal,
    parse_date,
)
from docextract.parsers import EXTRACTOR_NAME, PARSERS, extract_text_route
from docextract.router import RouteKind
from docextract.schemas import DocType, ExtractionResult

__all__ = [
    "DocumentEval",
    "cer",
    "evaluate_document",
    "evaluate_documents",
    "evaluate_image_result",
    "field_evals",
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
    extractor: str | None = None
    """``texto_reglas``, ``ocr_reglas`` o ``None`` si no se leyó el texto."""
    costo_usd: float = 0.0
    """Costo del modelo remoto (extractores B y C1)."""
    respuesta_valida: bool = True
    """Falso si el modelo respondió algo que no cumple el esquema."""

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


def evaluate_document(
    root: Path, truth: DocumentTruth, *, ocr: OcrRulesExtractor | None = None
) -> DocumentEval:
    """Lee el documento por su ruta. Sin ``ocr``, los documentos de imagen no se extraen."""
    pdf = (root / truth.pdf).read_bytes()
    start = time.perf_counter()
    out = extract_text_route(pdf, truth.doc_type)
    latency = (time.perf_counter() - start) * 1000
    classification, result, extractor = out.classification, out.result, EXTRACTOR_NAME
    if out.route.kind is RouteKind.IMAGE:
        if ocr is None:
            return DocumentEval(truth, out.route.kind, None)
        image = ocr.extract_pdf(pdf, truth.doc_type)
        classification, result, extractor = image.classification, image.result, OCR_NAME
        # La latencia del OCR es la medida al leer, también cuando viene de la caché.
        if result is not None:
            latency += result.latency_ms or 0.0
    predicted_type = None
    if classification is not None and classification.doc_type is not None:
        predicted_type = classification.doc_type.value
    if result is None:
        return DocumentEval(truth, out.route.kind, predicted_type, extractor=extractor)
    fields = field_evals(truth, result)
    return DocumentEval(truth, out.route.kind, predicted_type, fields, latency, extractor)


def field_evals(truth: DocumentTruth, result: ExtractionResult) -> dict[str, FieldEval]:
    """Compara los campos que intentan todos los extractores (los del parser de reglas)."""
    fields = {}
    for name in PARSERS[truth.doc_type].fields:
        if name not in truth.fields:
            continue
        extracted = result.fields.get(name)
        predicted = extracted.value if extracted else None
        fields[name] = FieldEval(
            match=field_matches(name, predicted, truth.fields[name]),
            cer=cer(name, predicted, truth.fields[name]),
            confidence=extracted.confidence if extracted else 0.0,
            predicted=predicted,
            truth=truth.fields[name],
        )
    return fields


def evaluate_image_result(
    truth: DocumentTruth, result: ExtractionResult, *, respuesta_valida: bool = True
) -> DocumentEval:
    """Evalúa la salida de cualquier extractor de imagen (A, B, C1...) para un documento."""
    return DocumentEval(
        truth,
        RouteKind.IMAGE,
        None,
        field_evals(truth, result),
        result.latency_ms,
        result.extractor,
        costo_usd=result.usage.estimated_cost_usd if result.usage else 0.0,
        respuesta_valida=respuesta_valida,
    )


def evaluate_documents(
    root: Path,
    documents: Iterable[DocumentTruth],
    *,
    ocr: OcrRulesExtractor | None = None,
    progress: Callable[[int], None] | None = None,
) -> list[DocumentEval]:
    results = []
    for i, truth in enumerate(documents, 1):
        results.append(evaluate_document(root, truth, ocr=ocr))
        if progress:
            progress(i)
    return results


# ---------------------------------------------------------------------------
# Resumen
# ---------------------------------------------------------------------------
MODALIDADES = tuple(m.value for m in Modality)
RUTAS = {"texto": EXTRACTOR_NAME, "ocr": OCR_NAME}


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[int(q) - 1]


def _accuracy(docs: list[DocumentEval]) -> float:
    return sum(e.predicted_type == e.truth.doc_type.value for e in docs) / len(docs)


def _classifier(docs: list[DocumentEval]) -> dict[str, object]:
    por_tipo: dict[str, list[DocumentEval]] = defaultdict(list)
    for e in docs:
        por_tipo[e.truth.doc_type.value].append(e)
    no_vista = [e for e in docs if not e.truth.template_seen_in_train]
    return {
        "documentos": len(docs),
        "exactitud": _accuracy(docs),
        "por_tipo": {t: _accuracy(d) for t, d in sorted(por_tipo.items())},
        # Generalización: documentos cuya plantilla no aparece en train.
        "plantilla_no_vista": (
            {"documentos": len(no_vista), "exactitud": _accuracy(no_vista)} if no_vista else None
        ),
    }


def _extraction(docs: list[DocumentEval], doc_type: DocType) -> dict[str, object]:
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
    return {
        "extractor": docs[0].extractor,
        "documentos": len(docs),
        "documentos_100": sum(e.all_correct for e in docs) / len(docs),
        "latencia_p50_ms": _percentile(latencias, 50),
        "latencia_p95_ms": _percentile(latencias, 95),
        "costo_usd_por_documento": 0.0,
        "campos": por_campo,
    }


def summarize(evals: list[DocumentEval]) -> dict[str, object]:
    """Métricas agregadas, listas para JSON."""
    router_ok = sum(e.route_ok for e in evals)
    confusion = Counter(f"{e.truth.modality}->{e.route}" for e in evals)
    clasificador = {}
    for ruta, name in RUTAS.items():
        docs = [e for e in evals if e.extractor == name]
        if docs:
            clasificador[ruta] = _classifier(docs)
    extraccion: dict[str, dict[str, object]] = {}
    for doc_type in PARSERS:
        por_modalidad = {}
        for modalidad in MODALIDADES:
            docs = [
                e
                for e in evals
                if e.truth.doc_type is doc_type and e.truth.modality == modalidad and e.parsed
            ]
            if docs:
                por_modalidad[modalidad] = _extraction(docs, doc_type)
        if por_modalidad:
            extraccion[doc_type.value] = por_modalidad
    no_vista: dict[str, dict[str, float]] = {}
    for modalidad in MODALIDADES:
        docs = [
            e
            for e in evals
            if not e.truth.template_seen_in_train and e.truth.modality == modalidad and e.parsed
        ]
        if docs:
            campos = [f.match for e in docs for f in e.fields.values()]
            no_vista[modalidad] = {
                "documentos": len(docs),
                "documentos_100": sum(e.all_correct for e in docs) / len(docs),
                "exactitud_campos": sum(campos) / len(campos),
            }
    return {
        "documentos": len(evals),
        "router": {
            "exactitud": router_ok / len(evals) if evals else 0.0,
            "matriz": dict(sorted(confusion.items())),
        },
        "clasificador_palabras_clave": clasificador,
        "extraccion": extraccion,
        # Generalización de la extracción al diseño de comprobante que no está en train.
        "extraccion_plantilla_no_vista": no_vista,
    }


def _pct(value: float) -> str:
    return f"{100 * value:.1f}%"


def to_markdown(summary: dict, *, title: str) -> str:
    router = summary["router"]
    lines = [
        f"# {title}",
        "",
        "Generado por `make eval`. No editar a mano. Los documentos digitales van por la capa "
        "de texto (`texto_reglas`); los escaneos y fotos, por el extractor A (`ocr_reglas`: "
        "Tesseract + las mismas reglas). Costo: $0 (sin servicios externos).",
        "",
        "## Resumen por documento y modalidad",
        "",
        "| Documento | Modalidad | Extractor | Documentos | 100% correctos | p50 | p95 |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for doc_type, modalidades in summary["extraccion"].items():
        for modalidad, data in modalidades.items():
            lines.append(
                f"| {doc_type} | {modalidad} | `{data['extractor']}` | {data['documentos']} | "
                f"{_pct(data['documentos_100'])} | {data['latencia_p50_ms']:.0f} ms | "
                f"{data['latencia_p95_ms']:.0f} ms |"
            )
    if no_vista := summary.get("extraccion_plantilla_no_vista"):
        lines += [
            "",
            "## Comprobante de diseño no visto en train",
            "",
            "Las reglas del comprobante se escribieron sin este diseño: mide la generalización.",
            "",
            "| Modalidad | Documentos | 100% correctos | Campos correctos |",
            "|---|---:|---:|---:|",
        ]
        for modalidad, data in no_vista.items():
            lines.append(
                f"| {modalidad} | {data['documentos']} | {_pct(data['documentos_100'])} | "
                f"{_pct(data['exactitud_campos'])} |"
            )
    lines += [
        "",
        "## Router y clasificador de palabras clave",
        "",
        "| Métrica | Documentos | Exactitud |",
        "|---|---:|---:|",
        f"| Router (texto vs. imagen) | {summary['documentos']} | {_pct(router['exactitud'])} |",
    ]
    for ruta, clasif in summary["clasificador_palabras_clave"].items():
        origen = "PDF" if ruta == "texto" else "OCR"
        lines.append(
            f"| Clasificador, texto del {origen} | {clasif['documentos']} | "
            f"{_pct(clasif['exactitud'])} |"
        )
        for doc_type, acc in clasif["por_tipo"].items():
            lines.append(f"| · {doc_type} | | {_pct(acc)} |")
        if no_vista := clasif.get("plantilla_no_vista"):
            lines.append(
                f"| · plantilla no vista en train | {no_vista['documentos']} | "
                f"{_pct(no_vista['exactitud'])} |"
            )
    for doc_type, modalidades in summary["extraccion"].items():
        nombres: list[str] = []
        for data in modalidades.values():
            nombres += [n for n in data["campos"] if n not in nombres]
        lines += [
            "",
            f"## {doc_type}: exactitud por campo",
            "",
            "| Campo | " + " | ".join(modalidades) + " |",
            "|---|" + "---:|" * len(modalidades),
        ]
        for name in nombres:
            cells = []
            for data in modalidades.values():
                v = data["campos"].get(name)
                cells.append(f"{_pct(v['exactitud'])} (CER {v['cer']:.3f})" if v else "")
            lines.append(f"| {name} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def to_csv_rows(summary: dict, *, split: str) -> list[dict[str, object]]:
    rows = []
    for doc_type, modalidades in summary["extraccion"].items():
        for modalidad, data in modalidades.items():
            for name, values in data["campos"].items():
                rows.append(
                    {
                        "extractor": data["extractor"],
                        "split": split,
                        "doc_type": doc_type,
                        "modalidad": modalidad,
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
