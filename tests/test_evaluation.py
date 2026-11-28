"""Pruebas de la evaluación (make eval) y de eval_private.py.

Corren sobre las muestras sintéticas versionadas, así que no dependen de ``make synth``.
"""

import json
import shutil
import sys
from pathlib import Path

import pytest

from docextract.dataset import PersonTruth
from docextract.evaluation import (
    cer,
    evaluate_documents,
    field_matches,
    load_manifest,
    normalize_value,
    summarize,
    to_csv_rows,
    to_markdown,
)
from docextract.validators.sepomex import SepomexCatalog

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "data" / "synthetic" / "samples"
sys.path.insert(0, str(ROOT / "eval"))
import eval_private  # noqa: E402
import evaluate  # noqa: E402


# ---------------------------------------------------------------------------
# Comparación
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("campo", "a", "b"),
    [
        ("nombre", "María José", "MARIA JOSE"),
        ("apellido_materno", "Núñez", "NUÑEZ"),
        ("fecha_nacimiento", "17/05/1990", "1990-05-17"),
        ("fecha_emision", "05 OCT 2026", "5 de octubre de 2026"),
        ("codigo_postal", "C.P. 1901", "01901"),
        ("estado", "NAY.", "Nayarit"),
        ("entidad_nacimiento", "CIUDAD DE MEXICO", "Distrito Federal"),
        ("sexo", "HOMBRE", "H"),
        ("calle", "AV. JUAREZ", "Avenida Juárez"),
        ("curp", "abcd 123", "ABCD123"),
        ("apellido_materno", "", ""),
    ],
)
def test_comparacion_tras_normalizar(campo: str, a: str, b: str) -> None:
    assert field_matches(campo, a, b)


def test_no_encontrado_nunca_coincide() -> None:
    assert not field_matches("apellido_materno", None, "")
    assert normalize_value("nombre", None) is None


def test_cer() -> None:
    assert cer("nombre", "GONZALES", "GONZALEZ") == pytest.approx(1 / 8)
    assert cer("nombre", None, "ANA") == 1.0
    assert cer("apellido_materno", "", "") == 0.0
    assert cer("apellido_materno", "LOPEZ", "") == 1.0


# ---------------------------------------------------------------------------
# Evaluación sobre las muestras
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def resumen() -> dict:
    documentos = load_manifest(SAMPLES, "train") + load_manifest(SAMPLES, "test")
    return summarize(evaluate_documents(SAMPLES, documentos))


def test_resumen_de_las_muestras(resumen: dict) -> None:
    # Sin OCR: solo se extraen los digitales (los de imagen requieren Tesseract).
    assert resumen["documentos"] == 16
    assert resumen["router"]["exactitud"] == 1.0
    assert resumen["clasificador_palabras_clave"]["texto"]["exactitud"] == 1.0
    assert set(resumen["extraccion"]) == {"curp", "csf", "ine", "comprobante_domicilio"}
    for por_modalidad in resumen["extraccion"].values():
        data = por_modalidad["digital"]
        assert data["extractor"] == "texto_reglas"
        assert data["documentos_100"] == 1.0
        assert data["costo_usd_por_documento"] == 0.0
        assert data["latencia_p95_ms"] >= data["latencia_p50_ms"] > 0
        assert all(v["exactitud"] == 1.0 for v in data["campos"].values())


def test_markdown_y_csv(resumen: dict) -> None:
    markdown = to_markdown(resumen, title="Prueba")
    assert "| Router (texto vs. imagen) | 16 | 100.0% |" in markdown
    assert "## curp: exactitud por campo" in markdown
    assert "| curp | digital | `texto_reglas` |" in markdown
    rows = to_csv_rows(resumen, split="train")
    assert {r["doc_type"] for r in rows} == {"curp", "csf", "ine", "comprobante_domicilio"}
    assert {r["modalidad"] for r in rows} == {"digital"}
    assert all(r["costo_usd"] == 0.0 for r in rows)


