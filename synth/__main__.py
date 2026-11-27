"""Línea de comandos del generador.

    uv run python -m synth                      # dataset completo en data/synthetic/
    uv run python -m synth --samples            # muestras versionadas en data/synthetic/samples/
    uv run python -m synth --train 20 --val 5 --test 5 --out /tmp/prueba

Requiere el catálogo de SEPOMEX (``make sepomex``).
"""

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

from docextract.validators.sepomex import SepomexCatalog
from synth.config import DEFAULT_CONFIG_PATH, load_config
from synth.generate import SPLITS, generate_dataset, samples_plan

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "data" / "synthetic"
SAMPLES_OUT = DEFAULT_OUT / "samples"


RUN_FILE = "generacion.json"
"""Configuración de la corrida en curso; ``--resume`` exige que coincida."""


def _check_resume(out: Path, config_json: str) -> None:
    run = out / RUN_FILE
    if not run.exists():
        raise SystemExit(f"No hay una generación que continuar en {out}.")
    guardada = json.loads(run.read_text(encoding="utf-8"))
    if guardada != json.loads(config_json):
        raise SystemExit(
            "La configuración no coincide con la de la generación interrumpida; "
            "usa la misma o empieza de nuevo con --force."
        )


def _prepare_output(out: Path, *, force: bool) -> None:
    """Solo borra lo que el generador escribió (splits, manifiestos y dataset.json)."""
    generated = [out / s for s in SPLITS] + [out / "dataset.json", out / RUN_FILE]
    existing = [p for p in generated if p.exists()]
    if existing and not force:
        raise SystemExit(f"Ya hay un dataset en {out}. Usa --force para regenerarlo.")
    for path in existing:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()


def _sepomex_sha256(catalog_path: Path) -> str | None:
    metadata = catalog_path.with_name("metadata.json")
    if metadata.exists():
        return json.loads(metadata.read_text(encoding="utf-8")).get("sha256")
    return None


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # acentos correctos en la consola de Windows
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="python -m synth", description=__doc__.split("\n")[0])
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--train", type=int)
    parser.add_argument("--val", type=int)
    parser.add_argument("--test", type=int)
    parser.add_argument(
        "--workers", type=int, default=0, help="procesos en paralelo (0 = la mitad de los núcleos)"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--force", action="store_true", help="reemplaza un dataset existente")
    group.add_argument("--resume", action="store_true", help="continúa una generación interrumpida")
    parser.add_argument("--samples", action="store_true", help="genera solo las muestras")
    args = parser.parse_args(argv)

    config = load_config(args.config, seed=args.seed)
    personas = {k: getattr(args, k) for k in SPLITS if getattr(args, k) is not None}
    if personas:
        config = config.model_copy(update={"personas": config.personas.model_copy(update=personas)})
    out = args.out or (SAMPLES_OUT if args.samples else DEFAULT_OUT)
    if args.resume:
        _check_resume(out, config.model_dump_json())
    else:
        _prepare_output(out, force=args.force or args.samples)
        if not args.samples:
            out.mkdir(parents=True, exist_ok=True)
            (out / RUN_FILE).write_text(config.model_dump_json(indent=2) + "\n", encoding="utf-8")

    catalog_path = SepomexCatalog.default_path()
    try:
        catalog = SepomexCatalog.load_default()
    except FileNotFoundError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    # La mitad de los núcleos: con todos al 100% durante minutos, el equipo de desarrollo se
    # reinició inesperadamente (2026-11-26). Se puede subir con --workers.
    workers = args.workers or max(1, (os.cpu_count() or 2) // 2)
    start = time.perf_counter()
    info = generate_dataset(
        config,
        catalog,
        out,
        plan=samples_plan() if args.samples else None,
        workers=1 if args.samples else workers,
        catalog_path=catalog_path,
        sepomex_sha256=_sepomex_sha256(catalog_path),
        resume=args.resume,
    )
    (out / RUN_FILE).unlink(missing_ok=True)  # terminada: ya no hay nada que reanudar
    elapsed = time.perf_counter() - start
    for split, counts in info.counts.items():
        print(f"{split:>5}: {counts['personas']:4d} personas, {counts['documentos']:5d} documentos")
    print(f"Listo en {elapsed:.0f} s: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
