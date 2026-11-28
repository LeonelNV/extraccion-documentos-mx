"""Actualiza ``src/docextract/llm/precios_bedrock.json`` desde la AWS Price List API.

    uv run python scripts/precios_bedrock.py          # muestra los precios y las diferencias
    uv run python scripts/precios_bedrock.py --write  # además reescribe el JSON

Usa las credenciales de AWS del entorno (la Price List API no cobra). Toma el precio bajo
demanda del nivel estándar en us-east-1, sin lotes, caché, Flex ni Priority.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRECIOS = ROOT / "src" / "docextract" / "llm" / "precios_bedrock.json"

# Nombre del modelo en la Price List API (atributo "model").
NOMBRES_PRICING = {
    "amazon.nova-micro-v1:0": "Nova Micro",
    "amazon.nova-lite-v1:0": "Nova Lite",
    "amazon.nova-pro-v1:0": "Nova Pro",
    "qwen.qwen3-vl-235b-a22b": "Qwen3 VL 235B A22B",
}
USAGE_RE = re.compile(r"^USE1-[A-Za-z0-9.-]+-(input|output)-tokens$")


def precio(client, nombre: str) -> dict[str, float]:
    response = client.get_products(
        ServiceCode="AmazonBedrock",
        Filters=[
            {"Type": "TERM_MATCH", "Field": "regionCode", "Value": "us-east-1"},
            {"Type": "TERM_MATCH", "Field": "model", "Value": nombre},
        ],
        MaxResults=100,
    )
    out: dict[str, float] = {}
    for item in response["PriceList"]:
        product = json.loads(item)
        usage = product["product"]["attributes"].get("usagetype", "")
        match = USAGE_RE.match(usage)
        if not match or "custom-model" in usage or "mantle" in usage:
            continue
        for term in product["terms"].get("OnDemand", {}).values():
            for dimension in term["priceDimensions"].values():
                if dimension["unit"] == "1K tokens":
                    key = "entrada_1k" if match.group(1) == "input" else "salida_1k"
                    out[key] = float(dimension["pricePerUnit"]["USD"])
    if set(out) != {"entrada_1k", "salida_1k"}:
        raise SystemExit(f"No se encontró el precio de entrada y salida de {nombre}: {out}")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)

    import boto3

    client = boto3.client("pricing", region_name="us-east-1")
    actual = json.loads(PRECIOS.read_text(encoding="utf-8"))
    nuevo = {**actual, "fecha": date.today().isoformat(), "modelos": {}}
    for model_id, nombre in NOMBRES_PRICING.items():
        previo = actual["modelos"].get(model_id, {})
        datos = {**previo, **precio(client, nombre)}
        nuevo["modelos"][model_id] = datos
        cambio = "" if datos == previo else "  (cambió)"
        print(f"{model_id}: entrada {datos['entrada_1k']}, salida {datos['salida_1k']}{cambio}")
    if args.write:
        lines = [
            f"    {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}"
            for k, v in nuevo["modelos"].items()
        ]
        cabecera = {k: v for k, v in nuevo.items() if k != "modelos"}
        texto = json.dumps(cabecera, ensure_ascii=False, indent=2)[:-2]
        texto += ',\n  "modelos": {\n' + ",\n".join(lines) + "\n  }\n}\n"
        PRECIOS.write_text(texto, encoding="utf-8")
        print(f"Escrito {PRECIOS.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
