"""Clasificador entrenado (TF-IDF + regresión logística) y su script de entrenamiento."""

import sys
from pathlib import Path

import pytest

from docextract.classify_ml import MlClassifier, build_pipeline, prepare_text
from docextract.layout import TextLayout
from docextract.schemas import DocType

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "data" / "synthetic" / "samples"
sys.path.insert(0, str(ROOT / "training"))
import train_clasificador  # noqa: E402

ARCHIVOS = {
    "curp.pdf": DocType.CURP,
    "csf.pdf": DocType.CSF,
    "ine.pdf": DocType.INE,
    "comprobante.pdf": DocType.COMPROBANTE_DOMICILIO,
}


@pytest.fixture(scope="module")
def modelo() -> MlClassifier:
    """Entrenado con la capa de texto de las muestras digitales, cada una cortada en mitades
    para tener más de un ejemplo por clase."""
    texts, labels = [], []
    for archivo, doc_type in ARCHIVOS.items():
        lines = TextLayout.from_pdf((SAMPLES / "train" / "train-00000" / archivo).read_bytes())
        lines = lines.text.splitlines()
        for half in (lines[: len(lines) // 2], lines[len(lines) // 2 :], lines):
            texts.append(prepare_text("\n".join(half)))
            labels.append(doc_type.value)
    pipeline = build_pipeline(1.0)
    pipeline.fit(texts, labels)
    return MlClassifier(pipeline, threshold=0.3, metadata={"prueba": True})


def test_prepara_el_texto_sin_marcas_de_lo_sintetico() -> None:
    lineas = ["MUESTRA / SPECIMEN", "C.P. 63000, Tepic", "Empresa y documento ficticios"]
    assert prepare_text("\n".join(lineas)) == "C P 00000 TEPIC"


def test_clasifica_y_rechaza(modelo: MlClassifier) -> None:
    for archivo, doc_type in ARCHIVOS.items():
        texto = TextLayout.from_pdf((SAMPLES / "test" / "test-00000" / archivo).read_bytes()).text
        if texto:  # los de imagen no tienen capa de texto
            assert modelo.classify_text(texto).doc_type is doc_type, archivo
    estricto = MlClassifier(modelo.pipeline, threshold=0.99, metadata={})
    resultado = estricto.classify_text("texto que no se parece a ningún documento")
    assert resultado.doc_type is None
    assert 0 < resultado.confidence < 0.99


def test_guardar_y_cargar(modelo: MlClassifier, tmp_path: Path) -> None:
    modelo.save(tmp_path)
    cargado = MlClassifier.load(tmp_path)
    assert cargado.threshold == modelo.threshold
    assert cargado.metadata["prueba"] is True
    texto = "CREDENCIAL PARA VOTAR CLAVE DE ELECTOR"
    assert cargado.probabilities([texto]) == modelo.probabilities([texto])


def test_metricas_cuentan_no_reconocido_como_error() -> None:
    y_true = ["curp", "curp", "ine", "csf"]
    y_pred = ["curp", train_clasificador.NO_RECONOCIDO, "ine", "curp"]
    m = train_clasificador.metricas(y_true, y_pred)
    assert m["exactitud"] == 0.5
    assert m["no_reconocidos"] == 1
    assert m["por_clase"]["curp"]["recall"] == 0.5
    assert m["matriz"]["curp"][train_clasificador.NO_RECONOCIDO] == 1
