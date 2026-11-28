"""Entrena el clasificador de documentos (TF-IDF + regresión logística) y lo compara con el
de palabras clave.

    uv run python training/train_clasificador.py        # make train-clasificador

Protocolo:

1. **Texto** de cada documento, el mismo que recibe el clasificador en producción: la capa
   de texto en los digitales y el OCR (extractor A, con caché) en escaneos y fotos.
2. **train** ajusta el modelo. **val** elige la regularización ``C`` (macro-F1) y el umbral
   de "no reconocido": el percentil 1 de la probabilidad máxima en val, es decir, se acepta
   rechazar a lo más 1% de los documentos de tipos conocidos.
3. **test** solo se usa para reportar, con los dos clasificadores sobre los mismos
   documentos. El diseño de comprobante de teléfono nunca entra al entrenamiento: está solo
   en test y mide la generalización.

Escribe el modelo en ``models/clasificador/`` (no se versiona) y las métricas en
``reports/clasificador.md`` y ``reports/clasificador.csv``.
"""

import argparse
import csv
import hashlib
import statistics
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from docextract.classify import classify_text
from docextract.classify_ml import DEFAULT_MODEL_DIR, MlClassifier, build_pipeline
from docextract.dataset import DocumentTruth
from docextract.evaluation import load_manifest
from docextract.layout import TextLayout
from docextract.ocr import OcrCache, OcrConfig, find_tesseract, ocr_many
from docextract.schemas import DocType

ROOT = Path(__file__).resolve().parents[1]
CLASES = [d.value for d in DocType]
NO_RECONOCIDO = "no_reconocido"
C_GRID = (0.3, 1.0, 3.0, 10.0)
SEED = 0


@dataclass(frozen=True)
class Muestra:
    truth: DocumentTruth
    text: str
    ruta: str
    """``texto`` (capa de texto) u ``ocr``."""


def textos(root: Path, split: str, cache: OcrCache, workers: int) -> list[Muestra]:
    docs = load_manifest(root, split)
    ocr_many([root / d.pdf for d in docs if d.image], cache, workers=workers)
    out = []
    for d in docs:
        pdf = (root / d.pdf).read_bytes()
        if d.image:
            out.append(Muestra(d, cache.get(pdf).layout.text, "ocr"))
        else:
            out.append(Muestra(d, TextLayout.from_pdf(pdf).text, "texto"))
    return out


def _labels(muestras: list[Muestra]) -> list[str]:
    return [m.truth.doc_type.value for m in muestras]


def _macro_f1(y_true: list[str], y_pred: list[str]) -> float:
    from sklearn.metrics import f1_score

    return float(f1_score(y_true, y_pred, labels=CLASES, average="macro", zero_division=0))


def entrenar(train: list[Muestra], val: list[Muestra]) -> tuple[MlClassifier, dict]:
    x_train, y_train = [m.text for m in train], _labels(train)
    y_val = _labels(val)
    seleccion = {}
    best = None
    for c in C_GRID:
        model = MlClassifier(build_pipeline(c, SEED), 0.0, {})
        model.pipeline.fit([_prep(t) for t in x_train], y_train)
        pred = [_pred(model.classify_text(m.text)) for m in val]
        f1 = _macro_f1(y_val, pred)
        seleccion[c] = f1
        print(f"  C={c:<5} macro-F1 val={f1:.4f}")
        if best is None or f1 > best[0] + 1e-9:  # empate: el C más chico (más regularizado)
            best = (f1, c, model)
    _, c, model = best
    maximos = [max(p.values()) for p in model.probabilities([m.text for m in val])]
    threshold = float(np.floor(np.percentile(maximos, 1) * 100) / 100)
    model.threshold = threshold
    model.metadata = {
        "modelo": "TF-IDF (palabras 1-2, caracteres 3-5) + regresión logística",
        "C": c,
        "macro_f1_val_por_C": seleccion,
        "umbral": "percentil 1 de la probabilidad máxima en val",
        "entrenado_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "documentos_train": len(train),
        "documentos_val": len(val),
        "hash_textos_train": hashlib.sha256("\n".join(x_train).encode()).hexdigest()[:16],
        "sklearn": __import__("sklearn").__version__,
    }
    return model, model.metadata


def _prep(text: str) -> str:
    from docextract.classify_ml import prepare_text

    return prepare_text(text)


def _pred(classification) -> str:
    return classification.doc_type.value if classification.doc_type else NO_RECONOCIDO


