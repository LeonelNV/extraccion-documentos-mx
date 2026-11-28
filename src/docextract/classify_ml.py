"""Clasificador de documentos entrenado: TF-IDF + regresión logística (scikit-learn).

Es el primer modelo entrenado del proyecto. Recibe el mismo texto que el clasificador de
palabras clave (capa de texto del PDF o texto del OCR) para compararlos en igualdad.

* **Características:** TF-IDF de palabras (1 y 2 palabras) y de fragmentos de 3 a 5
  caracteres dentro de cada palabra. Los fragmentos aguantan errores del OCR: "CREDENClAL"
  comparte casi todos sus fragmentos con "CREDENCIAL".
* **Texto preparado** (:func:`prepare_text`): mayúsculas sin acentos, dígitos como ``0``
  (un CP o un monto no dice qué documento es) y **sin las palabras que solo existen en los
  sintéticos** ("MUESTRA", "SPECIMEN", "FICTICIO"...). Están en todos los documentos
  sintéticos y en ningún real: el modelo aprendería atajos que no sirven en producción.
* **No reconocido:** si la probabilidad de la clase más probable queda bajo
  ``threshold``, el documento se reporta como no reconocido en lugar de forzar una clase.

El modelo no se versiona (``models/clasificador/``); ``make train-clasificador`` lo
regenera de forma determinista a partir del dataset sintético.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from docextract.classify import Classification
from docextract.layout import TextLayout
from docextract.normalize import comparison_key
from docextract.schemas import DocType

__all__ = [
    "DEFAULT_MODEL_DIR",
    "PALABRAS_SINTETICAS",
    "MlClassifier",
    "build_pipeline",
    "prepare_text",
]

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_DIR = ROOT / "models" / "clasificador"

PALABRAS_SINTETICAS = frozenset(
    [
        "MUESTRA",
        "SPECIMEN",
        "SINTETICO",
        "SINTETICA",
        "SINTETICOS",
        "SINTETICAS",
        "FICTICIO",
        "FICTICIA",
        "FICTICIOS",
        "FICTICIAS",
        "EJEMPLO",
        "VALIDEZ",
        "PRUEBAS",
        "SOFTWARE",
        "GENERADO",
        "GENERADOS",
        "GENERADA",
        "GENERADAS",
    ]
)
"""Palabras de las marcas de agua y avisos de las plantillas sintéticas."""

_NO_PALABRA = re.compile(r"[^A-Z0-9Ñ ]+")


def prepare_text(text: str) -> str:
    r"""Texto listo para el modelo.

    Un renglón con una palabra de ``PALABRAS_SINTETICAS`` se descarta **completo**: es un
    aviso de las plantillas ("Empresa y documento ficticios, generados para pruebas..."), y
    sus otras palabras ("EMPRESA Y DOCUMENTO") también serían una pista que solo existe en
    los sintéticos.

    >>> prepare_text("Código Postal: 63000, Tepic\nEmpresa ficticia de agua\nMUESTRA")
    'CODIGO POSTAL 00000 TEPIC'
    """
    words: list[str] = []
    for line in text.splitlines():
        line_words = re.sub(r"\d", "0", _NO_PALABRA.sub(" ", comparison_key(line))).split()
        if not any(w in PALABRAS_SINTETICAS for w in line_words):
            words += line_words
    return " ".join(words)


def build_pipeline(c: float, seed: int = 0):
    """TF-IDF de palabras y de fragmentos de caracteres + regresión logística."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import FeatureUnion, Pipeline

    features = FeatureUnion(
        [
            ("palabras", TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True)),
            (
                "caracteres",
                TfidfVectorizer(
                    analyzer="char_wb", ngram_range=(3, 5), min_df=2, sublinear_tf=True
                ),
            ),
        ]
    )
    model = LogisticRegression(C=c, max_iter=5000, class_weight="balanced", random_state=seed)
    return Pipeline([("tfidf", features), ("modelo", model)])


@dataclass
class MlClassifier:
    pipeline: object
    threshold: float
    metadata: dict

    def probabilities(self, texts: list[str]) -> list[dict[DocType, float]]:
        prepared = [prepare_text(t) for t in texts]
        probas = self.pipeline.predict_proba(prepared)
        classes = [DocType(c) for c in self.pipeline.classes_]
        return [dict(zip(classes, map(float, row), strict=True)) for row in probas]

    def classify_text(self, text: str) -> Classification:
        scores = self.probabilities([text])[0]
        best = max(scores, key=lambda d: scores[d])
        if scores[best] < self.threshold:
            return Classification(None, scores[best], scores)
        return Classification(best, scores[best], scores)

    def classify(self, layout: TextLayout) -> Classification:
        return self.classify_text(layout.text)

    # ------------------------------------------------------------------
    def save(self, folder: Path = DEFAULT_MODEL_DIR) -> None:
        import joblib

        folder.mkdir(parents=True, exist_ok=True)
        joblib.dump(self.pipeline, folder / "modelo.joblib")
        data = {**self.metadata, "threshold": self.threshold}
        (folder / "metadata.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    @classmethod
    def load(cls, folder: Path = DEFAULT_MODEL_DIR) -> MlClassifier:
        """Carga un modelo entrenado aquí con ``make train-clasificador``.

        joblib usa pickle: solo se cargan modelos de esta carpeta, nunca uno descargado.
        """
        import joblib

        metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
        return cls(joblib.load(folder / "modelo.joblib"), metadata["threshold"], metadata)
