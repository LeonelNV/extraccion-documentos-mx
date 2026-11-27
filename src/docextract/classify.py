"""Clasificador de tipo de documento a partir de su texto (palabras clave con peso).

En la FEA cada documento se sube en su propio campo, así que el tipo esperado ya se conoce.
El clasificador sirve para **verificar** que el documento corresponda al campo: si no, la
advertencia ``DOCUMENTO_NO_RECONOCIDO`` pide revisarlo. Funciona igual con el texto de un PDF
digital que con el de un OCR (fase 5).

Las frases son las que imprimen los documentos reales y comparten las plantillas
sintéticas; los pesos favorecen los títulos, que son lo más distintivo.
"""

import re
from dataclasses import dataclass, field

from docextract.layout import TextLayout
from docextract.normalize import comparison_key
from docextract.schemas import DocType, ExtractionWarning, WarningCode
from docextract.validators._common import make_warning

__all__ = ["KEYWORDS", "Classification", "classify_text", "verify_doc_type"]

KEYWORDS: dict[DocType, tuple[tuple[str, float], ...]] = {
    DocType.CURP: (
        ("CLAVE UNICA DE REGISTRO DE POBLACION", 4.0),
        ("CONSTANCIA DE LA CLAVE UNICA", 2.0),
        ("ENTIDAD DE NACIMIENTO", 1.5),
        ("PRIMER APELLIDO", 0.5),
        ("SEGUNDO APELLIDO", 0.5),
    ),
    DocType.CSF: (
        ("CONSTANCIA DE SITUACION FISCAL", 4.0),
        ("CEDULA DE IDENTIFICACION FISCAL", 3.0),
        ("IDCIF", 2.0),
        ("REGISTRO FEDERAL DE CONTRIBUYENTES", 1.5),
        ("DATOS DEL DOMICILIO REGISTRADO", 1.5),
        ("REGIMEN", 1.0),
        ("ESTATUS EN EL PADRON", 1.0),
    ),
    DocType.INE: (
        ("CREDENCIAL PARA VOTAR", 4.0),
        ("CLAVE DE ELECTOR", 3.0),
        ("ANO DE REGISTRO", 1.0),
        ("SECCION", 0.5),
        ("VIGENCIA", 0.5),
    ),
    DocType.COMPROBANTE_DOMICILIO: (
        ("ESTADO DE CUENTA", 2.5),
        ("TOTAL A PAGAR", 2.0),
        ("FECHA LIMITE DE PAGO", 2.0),
        ("PERIODO FACTURADO", 2.0),
        ("FECHA DE CORTE", 2.0),
        ("LECTURA ANTERIOR", 2.0),
        ("NUMERO DE SERVICIO", 1.5),
        ("NO DE SERVICIO", 1.5),
        ("CONSUMO", 1.0),
        ("RECIBO", 1.0),
        ("FACTURA", 1.0),
        ("SALDO", 1.0),
        ("PERIODO", 0.5),
        ("IMPORTE", 0.5),
    ),
}

MIN_SCORE = 3.0
"""Puntaje mínimo para decidir; por debajo, el documento no se reconoce."""


@dataclass(frozen=True)
class Classification:
    doc_type: DocType | None
    """``None`` si ningún tipo alcanza el puntaje mínimo."""
    confidence: float
    scores: dict[DocType, float] = field(default_factory=dict)


def _contains(text: str, phrase: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text) is not None


def classify_text(layout: TextLayout) -> Classification:
    text = comparison_key(layout.text)
    scores = {
        doc_type: sum(weight for phrase, weight in phrases if _contains(text, phrase))
        for doc_type, phrases in KEYWORDS.items()
    }
    best = max(scores, key=lambda d: scores[d])
    total = sum(scores.values())
    if scores[best] < MIN_SCORE:
        return Classification(None, 0.0, scores)
    return Classification(best, round(scores[best] / total, 3), scores)


def verify_doc_type(expected: DocType, classification: Classification) -> list[ExtractionWarning]:
    """Advierte si el documento no parece del tipo que se esperaba en ese campo."""
    if classification.doc_type == expected:
        return []
    return [
        make_warning(
            WarningCode.DOCUMENTO_NO_RECONOCIDO,
            "El documento no parece corresponder al tipo esperado; revisa que se haya subido "
            "en el campo correcto.",
            docs=(expected,),
        )
    ]