# ---------------------------------------------------------------------------
# Evaluación en test
# ---------------------------------------------------------------------------
def predecir(model: MlClassifier, muestras: list[Muestra]) -> dict[str, list]:
    out: dict[str, list] = {"palabras_clave": [], "ml": [], "ms_palabras_clave": [], "ms_ml": []}
    for m in muestras:
        layout_text = m.text
        start = time.perf_counter()
        kw = classify_text(_layout(layout_text))
        out["ms_palabras_clave"].append((time.perf_counter() - start) * 1000)
        start = time.perf_counter()
        ml = model.classify_text(layout_text)
        out["ms_ml"].append((time.perf_counter() - start) * 1000)
        out["palabras_clave"].append(_pred(kw))
        out["ml"].append(_pred(ml))
    return out


def _layout(text: str) -> TextLayout:
    """El clasificador de palabras clave recibe un layout; su texto basta para clasificar."""
    from docextract.layout import Word

    words = [
        Word(w, 0, 1, i * 10.0, i * 10.0 + 8)
        for i, line in enumerate(text.splitlines())
        for w in line.split()
    ]
    return TextLayout(words)


def metricas(y_true: list[str], y_pred: list[str]) -> dict[str, object]:
    from sklearn.metrics import confusion_matrix, precision_recall_fscore_support

    p, r, f, n = precision_recall_fscore_support(y_true, y_pred, labels=CLASES, zero_division=0)
    columnas = [*CLASES, NO_RECONOCIDO]
    matriz = confusion_matrix(y_true, y_pred, labels=columnas)[: len(CLASES)]
    return {
        "documentos": len(y_true),
        "exactitud": sum(a == b for a, b in zip(y_true, y_pred, strict=True)) / len(y_true),
        "macro_f1": float(np.mean(f)),
        "por_clase": {
            c: {"precision": float(p[i]), "recall": float(r[i]), "f1": float(f[i]), "n": int(n[i])}
            for i, c in enumerate(CLASES)
        },
        "matriz": {
            c: dict(zip(columnas, map(int, row), strict=True))
            for c, row in zip(CLASES, matriz, strict=True)
        },
        "no_reconocidos": sum(p == NO_RECONOCIDO for p in y_pred),
    }


