"""OCR y extractor A. Las pruebas que llaman a Tesseract se omiten si no está instalado
(en CI sí lo está: ver .github/workflows/ci.yml y ``make tessdata``)."""

import json
from pathlib import Path

import numpy as np
import pytest

from docextract import ocr
from docextract.evaluation import field_matches
from docextract.extractors import Extractor
from docextract.extractors.ocr_rules import NAME, OcrRulesExtractor
from docextract.ocr import OcrCache, OcrConfig, OcrResult, OcrWord, TesseractNotFoundError
from docextract.parsers.address import default_catalog
from docextract.schemas import DocType

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "synthetic" / "samples"
ESCANEO = SAMPLES / "train" / "train-00002"  # muestra con los 4 documentos escaneados


def _tesseract_disponible() -> bool:
    try:
        ocr.find_tesseract()
        ocr.tessdata_dir(OcrConfig())
    except TesseractNotFoundError:
        return False
    return True


con_tesseract = pytest.mark.skipif(
    not _tesseract_disponible(), reason="Tesseract o sus modelos (make tessdata) no están"
)


# ---------------------------------------------------------------------------
# Sin Tesseract
# ---------------------------------------------------------------------------
def _foto_sintetica(angle: float) -> np.ndarray:
    """Hoja blanca con renglones oscuros, girada, sobre una mesa gris."""
    import cv2

    hoja = np.full((1100, 850), 250, np.uint8)
    for y in range(100, 1000, 40):
        hoja[y : y + 12, 80:770] = 30
    mesa = np.full((1600, 1200), 110, np.uint8)
    matrix = cv2.getRotationMatrix2D((425, 550), angle, 1.0)
    matrix[:, 2] += (175, 250)
    return cv2.warpAffine(hoja, matrix, (1200, 1600), dst=mesa, borderMode=cv2.BORDER_TRANSPARENT)


def test_encuentra_la_hoja_en_una_foto_y_no_en_un_escaneo() -> None:
    corners = ocr.find_document(_foto_sintetica(6.0))
    assert corners is not None
    # Las esquinas de una hoja de 850 x 1100 girada 6° alrededor de (600, 800).
    width = np.linalg.norm(corners[1] - corners[0])
    height = np.linalg.norm(corners[3] - corners[0])
    assert width == pytest.approx(850, rel=0.03)
    assert height == pytest.approx(1100, rel=0.03)
    escaneo = np.full((1100, 850), 250, np.uint8)
    escaneo[100:112, 80:770] = 30
    assert ocr.find_document(escaneo) is None


def test_endereza_renglones_inclinados() -> None:
    import cv2

    hoja = np.full((1100, 850), 250, np.uint8)
    for y in range(100, 1000, 40):
        hoja[y : y + 12, 80:770] = 30
    matrix = cv2.getRotationMatrix2D((425, 550), 4.0, 1.0)
    girada = cv2.warpAffine(hoja, matrix, (850, 1100), borderValue=250)
    assert ocr.skew_angle(girada) == pytest.approx(-4.0, abs=0.6)


def test_cache_no_repite_el_ocr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result = OcrResult(
        words=(OcrWord("Clave:", 10, 40, 10, 20, 95.0),), width=612, height=792,
        seconds=1.5, config="prueba",
    )  # fmt: skip
    llamadas = []

    def fake(pdf: bytes, config: OcrConfig) -> OcrResult:
        llamadas.append(pdf)
        return result

    monkeypatch.setattr(ocr, "ocr_pdf", fake)
    cache = OcrCache(tmp_path)
    assert cache.get(b"%PDF uno") == result
    assert cache.get(b"%PDF uno") == result
    assert len(llamadas) == 1
    guardado = next(tmp_path.rglob("*.json"))
    assert json.loads(guardado.read_text(encoding="utf-8"))["seconds"] == 1.5
    assert result.layout.ocr


def test_el_extractor_cumple_la_interfaz() -> None:
    assert isinstance(OcrRulesExtractor(), Extractor)


# ---------------------------------------------------------------------------
# Con Tesseract
# ---------------------------------------------------------------------------
@con_tesseract
@pytest.mark.parametrize("doc", ["curp", "ine", "comprobante"])
def test_extractor_a_sobre_escaneos(doc: str, tmp_path: Path) -> None:
    truth = json.loads((ESCANEO / "ground_truth.json").read_text(encoding="utf-8"))
    document = next(d for d in truth["documents"] if d["pdf"].endswith(f"/{doc}.pdf"))
    assert document["modality"] == "escaneo"
    doc_type = DocType(document["doc_type"])
    extractor = OcrRulesExtractor(cache=OcrCache(tmp_path))
    out = extractor.extract_pdf((ESCANEO / f"{doc}.pdf").read_bytes(), doc_type)
    assert out.classification.doc_type is doc_type
    assert out.result is not None and out.result.extractor == NAME
    assert out.result.latency_ms > 0
    # Sin el catálogo de SEPOMEX (en CI no se puede redistribuir), el comprobante lee colonia,
    # ciudad y estado con reglas más débiles: esos campos solo se exigen con catálogo.
    sin_catalogo = set()
    if doc_type is DocType.COMPROBANTE_DOMICILIO and default_catalog() is None:
        sin_catalogo = {"colonia", "ciudad", "estado"}
    correctos = [
        field_matches(name, out.result.fields[name].value, value)
        for name, value in document["fields"].items()
        if name in out.result.fields and name not in sin_catalogo
    ]
    # Línea base: la mayoría de los campos de un escaneo limpio.
    assert sum(correctos) / len(correctos) >= 0.7, correctos


@con_tesseract
def test_extract_con_imagenes() -> None:
    from PIL import Image

    image = Image.open(ESCANEO / "curp.jpg")
    result = OcrRulesExtractor().extract([image], DocType.CURP)
    assert result.extractor == NAME
    assert result.fields["curp"].value
