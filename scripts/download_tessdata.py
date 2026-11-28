"""Descarga los modelos de Tesseract (español, inglés y orientación) a ``models/tessdata/``.

Uso::

    uv run python scripts/download_tessdata.py                 # variante best (por defecto)
    uv run python scripts/download_tessdata.py --variante fast

El instalador de Tesseract para Windows trae solo inglés si se instala en silencio, y agregar
idiomas en ``C:\\Program Files`` pide permisos de administrador. Este script los baja a una
carpeta del proyecto (ignorada por git) que el extractor usa con ``--tessdata-dir``. La CI
corre el mismo script, así que la PC y la CI leen con exactamente los mismos modelos.

Cada archivo sale de un commit fijo de los repositorios oficiales y se comprueba contra su
SHA-256 antes de guardarlo; si no coincide, no se guarda. ``metadata.json`` registra el
origen para saber con qué modelos se midió cada evaluación.

* ``best``: modelos LSTM de mayor exactitud (tessdata_best). Más lentos.
* ``fast``: versiones reducidas (tessdata_fast). Más rápidos y algo menos exactos.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / "models" / "tessdata"
USER_AGENT = "docextract-tessdata/1.0"
TIMEOUT_S = 300
WINDOWS_EXE = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")


@dataclass(frozen=True)
class Variante:
    repo: str
    commit: str
    sha256: dict[str, str]

    def url(self, archivo: str) -> str:
        return (
            f"https://raw.githubusercontent.com/tesseract-ocr/{self.repo}/{self.commit}/{archivo}"
        )


# El modelo de orientación (osd) es el mismo archivo en ambos repositorios.
_OSD = "9cf5d576fcc47564f11265841e5ca839001e7e6f38ff7f7aacf46d15a96b00ff"
VARIANTES = {
    "best": Variante(
        repo="tessdata_best",
        commit="e12c65a915945e4c28e237a9b52bc4a8f39a0cec",  # 2024-03-09
        sha256={
            "spa.traineddata": "e2c1ffdad8b30f26c45d4017a9183d3a7f9aa69e59918be4f88b126fac99ab2c",
            "eng.traineddata": "8280aed0782fe27257a68ea10fe7ef324ca0f8d85bd2fd145d1c2b560bcb66ba",
            "osd.traineddata": _OSD,
        },
    ),
    "fast": Variante(
        repo="tessdata_fast",
        commit="87416418657359cb625c412a48b6e1d6d41c29bd",  # 2024-08-01
        sha256={
            "spa.traineddata": "6f2e04d02774a18f01bed44b1111f2cd7f3ba7ac9dc4373cd3f898a40ea6b464",
            "eng.traineddata": "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2",
            "osd.traineddata": _OSD,
        },
    ),
}


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(url: str, destino: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response, destino.open("wb") as f:
        shutil.copyfileobj(response, f)


def descargar(variante: Variante, carpeta: Path, *, fetch=fetch) -> list[str]:
    """Baja los archivos que falten o no coincidan. Devuelve los nombres descargados.

    Cada archivo se baja a un temporal y solo se mueve a ``carpeta`` si su SHA-256 coincide.
    """
    carpeta.mkdir(parents=True, exist_ok=True)
    bajados = []
    for archivo, esperado in variante.sha256.items():
        destino = carpeta / archivo
        if destino.exists() and sha256_of(destino) == esperado:
            continue
        with tempfile.TemporaryDirectory(dir=carpeta) as tmp:
            parcial = Path(tmp) / archivo
            fetch(variante.url(archivo), parcial)
            obtenido = sha256_of(parcial)
            if obtenido != esperado:
                raise RuntimeError(
                    f"{archivo}: SHA-256 {obtenido[:12]}… no coincide con {esperado[:12]}…"
                )
            parcial.replace(destino)
        bajados.append(archivo)
    return bajados


def tesseract_exe() -> str | None:
    encontrado = shutil.which("tesseract")
    if encontrado:
        return encontrado
    return str(WINDOWS_EXE) if WINDOWS_EXE.exists() else None


def idiomas_disponibles(exe: str, carpeta: Path) -> list[str]:
    salida = subprocess.run(
        [exe, "--tessdata-dir", str(carpeta), "--list-langs"],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    # La primera línea es "List of available languages in ...".
    return sorted(line.strip() for line in salida.stdout.splitlines()[1:] if line.strip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--variante", choices=sorted(VARIANTES), default="best")
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    args = parser.parse_args(argv)

    variante = VARIANTES[args.variante]
    carpeta = args.dir / args.variante
    bajados = descargar(variante, carpeta)
    print(f"Modelos {args.variante} en {carpeta}: ", end="")
    print(f"descargados {', '.join(bajados)}" if bajados else "ya estaban (SHA-256 correcto)")
    (carpeta / "metadata.json").write_text(
        json.dumps(
            {
                "repo": f"tesseract-ocr/{variante.repo}",
                "commit": variante.commit,
                "sha256": variante.sha256,
                "verificado": datetime.now(UTC).isoformat(timespec="seconds"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    exe = tesseract_exe()
    if exe is None:
        print("Aviso: no encontré tesseract. En Windows: winget install UB-Mannheim.TesseractOCR")
        return 0
    version = subprocess.run([exe, "--version"], capture_output=True, text=True, check=True)
    print(f"{version.stdout.splitlines()[0]} ({exe})")
    idiomas = idiomas_disponibles(exe, carpeta)
    print(f"Idiomas: {', '.join(idiomas)}")
    if "spa" not in idiomas:
        print("Error: tesseract no reconoce el modelo de español.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
