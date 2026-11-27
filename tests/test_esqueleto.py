"""Pruebas de eval/esqueleto.py: muestra la estructura sin filtrar datos personales."""

import shutil
import sys
from pathlib import Path

import pytest

from docextract.dataset import Modality, PersonTruth
from docextract.schemas import DocType

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "data" / "synthetic" / "samples"
sys.path.insert(0, str(ROOT / "eval"))
import esqueleto  # noqa: E402


def _digitales() -> list[tuple[Path, PersonTruth, str]]:
    """Las CURP y CSF digitales de las muestras, con el ground truth de su persona."""
    encontrados = []
    for gt in sorted(SAMPLES.glob("*/*/ground_truth.json")):
        truth = PersonTruth.model_validate_json(gt.read_text(encoding="utf-8"))
        for doc in truth.documents:
            if doc.modality is Modality.DIGITAL and doc.doc_type in (DocType.CURP, DocType.CSF):
                encontrados.append((SAMPLES / doc.pdf, truth, doc.doc_type.value))
    return encontrados


def test_mascara() -> None:
    assert esqueleto.mascara("Apellido:") == "Apellido:"
    assert esqueleto.mascara("Postal:63000") == "Postal:99999"
    assert esqueleto.mascara("CALLE") == "AAAAA"  # valor en mayúsculas, no la etiqueta "Calle"
    assert esqueleto.mascara("DE") == "AA"  # palabra corta que también va en los valores
    assert esqueleto.mascara("RFC:") == "RFC:"


@pytest.mark.parametrize(("pdf", "truth", "tipo"), _digitales())
def test_no_muestra_datos_personales(
    pdf: Path, truth: PersonTruth, tipo: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    carpeta = tmp_path / tipo
    carpeta.mkdir()
    shutil.copy(pdf, carpeta / f"{tipo.upper()}_{truth.form['apellido_paterno']}.pdf")
    assert esqueleto.main([str(carpeta)]) == 0
    salida = capsys.readouterr().out
    for campo, valor in truth.form.items():
        if valor and len(valor) > 3 and campo != "nacionalidad":
            assert valor not in salida, campo
    assert f"{tipo.upper()}_" not in salida  # nombre de archivo
    assert "Campos del parser" in salida
    if tipo == "csf":
        assert "codigo_postal: misma línea" in salida
        assert "Código@" in salida and "Postal:" in salida


def test_sin_pdfs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert esqueleto.main([str(tmp_path)]) == 1
    assert "No se encontraron PDFs" in capsys.readouterr().out
