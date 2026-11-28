"""Evalúa la ruta de texto y el extractor A (OCR + reglas) sobre el dataset sintético.

    uv run python eval/evaluate.py                      # split test (lo que reporta make eval)
    uv run python eval/evaluate.py --split val --errores 10 --no-save   # desarrollo
    uv run python eval/evaluate.py --sin-ocr            # solo la ruta de texto (rápido)

El OCR de los escaneos y fotos se guarda en ``data/cache/ocr/`` (ignorado por git), por
hash del PDF y configuración: la segunda corrida no vuelve a leer las imágenes. La latencia
reportada es la medida al hacer el OCR.

Escribe:

- ``reports/resultados.md`` y ``reports/resultados.csv``: el resumen, que se versiona y del
  que salen los números del README;
- ``reports/runs/<fecha>_<split>.json``: el detalle de cada corrida (no se versiona).

Las reglas se desarrollan mirando train y val; test solo se usa para reportar.
"""

import argparse
import csv
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from docextract.dataset import DatasetInfo
from docextract.evaluation import (
    evaluate_documents,
    load_manifest,
    summarize,
    to_csv_rows,
    to_markdown,
)
from docextract.extractors.ocr_rules import OcrRulesExtractor
from docextract.ocr import OcrCache, OcrConfig, find_tesseract, ocr_many

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "data" / "cache" / "ocr"


def _git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip()


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--data", type=Path, default=ROOT / "data" / "synthetic")
    parser.add_argument("--split", default="test", choices=("train", "val", "test"))
    parser.add_argument("--out", type=Path, default=ROOT / "reports")
    parser.add_argument("--cache", type=Path, default=CACHE_DIR)
    parser.add_argument("--workers", type=int, default=4, help="procesos para el OCR")
    parser.add_argument("--sin-ocr", action="store_true", help="solo la ruta de texto")
    parser.add_argument("--no-save", action="store_true", help="solo imprime el resumen")
    parser.add_argument("--errores", type=int, default=0, help="muestra N campos con error")
    args = parser.parse_args(argv)

    if not (args.data / args.split / "manifest.jsonl").exists():
        print(f"No hay dataset en {args.data}. Genéralo con `make synth`.", file=sys.stderr)
        return 1
    documents = load_manifest(args.data, args.split)

    ocr = None
    if not args.sin_ocr:
        find_tesseract()  # falla pronto y con instrucciones si no está instalado
        config = OcrConfig()
        cache = OcrCache(args.cache)
        imagen = [args.data / d.pdf for d in documents if d.image]
        ocr_many(imagen, cache, config, workers=args.workers)
        ocr = OcrRulesExtractor(config=config, cache=cache)

    def progress(i: int) -> None:
        if i % 100 == 0 or i == len(documents):
            print(f"  {i}/{len(documents)} documentos", end="\r", flush=True)

    evals = evaluate_documents(args.data, documents, ocr=ocr, progress=progress)
    print()
    summary = summarize(evals)
    ruta = "ruta de texto" if args.sin_ocr else "ruta de texto y extractor A (OCR + reglas)"
    markdown = to_markdown(summary, title=f"Resultados: {ruta}, split {args.split}")
    print(markdown)

    if args.errores:
        shown = 0
        for e in evals:
            for name, f in e.fields.items():
                if not f.match and shown < args.errores:
                    # Datos sintéticos: se pueden mostrar. eval_private.py nunca lo hace.
                    ident = f"{e.truth.persona_id} {e.truth.doc_type} {e.truth.modality} {name}"
                    print(f"  {ident}: {f.predicted!r} vs {f.truth!r}")
                    shown += 1

    if args.no_save:
        return 0
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "resultados.md").write_text(markdown, encoding="utf-8")
    rows = to_csv_rows(summary, split=args.split)
    with (args.out / "resultados.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["extractor"])
        writer.writeheader()
        writer.writerows(rows)

    dataset_json = args.data / "dataset.json"
    dataset = (
        DatasetInfo.model_validate_json(dataset_json.read_text(encoding="utf-8"))
        if dataset_json.exists()
        else None
    )
    now = datetime.now(UTC)
    run = {
        "fecha_utc": now.isoformat(timespec="seconds"),
        "commit": _git_commit(),
        "extractores": ["texto_reglas"] + ([] if args.sin_ocr else ["ocr_reglas"]),
        "ocr": None if args.sin_ocr else OcrConfig().key(),
        "split": args.split,
        "dataset": {
            "semilla": dataset.seed if dataset else None,
            "version_generador": dataset.generator_version if dataset else None,
        },
        "resumen": summary,
    }
    runs = args.out / "runs"
    runs.mkdir(exist_ok=True)
    run_path = runs / f"{now:%Y%m%dT%H%M%SZ}_{args.split}.json"
    run_path.write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Escrito: {args.out / 'resultados.md'}, resultados.csv y {run_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