def test_cli_escribe_los_reportes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    args = ["--data", str(SAMPLES), "--split", "train", "--out", str(tmp_path), "--sin-ocr"]
    assert evaluate.main(args) == 0
    assert (tmp_path / "resultados.md").read_text(encoding="utf-8").startswith("# Resultados")
    assert "exactitud" in (tmp_path / "resultados.csv").read_text(encoding="utf-8")
    runs = list((tmp_path / "runs").glob("*_train.json"))
    assert len(runs) == 1
    run = json.loads(runs[0].read_text(encoding="utf-8"))
    assert run["extractores"] == ["texto_reglas"]
    assert "resumen" in run


def test_cli_sin_dataset(tmp_path: Path) -> None:
    assert evaluate.main(["--data", str(tmp_path), "--no-save"]) == 1


# ---------------------------------------------------------------------------
# eval_private: documentos "reales" (aquí, muestras sintéticas) sin exponer datos
# ---------------------------------------------------------------------------
@pytest.fixture
def carpeta_real(tmp_path: Path) -> tuple[Path, PersonTruth]:
    persona = SAMPLES / "train" / "train-00000"
    truth = PersonTruth.model_validate_json((persona / "ground_truth.json").read_text("utf-8"))
    real = tmp_path / "real"
    (real / "curp").mkdir(parents=True)
    (real / "csf").mkdir()
    # Nombres de archivo con datos personales: no deben aparecer en la salida.
    shutil.copy(persona / "curp.pdf", real / "curp" / f"CURP_{truth.form['apellido_paterno']}.pdf")
    shutil.copy(persona / "csf.pdf", real / "csf" / f"CSF_{truth.form['rfc']}.pdf")
    return real, truth


def _salida(real: Path, catalogo: SepomexCatalog | None, capsys: pytest.CaptureFixture[str]) -> str:
    eval_private.imprimir(eval_private.evaluar(real, catalog=catalogo))
    captured = capsys.readouterr()
    return captured.out + captured.err


def _assert_sin_datos(salida: str, truth: PersonTruth) -> None:
    for campo, valor in truth.form.items():
        if valor and len(valor) > 3 and campo != "nacionalidad":
            assert valor not in salida, campo
    assert "CURP_" not in salida and "CSF_" not in salida  # nombres de archivo


def test_eval_private_sin_etiquetas(
    carpeta_real: tuple[Path, PersonTruth], capsys: pytest.CaptureFixture[str]
) -> None:
    real, truth = carpeta_real
    salida = _salida(real, None, capsys)
    _assert_sin_datos(salida, truth)
    assert "== CURP: 1 documento(s)" in salida
    assert "1/1    CURP con dígito verificador válido" in salida
    assert "1/1    Nombre coherente con la CURP" in salida
    assert "1/1    RFC coherente con la CURP" in salida
    assert "1/1    Misma CURP en la constancia CURP y en la CSF" in salida
    assert "1/1    Mismo nombre, idéntico palabra por palabra" in salida
    assert "Sin etiquetas.json" in salida


def test_eval_private_con_etiquetas_y_error(
    carpeta_real: tuple[Path, PersonTruth],
    capsys: pytest.CaptureFixture[str],
    catalogo: SepomexCatalog,
) -> None:
    real, truth = carpeta_real
    archivo = next((real / "curp").glob("*.pdf")).name
    etiquetas = {f"curp/{archivo}": {"curp": truth.form["curp"], "nombre": "OTRO NOMBRE"}}
    (real / "etiquetas.json").write_text(json.dumps(etiquetas), encoding="utf-8")
    (real / "curp" / "dañado.pdf").write_bytes(b"%PDF-1.4 basura que no es un PDF")
    antes = sorted(p.name for p in real.rglob("*"))

    salida = _salida(real, catalogo, capsys)
    _assert_sin_datos(salida, truth)
    assert "1/1    Correcto (etiquetas): curp" in salida
    assert "0/1    Correcto (etiquetas): nombre" in salida
    assert "InvalidPdfError" in salida  # solo el tipo del error
    assert "== CURP: 2 documento(s)" in salida
    assert sorted(p.name for p in real.rglob("*")) == antes  # no escribió nada


def test_eval_private_carpeta_vacia(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert "No se encontraron PDFs" in _salida(tmp_path, None, capsys)
