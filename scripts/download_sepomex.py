"""Descarga el Catálogo Nacional de Códigos Postales de Correos de México (SEPOMEX).

Uso::

    uv run python scripts/download_sepomex.py                  # descarga automática
    uv run python scripts/download_sepomex.py --from-file X    # zip o txt bajado a mano

La página de descarga es un formulario ASP.NET: se lee una vez para obtener sus campos
ocultos (``__VIEWSTATE``, ``__EVENTVALIDATION``…) y se reenvía pidiendo el TXT de todos
los estados. Si Correos cambia la página y la descarga automática falla, baja el archivo a
mano (formato TXT, "Todos") y usa ``--from-file``.

El catálogo es "para uso particular" y no se permite su distribución: se guarda en
``data/sepomex/`` (ignorado por git), junto con ``metadata.json`` (fecha, origen, SHA-256 y
conteos) para saber qué versión se usó en cada evaluación.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import sys
import tempfile
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from docextract.validators.sepomex import DEFAULT_PATH, read_sepomex

URL = "https://www.correosdemexico.gob.mx/SSLServicios/ConsultaCP/CodigoPostal_Exportar.aspx"
USER_AGENT = "Mozilla/5.0 (compatible; docextract-sepomex/1.0)"
TIMEOUT_S = 300
_HIDDEN_FIELDS = (
    "__EVENTTARGET",
    "__EVENTARGUMENT",
    "__LASTFOCUS",
    "__VIEWSTATE",
    "__VIEWSTATEGENERATOR",
    "__EVENTVALIDATION",
)


def parse_hidden_fields(page: str) -> dict[str, str]:
    """Extrae los campos ocultos del formulario ASP.NET."""
    fields: dict[str, str] = {}
    for tag in re.findall(r"<input\b[^>]*>", page, flags=re.IGNORECASE):
        if not re.search(r'type="hidden"', tag, flags=re.IGNORECASE):
            continue
        name = re.search(r'name="([^"]+)"', tag)
        value = re.search(r'value="([^"]*)"', tag)
        if name:
            fields[name.group(1)] = html.unescape(value.group(1)) if value else ""
    return fields


def build_form(hidden: dict[str, str]) -> dict[str, str]:
    """Datos del POST: todos los estados ("00"), formato TXT y el botón de descarga."""
    if "__VIEWSTATE" not in hidden:
        raise RuntimeError("La página ya no tiene el formulario esperado (__VIEWSTATE).")
    form = {name: hidden.get(name, "") for name in _HIDDEN_FIELDS}
    form.update({"cboEdo": "00", "rblTipo": "txt", "btnDescarga.x": "10", "btnDescarga.y": "10"})
    return form


def download(destination: Path) -> None:
    headers = {"User-Agent": USER_AGENT}
    with urllib.request.urlopen(urllib.request.Request(URL, headers=headers), timeout=60) as r:
        page = r.read().decode(r.headers.get_content_charset() or "latin-1")
    body = urllib.parse.urlencode(build_form(parse_hidden_fields(page))).encode()
    request = urllib.request.Request(
        URL,
        data=body,
        headers={**headers, "Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        content_type = response.headers.get("Content-Type", "")
        if "html" in content_type:
            raise RuntimeError("Correos devolvió una página en lugar del archivo.")
        with destination.open("wb") as out:
            shutil.copyfileobj(response, out)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def install(source: Path, output: Path, *, origin: str) -> dict[str, object]:
    """Valida ``source`` como catálogo, lo copia a ``output`` y escribe metadata.json."""
    rows = read_sepomex(source)  # falla si no es un catálogo válido
    if not rows:
        raise ValueError("El catálogo está vacío.")
    output.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != output.resolve():
        shutil.copyfile(source, output)
    metadata: dict[str, object] = {
        "origen": origin,
        "fecha_descarga_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "archivo": output.name,
        "sha256": sha256(output),
        "asentamientos": len(rows),
        "codigos_postales": len({r.codigo_postal for r in rows}),
    }
    (output.parent / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return metadata


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--from-file", type=Path, help="zip o txt descargado a mano")
    parser.add_argument("--output", type=Path, default=DEFAULT_PATH, help="destino del zip")
    parser.add_argument("--force", action="store_true", help="vuelve a descargar aunque exista")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # acentos correctos en la consola de Windows
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    if args.from_file is None and args.output.exists() and not args.force:
        print(f"Ya existe {args.output}. Usa --force para volver a descargarlo.")
        return 0

    try:
        if args.from_file is not None:
            metadata = install(
                args.from_file, args.output, origin=f"archivo local ({args.from_file.name})"
            )
        else:
            with tempfile.TemporaryDirectory() as tmp:
                downloaded = Path(tmp) / "CPdescargatxt.zip"
                print("Descargando el catálogo de SEPOMEX (unos 2 MB)...")
                download(downloaded)
                metadata = install(downloaded, args.output, origin=URL)
    except (OSError, ValueError, RuntimeError) as error:  # red, archivo o formato
        print(f"Error: {error}", file=sys.stderr)
        if args.from_file is None:
            print(
                "Baja el archivo a mano (formato TXT, todos los estados) desde\n"
                f"  {URL}\n"
                "y corre: uv run python scripts/download_sepomex.py --from-file <archivo>",
                file=sys.stderr,
            )
        return 1

    print(
        f"Listo: {metadata['codigos_postales']:,} códigos postales y "
        f"{metadata['asentamientos']:,} asentamientos en {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
