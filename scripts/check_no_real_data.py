"""Bloquea documentos reales: PDFs e imágenes fuera de las carpetas permitidas.

Uso:
    python scripts/check_no_real_data.py ARCHIVO...   # pre-commit: archivos del commit
    python scripts/check_no_real_data.py --history    # CI: todo el historial de git

Reglas:
1. Nada puede versionarse bajo ``data/real/``, sea cual sea el tipo de archivo.
2. PDFs e imágenes solo se permiten en ``data/synthetic/`` y ``docs/img/``. Se
   detectan por extensión **y** por contenido (magic bytes), así que cambiarle
   la extensión a un archivo no lo oculta.

Solo usa la biblioteca estándar, para correr en CI sin instalar dependencias.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

ALLOWED_DIRS = ("data/synthetic/", "docs/img/")
BLOCKED_DIR = "data/real/"
BLOCKED_EXTENSIONS = frozenset(
    {
        ".pdf",
        ".png",
        ".jpg",
        ".jpeg",
        ".jpe",
        ".jfif",
        ".tif",
        ".tiff",
        ".gif",
        ".bmp",
        ".webp",
        ".heic",
        ".heif",
        ".avif",
        ".jp2",
        ".j2k",
    }
)
# La especificación de PDF permite que el encabezado aparezca en el primer KiB.
HEAD_BYTES = 1024
_HEIF_BRANDS = frozenset(
    {b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevx", b"mif1", b"msf1", b"avif", b"avis"}
)
_GITLINK_MODE = b"160000"  # submódulos: el "blob" es un commit de otro repo


@dataclass(frozen=True)
class Violation:
    path: str
    reason: str


def detect_content(head: bytes) -> str | None:
    """Devuelve el formato si los primeros bytes son de un PDF o una imagen."""
    pdf_at = head.find(b"%PDF-", 0, HEAD_BYTES)
    # Solo cuenta al inicio de una línea, para no confundir texto que lo menciona.
    if pdf_at == 0 or (pdf_at > 0 and head[pdf_at - 1 : pdf_at] in (b"\n", b"\r")):
        return "PDF"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if head.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "GIF"
    if head.startswith((b"II*\x00", b"MM\x00*")):
        return "TIFF"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "WEBP"
    if head[4:8] == b"ftyp" and head[8:12] in _HEIF_BRANDS:
        return "HEIF/AVIF"
    if head.startswith((b"\x00\x00\x00\x0cjP  \r\n\x87\n", b"\xff\x4f\xff\x51")):
        return "JPEG 2000"
    if head.startswith(b"BM") and head[6:10] == b"\x00\x00\x00\x00":
        return "BMP"
    return None


def normalize(path: str) -> str:
    return PurePosixPath(path.replace("\\", "/")).as_posix()


def check(path: str, head: bytes | None) -> Violation | None:
    """Aplica las reglas a una ruta relativa a la raíz del repo y su contenido inicial."""
    path = normalize(path)
    # data/real/ se compara sin distinguir mayúsculas: en Windows "Data/Real" es la misma carpeta.
    if path.lower().startswith(BLOCKED_DIR):
        return Violation(path, "está dentro de data/real/, que nunca se versiona")
    # Las carpetas permitidas sí distinguen mayúsculas: solo cuentan las rutas canónicas.
    if path.startswith(ALLOWED_DIRS):
        return None
    suffix = PurePosixPath(path).suffix.lower()
    if suffix in BLOCKED_EXTENSIONS:
        return Violation(path, f"archivo {suffix} fuera de data/synthetic/ y docs/img/")
    if head is not None and (kind := detect_content(head)):
        return Violation(path, f"el contenido es {kind} aunque la extensión no lo indique")
    return None


def _read_head(path: Path) -> bytes | None:
    try:
        with path.open("rb") as f:
            return f.read(HEAD_BYTES)
    except OSError:
        # Archivo borrado o ilegible: igual se aplican las reglas de ruta.
        return None


def check_files(paths: Iterable[str]) -> list[Violation]:
    violations = []
    for raw in paths:
        if v := check(raw, _read_head(Path(raw))):
            violations.append(v)
    return violations


def _git(repo: Path, *args: str, stdin: bytes | None = None) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo), *args], input=stdin, capture_output=True, check=True
    ).stdout


def iter_history_blobs(repo: Path) -> Iterator[tuple[str, str]]:
    """Recorre cada archivo agregado o modificado en cualquier commit de cualquier rama.

    Devuelve pares ``(sha_del_blob, ruta)`` sin repetir. ``-m`` incluye los cambios
    introducidos en commits de merge y ``-z`` evita que git escape rutas con acentos.
    """
    out = _git(
        repo,
        "log",
        "--all",
        "-m",
        "--raw",
        "-z",
        "--no-renames",
        "--no-abbrev",
        "--diff-filter=AM",
        "--format=",
    )
    tokens = out.split(b"\0")
    seen: set[tuple[str, str]] = set()
    i = 0
    while i < len(tokens):
        meta = tokens[i].strip()
        if not meta.startswith(b":") or i + 1 >= len(tokens):
            i += 1
            continue
        # Formato: ":<modo_ant> <modo_nuevo> <sha_ant> <sha_nuevo> <estado>" y luego la ruta.
        fields = meta[1:].split()
        path = tokens[i + 1].decode("utf-8", errors="replace")
        i += 2
        if len(fields) < 4 or fields[1] == _GITLINK_MODE:
            continue
        key = (fields[3].decode("ascii"), path)
        if key not in seen:
            seen.add(key)
            yield key


def read_blob_heads(repo: Path, shas: Iterable[str]) -> dict[str, bytes]:
    """Lee los primeros bytes de cada blob con una sola llamada a ``git cat-file``."""
    unique = list(dict.fromkeys(shas))
    if not unique:
        return {}
    data = _git(repo, "cat-file", "--batch", stdin="\n".join(unique).encode() + b"\n")
    heads: dict[str, bytes] = {}
    pos = 0
    for sha in unique:
        end_of_header = data.index(b"\n", pos)
        header = data[pos:end_of_header].split()
        pos = end_of_header + 1
        if len(header) < 3:  # "<sha> missing"
            continue
        size = int(header[2])
        heads[sha] = data[pos : pos + min(size, HEAD_BYTES)]
        pos += size + 1  # el contenido va seguido de un salto de línea
    return heads


def check_history(repo: Path) -> list[Violation]:
    blobs = list(iter_history_blobs(repo))
    # Solo hace falta leer el contenido de lo que está fuera de las carpetas permitidas.
    to_read = [sha for sha, path in blobs if not normalize(path).startswith(ALLOWED_DIRS)]
    heads = read_blob_heads(repo, to_read)
    violations = []
    for sha, path in blobs:
        if v := check(path, heads.get(sha)):
            violations.append(v)
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="*", help="archivos a revisar (los pasa pre-commit)")
    parser.add_argument(
        "--history", action="store_true", help="revisar todo el historial de git del repo actual"
    )
    args = parser.parse_args(argv)
    if args.history and args.files:
        parser.error("usa --history o una lista de archivos, no ambos")

    if args.history:
        violations = check_history(Path.cwd())
        title = "Hay posibles documentos reales en el historial de git:"
        hint = "Hay que quitarlos del historial (git filter-repo) antes de hacer merge."
    else:
        violations = check_files(args.files)
        title = "Commit bloqueado: posibles documentos reales."
        hint = (
            "Los documentos reales van en data/real/ (ignorada por git) y nunca se versionan.\n"
            "Si es una muestra sintética, muévela a data/synthetic/; "
            "si es una figura de la documentación, a docs/img/."
        )

    if not violations:
        return 0
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(errors="replace")
    print(title, file=sys.stderr)
    for v in sorted(set(violations), key=lambda v: v.path):
        print(f"  - {v.path}: {v.reason}", file=sys.stderr)
    print(hint, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
