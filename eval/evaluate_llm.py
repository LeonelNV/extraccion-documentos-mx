"""Compara los extractores de imagen A (OCR + reglas), B (OCR + LLM) y C1 (visión en Bedrock).

    uv run python eval/evaluate_llm.py --split val          # elegir modelos (desarrollo)
    uv run python eval/evaluate_llm.py --split test         # lo que reporta make eval-llm
    uv run python eval/evaluate_llm.py --split val --limite 8 --no-save   # piloto barato

**Cuesta dinero** (Amazon Bedrock) y **solo acepta el dataset sintético**: se niega a leer
documentos fuera de ``data/synthetic/``. Nunca se usa con ``data/real/``: ``eval_private.py``
no llama a Bedrock.

Control del gasto:

- ``--presupuesto`` (USD, por defecto 10) es el tope **acumulado** de todas las corridas:
  el gasto se lleva en ``data/cache/llm/gasto.json``. Antes de cada llamada se aparta el
  peor caso; si pasaría el tope, la corrida se detiene.
- Las respuestas se guardan en ``data/cache/llm/`` por hash de la petición: repetir una
  corrida no vuelve a llamar ni a cobrar. El costo reportado por documento es el de la
  llamada original.

Escribe ``reports/comparacion.{md,csv}`` (test) o ``reports/comparacion_val.{md,csv}`` (val)
y el detalle en ``reports/runs/``. Los modelos se eligen en val; test solo reporta.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

from docextract.comparison import summarize_comparison, to_csv_rows, to_markdown
from docextract.dataset import DocumentTruth
from docextract.evaluation import DocumentEval, evaluate_image_result, load_manifest
from docextract.extractors.bedrock_vlm import LADO, BedrockVlmExtractor
from docextract.extractors.ocr_llm import OcrLlmExtractor
from docextract.extractors.ocr_rules import OcrRulesExtractor
from docextract.llm.bedrock import (
    BedrockClient,
    LlmCache,
    Presupuesto,
    PresupuestoAgotadoError,
    precios,
)
from docextract.llm.prompts import PROMPT_VERSION
from docextract.ocr import OcrCache, OcrConfig, ocr_many

ROOT = Path(__file__).resolve().parents[1]
SINTETICOS = ROOT / "data" / "synthetic"
OCR_CACHE = ROOT / "data" / "cache" / "ocr"
LLM_CACHE = ROOT / "data" / "cache" / "llm"
MODELOS_B = ("amazon.nova-micro-v1:0", "amazon.nova-lite-v1:0", "amazon.nova-pro-v1:0")
MODELOS_C1 = ("amazon.nova-lite-v1:0", "amazon.nova-pro-v1:0", "qwen.qwen3-vl-235b-a22b")


def solo_sinteticos(data: Path) -> None:
    """Bedrock solo recibe documentos sintéticos."""
    data = data.resolve()
    if data != SINTETICOS.resolve() and SINTETICOS.resolve() not in data.parents:
        raise SystemExit(f"Solo se evalúan con Bedrock datos de {SINTETICOS}, no {data}.")


class Gasto:
    """Gasto acumulado en Bedrock de todas las corridas (no se versiona)."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def leer(self) -> float:
        if not self.path.exists():
            return 0.0
        return float(json.loads(self.path.read_text(encoding="utf-8"))["gastado_usd"])

    def guardar(self, gastado: float) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"gastado_usd": round(gastado, 6), "actualizado_utc": datetime.now(UTC).isoformat()}
        self.path.write_text(json.dumps(data) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--data", type=Path, default=SINTETICOS)
    parser.add_argument("--split", default="test", choices=("val", "test"))
    parser.add_argument("--out", type=Path, default=ROOT / "reports")
    parser.add_argument("--modelos-b", nargs="*", default=list(MODELOS_B))
    parser.add_argument("--modelos-c1", nargs="*", default=list(MODELOS_C1))
    parser.add_argument("--lado", type=int, default=LADO, help="píxeles del lado mayor (C1)")
    parser.add_argument("--presupuesto", type=float, default=10.0, help="tope acumulado, USD")
    parser.add_argument("--workers", type=int, default=4, help="llamadas en paralelo")
    parser.add_argument("--limite", type=int, default=0, help="solo los primeros N documentos")
    parser.add_argument("--no-save", action="store_true", help="solo imprime el resumen")
    parser.add_argument("--errores", type=int, default=0, help="muestra N campos con error")
    args = parser.parse_args(argv)

    solo_sinteticos(args.data)
    if not (args.data / args.split / "manifest.jsonl").exists():
        print(f"No hay dataset en {args.data}. Genéralo con `make synth`.", file=sys.stderr)
        return 1
    documents = [d for d in load_manifest(args.data, args.split) if d.image]
    if args.limite:
        documents = documents[: args.limite]

    # OCR (extractor A y entrada del B), con la misma caché que make eval.
    ocr_config, ocr_cache = OcrConfig(), OcrCache(OCR_CACHE)
    ocr_many([args.data / d.pdf for d in documents], ocr_cache, ocr_config, workers=4)

    gasto = Gasto(LLM_CACHE / "gasto.json")
    presupuesto = Presupuesto(args.presupuesto, gastado_usd=gasto.leer())
    inicial = presupuesto.gastado_usd
    bedrock = BedrockClient(presupuesto=presupuesto, cache=LlmCache(LLM_CACHE))
    extractores = [OcrRulesExtractor(config=ocr_config, cache=ocr_cache)]
    extractores += [
        OcrLlmExtractor(m, bedrock=bedrock, ocr_cache=ocr_cache) for m in args.modelos_b
    ]
    extractores += [
        BedrockVlmExtractor(m, bedrock=bedrock, lado=args.lado) for m in args.modelos_c1
    ]

    def evaluar(extractor, truth: DocumentTruth) -> DocumentEval:
        pdf = (args.data / truth.pdf).read_bytes()
        out = extractor.extract_pdf(pdf, truth.doc_type)
        valida = getattr(out, "valida", True)
        return evaluate_image_result(truth, out.result, respuesta_valida=valida)

    print(
        f"{len(documents)} documentos x {len(extractores)} extractores, split {args.split}. "
        f"Gastado antes: ${inicial:.4f} de ${args.presupuesto:.2f}."
    )
    evals: list[DocumentEval] = []
    detenido = None
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(evaluar, x, d) for x in extractores for d in documents]
            for i, future in enumerate(as_completed(futures), 1):
                try:
                    evals.append(future.result())
                except PresupuestoAgotadoError as error:
                    detenido = str(error)
                    for f in futures:
                        f.cancel()
                    break
                if i % 50 == 0 or i == len(futures):
                    print(f"  {i}/{len(futures)}  ${presupuesto.gastado_usd:.4f}", end="\r")
    finally:
        gasto.guardar(presupuesto.gastado_usd)
    print()
    print(
        f"Gasto de esta corrida: ${presupuesto.gastado_usd - inicial:.4f} USD "
        f"(acumulado ${presupuesto.gastado_usd:.4f} de ${args.presupuesto:.2f})."
    )
    if detenido:
        print(f"Corrida detenida por el tope: {detenido}", file=sys.stderr)
        return 2

    orden = {x.name: i for i, x in enumerate(extractores)}
    docs = {d.pdf: i for i, d in enumerate(documents)}
    evals.sort(key=lambda e: (orden[e.extractor], docs[e.truth.pdf]))
    summary = summarize_comparison(evals)
    nota = f"Imagen para C1: JPEG en color, {args.lado} px de lado mayor. Prompt v{PROMPT_VERSION}."
    markdown = to_markdown(
        summary, title=f"Comparación de extractores de imagen, split {args.split}", nota=nota
    )
    print(markdown)

    if args.errores:
        shown = 0
        for e in evals:
            for name, f in e.fields.items():
                if not f.match and shown < args.errores:
                    # Datos sintéticos: se pueden mostrar.
                    ident = (
                        f"{e.extractor} {e.truth.persona_id} {e.truth.doc_type} {e.truth.modality}"
                    )
                    print(f"  {ident} {name}: {f.predicted!r} vs {f.truth!r}")
                    shown += 1

    if args.no_save or args.limite:
        return 0
    sufijo = "" if args.split == "test" else f"_{args.split}"
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"comparacion{sufijo}.md").write_text(markdown, encoding="utf-8")
    rows = to_csv_rows(summary, split=args.split)
    with (args.out / f"comparacion{sufijo}.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    now = datetime.now(UTC)
    run = {
        "fecha_utc": now.isoformat(timespec="seconds"),
        "split": args.split,
        "extractores": [x.name for x in extractores],
        "lado_c1": args.lado,
        "prompt": PROMPT_VERSION,
        "ocr": ocr_config.key(),
        "precios": {k: precios()[k] for k in ("fuente", "fecha", "region")},
        "gasto_corrida_usd": round(presupuesto.gastado_usd - inicial, 6),
        "resumen": summary,
    }
    runs = args.out / "runs"
    runs.mkdir(exist_ok=True)
    path = runs / f"{now:%Y%m%dT%H%M%SZ}_comparacion_{args.split}.json"
    path.write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Escrito: {args.out / f'comparacion{sufijo}.md'}, .csv y {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
