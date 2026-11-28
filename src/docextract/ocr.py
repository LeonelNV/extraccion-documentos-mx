"""OCR con Tesseract: de un PDF de imagen a un ``TextLayout``, la entrada de los parsers.

Pasos:

1. **Rasterizar** cada página con pypdfium2 a un ancho fijo (``OcrConfig.width``).
2. **Preprocesar** con OpenCV:
   - si se encuentra el contorno del documento (una foto sobre una mesa), se corrige la
     perspectiva y se recorta;
   - se aplana la iluminación dividiendo entre el fondo estimado (quita sombras y degradados).
3. **Tesseract** en español, con salida TSV: cada palabra con su caja y su confianza.
4. Las palabras se pasan a coordenadas de una página carta (612 pt de ancho) y se arma el
   ``TextLayout``. Cada palabra toma la altura de su línea según Tesseract, para que el
   agrupamiento por líneas de ``TextLayout`` respete las líneas que encontró el OCR.

El binario de Tesseract es del sistema (winget o apt) y los modelos, los de ``make
tessdata`` (``models/tessdata/<variante>``), fijados por SHA-256.

Privacidad: el texto reconocido no se registra en logs. La caché (``OcrCache``) es opcional
y solo la usa la evaluación con datos sintéticos; ``eval_private.py`` y la API no la usan.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from docextract.layout import TextLayout, Word

__all__ = [
    "OcrCache",
    "OcrConfig",
    "OcrResult",
    "OcrWord",
    "TesseractNotFoundError",
    "find_tesseract",
    "ocr_images",
    "ocr_many",
    "ocr_pages",
    "ocr_pdf",
    "preprocess",
]

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TESSDATA = ROOT / "models" / "tessdata"
WINDOWS_EXE = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
PAGE_WIDTH_PT = 612.0
PREPROCESS_VERSION = "2"
"""Cambia cuando cambia el preprocesamiento: invalida la caché."""


class TesseractNotFoundError(RuntimeError):
    """No se encontró el binario de Tesseract o los modelos de ``make tessdata``."""


@dataclass(frozen=True)
class OcrConfig:
    lang: str = "spa"
    psm: int = 3
    """Segmentación automática de página (3). Ver ``tesseract --help-psm``."""
    variant: str = "best"
    width: int = 2400
    """Ancho en píxeles al rasterizar (≈280 ppp en una hoja carta)."""
    max_pages: int = 3

    def key(self) -> str:
        return f"{self.lang}-psm{self.psm}-{self.variant}-w{self.width}-p{PREPROCESS_VERSION}"


@dataclass(frozen=True)
class OcrWord:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float
    confidence: float
    """Confianza de Tesseract, 0 a 100."""


@dataclass(frozen=True)
class OcrResult:
    words: tuple[OcrWord, ...]
    width: float
    height: float
    seconds: float
    config: str
    warped: tuple[bool, ...] = field(default=())
    """Por página: si se corrigió la perspectiva."""

    @property
    def layout(self) -> TextLayout:
        words = [Word(w.text, w.x0, w.x1, w.top, w.bottom) for w in self.words]
        return TextLayout(words, width=self.width, height=self.height, ocr=True)

    @property
    def mean_confidence(self) -> float:
        """Confianza media de las palabras con texto, de 0 a 1."""
        values = [w.confidence for w in self.words if w.confidence >= 0]
        return float(np.mean(values)) / 100 if values else 0.0

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> OcrResult:
        data = json.loads(text)
        data["words"] = tuple(OcrWord(**w) for w in data["words"])
        data["warped"] = tuple(data.get("warped", ()))
        return cls(**data)


# ---------------------------------------------------------------------------
# Tesseract
# ---------------------------------------------------------------------------
def find_tesseract() -> str:
    exe = os.environ.get("DOCEXTRACT_TESSERACT") or shutil.which("tesseract")
    if not exe and WINDOWS_EXE.exists():
        exe = str(WINDOWS_EXE)
    if not exe:
        raise TesseractNotFoundError(
            "No se encontró tesseract. Windows: winget install UB-Mannheim.TesseractOCR; "
            "Ubuntu: apt install tesseract-ocr."
        )
    return exe


def tessdata_dir(config: OcrConfig) -> Path:
    base = Path(os.environ.get("DOCEXTRACT_TESSDATA", DEFAULT_TESSDATA))
    folder = base / config.variant
    if not (folder / f"{config.lang}.traineddata").exists():
        raise TesseractNotFoundError(f"Faltan los modelos de Tesseract en {folder}: make tessdata")
    return folder


def _tesseract_tsv(image: np.ndarray, config: OcrConfig) -> list[dict[str, str]]:
    import cv2

    ok, png = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError("No se pudo codificar la imagen para el OCR.")
    command = [
        find_tesseract(), "stdin", "stdout",
        "--tessdata-dir", str(tessdata_dir(config)),
        "-l", config.lang, "--psm", str(config.psm),
        # Sin el archivo de configuración "tsv": vive en el tessdata del sistema, no en el
        # de make tessdata. Se pide la salida TSV con variables.
        "-c", "tessedit_create_txt=0", "-c", "tessedit_create_tsv=1",
    ]  # fmt: skip
    completed = subprocess.run(command, input=png.tobytes(), capture_output=True, check=False)
    if completed.returncode != 0:
        # stderr de Tesseract no trae texto del documento, pero se recorta por si acaso.
        raise RuntimeError(f"Tesseract terminó con código {completed.returncode}.")
    text = completed.stdout.decode("utf-8", errors="replace")
    return list(csv.DictReader(io.StringIO(text), delimiter="\t", quoting=csv.QUOTE_NONE))


def _words_from_tsv(rows: list[dict[str, str]], scale: float, offset: float) -> list[OcrWord]:
    """Palabras (nivel 5) con la altura de su línea, en puntos de página carta."""
    lines: dict[tuple[str, str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if row.get("level") == "5" and (row.get("text") or "").strip():
            key = (row["page_num"], row["block_num"], row["par_num"], row["line_num"])
            lines[key].append(row)
    words = []
    for line in lines.values():
        top = min(int(r["top"]) for r in line)
        bottom = max(int(r["top"]) + int(r["height"]) for r in line)
        for r in line:
            left, width = int(r["left"]), int(r["width"])
            words.append(
                OcrWord(
                    text=r["text"].strip(),
                    x0=left * scale,
                    x1=(left + width) * scale,
                    top=top * scale + offset,
                    bottom=bottom * scale + offset,
                    confidence=float(r["conf"]),
                )
            )
    return words


# ---------------------------------------------------------------------------
# Imagen
# ---------------------------------------------------------------------------
def render_pages(pdf: bytes, config: OcrConfig) -> list[np.ndarray]:
    """Páginas del PDF en escala de grises, ``config.width`` píxeles de ancho."""
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(pdf)
    try:
        pages = []
        for index in range(min(len(document), config.max_pages)):
            page = document[index]
            scale = config.width / page.get_width()
            bitmap = page.render(scale=scale, grayscale=True)
            pages.append(np.array(bitmap.to_pil().convert("L")))
        return pages
    finally:
        document.close()


def _order_corners(points: np.ndarray) -> np.ndarray:
    """Esquinas en orden: arriba-izquierda, arriba-derecha, abajo-derecha, abajo-izquierda."""
    s = points.sum(axis=1)
    d = np.diff(points, axis=1).ravel()
    return np.array(
        [points[np.argmin(s)], points[np.argmin(d)], points[np.argmax(s)], points[np.argmax(d)]],
        dtype=np.float32,
    )


def find_document(gray: np.ndarray) -> np.ndarray | None:
    """Las 4 esquinas del documento en una foto, o ``None``.

    1. Si el borde de la imagen es claro como el papel, es un escaneo: no se recorta.
    2. Bordes con Canny y el contorno de 4 lados más grande. Los bordes del papel son
       nítidos; los de una sombra o un degradado de luz, difusos, y Canny no los marca.
       Separar papel y mesa por brillo falla con mesas claras y con sombras que parten la
       hoja (medido en val).
    """
    import cv2

    small_w = 600
    ratio = gray.shape[1] / small_w
    small = cv2.resize(gray, (small_w, round(gray.shape[0] / ratio)), interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (5, 5), 0)
    _, mask = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    border = np.concatenate([mask[0], mask[-1], mask[:, 0], mask[:, -1]])
    if np.mean(border > 0) > 0.3:
        return None

    total = small.shape[0] * small.shape[1]
    # Segundo intento más sensible, para una hoja sobre una mesa casi igual de clara.
    for low, high in ((20, 60), (8, 24)):
        edges = cv2.dilate(cv2.Canny(small, low, high), np.ones((3, 3), np.uint8))
        contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:10]:
            if not 0.25 <= cv2.contourArea(contour) / total <= 0.97:
                continue
            approx = cv2.approxPolyDP(contour, 0.02 * cv2.arcLength(contour, True), True)
            if len(approx) == 4 and cv2.isContourConvex(approx):
                return _order_corners(approx.reshape(4, 2).astype(np.float32) * ratio)
    return None


def skew_angle(gray: np.ndarray, *, max_angle: float = 12.0, step: float = 0.5) -> float:
    """Ángulo (grados) que endereza los renglones: el que maximiza la varianza del perfil
    horizontal del texto. Para fotos en las que no se encontró el contorno."""
    import cv2

    small_w = 800
    small = cv2.resize(gray, (small_w, round(gray.shape[0] * small_w / gray.shape[1])))
    text = cv2.adaptiveThreshold(
        small, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 25, 15
    )
    center = (small.shape[1] / 2, small.shape[0] / 2)
    best, best_score = 0.0, -1.0
    for angle in np.arange(-max_angle, max_angle + step, step):
        matrix = cv2.getRotationMatrix2D(center, float(angle), 1.0)
        rotated = cv2.warpAffine(text, matrix, (small.shape[1], small.shape[0]))
        score = float(np.var(rotated.sum(axis=1)))
        if score > best_score:
            best, best_score = float(angle), score
    return best


def _rotate(gray: np.ndarray, angle: float) -> np.ndarray:
    import cv2

    center = (gray.shape[1] / 2, gray.shape[0] / 2)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    return cv2.warpAffine(
        gray, matrix, (gray.shape[1], gray.shape[0]),
        flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE,
    )  # fmt: skip


def _warp(gray: np.ndarray, corners: np.ndarray, width: int) -> np.ndarray:
    import cv2

    tl, tr, br, bl = corners
    w = max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl))
    h = max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr))
    out_w, out_h = width, round(width * h / w)
    target = np.array([[0, 0], [out_w - 1, 0], [out_w - 1, out_h - 1], [0, out_h - 1]], np.float32)
    matrix = cv2.getPerspectiveTransform(corners, target)
    return cv2.warpPerspective(
        gray, matrix, (out_w, out_h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )


def _flatten_illumination(gray: np.ndarray) -> np.ndarray:
    """Divide entre el fondo (el papel sin texto) para quitar sombras y degradados."""
    import cv2

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (41, 41))
    background = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel)
    background = cv2.GaussianBlur(background, (0, 0), 15)
    flat = cv2.divide(gray, background, scale=255)
    return cv2.normalize(flat, None, 0, 255, cv2.NORM_MINMAX)


def preprocess(gray: np.ndarray, width: int) -> tuple[np.ndarray, bool]:
    """Imagen lista para Tesseract y si se corrigió la perspectiva.

    No se binariza: Tesseract lo hace por su cuenta, y un umbral propio (Otsu sobre los
    píxeles oscuros) borraba las etiquetas grises de la INE (exactitud de campos en val:
    90% → 22% en escaneos).
    """
    corners = find_document(gray)
    warped = corners is not None
    if warped:
        gray = _warp(gray, corners, width)
    else:
        angle = skew_angle(gray)
        if abs(angle) >= 0.5:
            gray = _rotate(gray, angle)
    return _flatten_illumination(gray), warped


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------
def ocr_pdf(pdf: bytes, config: OcrConfig | None = None) -> OcrResult:
    """OCR de las primeras páginas del PDF, apiladas verticalmente como en ``from_pdf``."""
    config = config or OcrConfig()
    start = time.perf_counter()
    return ocr_pages(render_pages(pdf, config), config, start=start)


def ocr_images(images: list, config: OcrConfig | None = None) -> OcrResult:
    """OCR de imágenes de Pillow (una por página)."""
    import cv2

    config = config or OcrConfig()
    start = time.perf_counter()
    pages = []
    for image in images[: config.max_pages]:
        gray = np.array(image.convert("L"))
        height = round(gray.shape[0] * config.width / gray.shape[1])
        pages.append(cv2.resize(gray, (config.width, height), interpolation=cv2.INTER_CUBIC))
    return ocr_pages(pages, config, start=start)


def ocr_pages(
    pages: list[np.ndarray], config: OcrConfig, *, start: float | None = None
) -> OcrResult:
    start = time.perf_counter() if start is None else start
    words: list[OcrWord] = []
    offset, warped = 0.0, []
    for page in pages:
        image, was_warped = preprocess(page, config.width)
        warped.append(was_warped)
        scale = PAGE_WIDTH_PT / image.shape[1]
        words += _words_from_tsv(_tesseract_tsv(image, config), scale, offset)
        offset += image.shape[0] * scale
    return OcrResult(
        words=tuple(words),
        width=PAGE_WIDTH_PT,
        height=offset,
        seconds=time.perf_counter() - start,
        config=config.key(),
        warped=tuple(warped),
    )


class OcrCache:
    """Caché en disco por hash del PDF y configuración. Solo para datos sintéticos."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def _path(self, pdf: bytes, config: OcrConfig) -> Path:
        digest = hashlib.sha256(pdf).hexdigest()
        return self.folder / config.key() / digest[:2] / f"{digest}.json"

    def get(self, pdf: bytes, config: OcrConfig | None = None) -> OcrResult:
        config = config or OcrConfig()
        path = self._path(pdf, config)
        if path.exists():
            return OcrResult.from_json(path.read_text(encoding="utf-8"))
        result = ocr_pdf(pdf, config)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(result.to_json(), encoding="utf-8")
        tmp.replace(path)
        return result


def _ocr_uno(args: tuple[str, str, OcrConfig]) -> None:
    pdf, folder, config = args
    OcrCache(Path(folder)).get(Path(pdf).read_bytes(), config)


def ocr_many(
    pdfs: list[Path], cache: OcrCache, config: OcrConfig | None = None, *, workers: int = 4
) -> None:
    """Llena la caché con el OCR de muchos PDFs en paralelo (Tesseract usa un núcleo por
    proceso). Solo para datos sintéticos."""
    from concurrent.futures import ProcessPoolExecutor

    config = config or OcrConfig()
    jobs = [(str(p), str(cache.folder), config) for p in pdfs]
    with ProcessPoolExecutor(workers) as pool:
        for i, _ in enumerate(pool.map(_ocr_uno, jobs, chunksize=4), 1):
            if i % 25 == 0 or i == len(jobs):
                print(f"  OCR {i}/{len(jobs)}", end="\r", flush=True)
    if jobs:
        print()