def comparar(muestras: list[Muestra], pred: dict[str, list]) -> dict[str, dict]:
    subsets = {
        "todos": lambda m: True,
        "texto": lambda m: m.ruta == "texto",
        "ocr": lambda m: m.ruta == "ocr",
        "plantilla_no_vista": lambda m: not m.truth.template_seen_in_train,
    }
    out: dict[str, dict] = {}
    for clasificador in ("palabras_clave", "ml"):
        out[clasificador] = {}
        for nombre, keep in subsets.items():
            idx = [i for i, m in enumerate(muestras) if keep(m)]
            if idx:
                y_true = [muestras[i].truth.doc_type.value for i in idx]
                y_pred = [pred[clasificador][i] for i in idx]
                out[clasificador][nombre] = metricas(y_true, y_pred)
        ms = pred[f"ms_{clasificador}"]
        out[clasificador]["latencia_ms"] = {
            "p50": statistics.median(ms),
            "p95": float(np.percentile(ms, 95)),
        }
    return out


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def markdown(resultado: dict, metadata: dict, test: list[Muestra]) -> str:
    kw, ml = resultado["palabras_clave"], resultado["ml"]
    nombres = {
        "todos": "Todos",
        "texto": "Texto del PDF (digitales)",
        "ocr": "Texto del OCR (escaneos y fotos)",
        "plantilla_no_vista": "Comprobante de diseño no visto (teléfono)",
    }
    rutas = Counter(m.ruta for m in test)
    lines = [
        "# Clasificador de documentos: palabras clave vs. TF-IDF + regresión logística",
        "",
        "Generado por `make train-clasificador`. No editar a mano. Split test del dataset "
        f"sintético: {len(test)} documentos ({rutas['texto']} con capa de texto, "
        f"{rutas['ocr']} por OCR). Los dos clasificadores reciben el mismo texto.",
        "",
        f"Modelo: {metadata['modelo']}. C = {metadata['C']} (elegido por macro-F1 en val), "
        f"umbral de no reconocido = {ml_threshold(metadata)} ({metadata['umbral']}). "
        f"Entrenado con {metadata['documentos_train']} documentos de train; el diseño de "
        "teléfono no está en train ni en val.",
        "",
        "## Comparación",
        "",
        "| Subconjunto | Documentos | Palabras clave: exactitud | ML: exactitud "
        "| Palabras clave: macro-F1 | ML: macro-F1 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for key, nombre in nombres.items():
        if key in kw:
            a, b = kw[key], ml[key]
            lines.append(
                f"| {nombre} | {a['documentos']} | {_pct(a['exactitud'])} | "
                f"{_pct(b['exactitud'])} | {a['macro_f1']:.3f} | {b['macro_f1']:.3f} |"
            )
    lines += [
        "",
        f"Latencia de clasificar (sin contar el OCR): palabras clave p50 "
        f"{kw['latencia_ms']['p50']:.2f} ms; ML p50 {ml['latencia_ms']['p50']:.2f} ms, "
        f"p95 {ml['latencia_ms']['p95']:.2f} ms.",
        "",
        'Las métricas con macro-F1 cuentan "no reconocido" como error. En el diseño no '
        "visto todos los documentos son comprobantes, así que su macro-F1 promedia clases "
        "sin documentos; ahí la métrica útil es la exactitud.",
    ]
    for clasificador, data in (("Palabras clave", kw), ("ML", ml)):
        todos = data["todos"]
        lines += [
            "",
            f"## {clasificador}: por clase (todos)",
            "",
            "| Clase | n | Precisión | Recall | F1 |",
            "|---|---:|---:|---:|---:|",
        ]
        for c, v in todos["por_clase"].items():
            lines.append(
                f"| {c} | {v['n']} | {_pct(v['precision'])} | {_pct(v['recall'])} | {v['f1']:.3f} |"
            )
        columnas = [*CLASES, NO_RECONOCIDO]
        lines += [
            "",
            "Matriz de confusión (filas: tipo real; columnas: predicho):",
            "",
            "| Real \\ Predicho | " + " | ".join(columnas) + " |",
            "|---|" + "---:|" * len(columnas),
        ]
        for c, row in todos["matriz"].items():
            lines.append(f"| {c} | " + " | ".join(str(row[k]) for k in columnas) + " |")
    return "\n".join(lines) + "\n"


def ml_threshold(metadata: dict) -> str:
    return f"{metadata.get('threshold_valor', 0):.2f}"


def csv_rows(resultado: dict) -> list[dict[str, object]]:
    rows = []
    for clasificador in ("palabras_clave", "ml"):
        for subset, data in resultado[clasificador].items():
            if subset == "latencia_ms":
                continue
            rows.append(
                {
                    "clasificador": clasificador,
                    "subconjunto": subset,
                    "documentos": data["documentos"],
                    "exactitud": round(data["exactitud"], 4),
                    "macro_f1": round(data["macro_f1"], 4),
                    "no_reconocidos": data["no_reconocidos"],
                }
            )
    return rows


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--data", type=Path, default=ROOT / "data" / "synthetic")
    parser.add_argument("--cache", type=Path, default=ROOT / "data" / "cache" / "ocr")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--out", type=Path, default=ROOT / "reports")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)

    if not (args.data / "train" / "manifest.jsonl").exists():
        print(f"No hay dataset en {args.data}. Genéralo con `make synth`.", file=sys.stderr)
        return 1
    find_tesseract()
    cache = OcrCache(args.cache)
    print("Texto de train, val y test (OCR con caché):")
    splits = {s: textos(args.data, s, cache, args.workers) for s in ("train", "val", "test")}
    for s, muestras in splits.items():
        assert s == "test" or all(m.truth.template_seen_in_train for m in muestras)
        print(f"  {s}: {len(muestras)} documentos")

    print("Selección de C en val:")
    model, metadata = entrenar(splits["train"], splits["val"])
    metadata["threshold_valor"] = model.threshold
    metadata["ocr"] = OcrConfig().key()
    model.metadata = metadata
    model.save(args.model)
    print(f"Modelo: C={metadata['C']}, umbral={model.threshold:.2f} → {args.model}")

    test = splits["test"]
    resultado = comparar(test, predecir(model, test))
    md = markdown(resultado, metadata, test)
    print(md)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "clasificador.md").write_text(md, encoding="utf-8")
    rows = csv_rows(resultado)
    with (args.out / "clasificador.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Escrito: {args.out / 'clasificador.md'} y clasificador.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
