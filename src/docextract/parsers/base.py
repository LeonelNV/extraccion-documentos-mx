"""Piezas comunes de los parsers de texto."""

import re
from collections.abc import Iterable
from typing import Protocol

from docextract.layout import TextLayout
from docextract.normalize import clean_identifier, clean_text
from docextract.schemas import DocType, ExtractedField, ExtractionResult, ExtractionWarning
from docextract.validators.curp import CurpInfo, curp_name_letters, validate_curp
from docextract.validators.rfc import RFC_PF_RE, validate_rfc

__all__ = [
    "EXTRACTOR_NAME",
    "Confianza",
    "TextParser",
    "field",
    "find_curp",
    "find_rfc",
    "split_full_name",
]

EXTRACTOR_NAME = "texto_reglas"


class Confianza:
    """Confianzas de las reglas. Provisionales: se calibran en la fase 5."""

    VALIDADO = 0.99
    """Identificador con dígito verificador válido, o dato que coincide con la CURP."""
    ETIQUETADO = 0.95
    """Encontrado junto a su etiqueta, sin forma de validarlo."""
    DERIVADO = 0.90
    """No está impreso: se dedujo de la CURP."""
    DUDOSO = 0.70
    """Encontrado, pero ambiguo (p. ej. un nombre completo que admite dos divisiones)."""
    INCONSISTENTE = 0.60
    """Encontrado, pero contradice otro dato del mismo documento."""
    INVALIDO = 0.50
    """Tiene el formato pero no pasa la validación (dígito verificador)."""


class TextParser(Protocol):
    doc_type: DocType
    fields: tuple[str, ...]
    """Campos que el parser intenta extraer (los que se evalúan)."""

    def parse(self, layout: TextLayout) -> ExtractionResult: ...


def field(
    value: str | None, confidence: float, warnings: Iterable[ExtractionWarning] = ()
) -> ExtractedField:
    if value is None:
        return ExtractedField(value=None, confidence=0.0, warnings=tuple(warnings))
    return ExtractedField(value=clean_text(value), confidence=confidence, warnings=tuple(warnings))


# ---------------------------------------------------------------------------
# Identificadores en cualquier parte del texto
# ---------------------------------------------------------------------------
def _candidates(text: str, length: int) -> list[str]:
    """Secuencias alfanuméricas de ``length`` caracteres (las claves vienen sin espacios)."""
    tokens = re.findall(r"[A-Z0-9Ñ&]+", text.upper())
    return [t for t in tokens if len(t) == length]


def find_curp(text: str) -> tuple[str | None, CurpInfo | None, float]:
    """La CURP del documento: primero una con dígito válido; si no, una con formato válido."""
    con_formato: tuple[str, CurpInfo] | None = None
    for candidate in _candidates(text, 18):
        result = validate_curp(candidate)
        if result.valid:
            return result.curp, result.info, Confianza.VALIDADO
        if result.info is not None and con_formato is None:
            con_formato = (result.curp, result.info)
    if con_formato:
        return con_formato[0], con_formato[1], Confianza.INVALIDO
    return None, None, 0.0


def find_rfc(text: str, *, prefer: str | None = None) -> tuple[str | None, float]:
    """El RFC de persona física: el que sigue a ``prefer`` (texto de la etiqueta) o el
    primero válido."""
    candidates = []
    if prefer:
        candidates.append(clean_identifier(prefer))
    candidates += _candidates(text, 13)
    fallback: str | None = None
    for candidate in candidates:
        if not RFC_PF_RE.match(candidate):
            continue
        result = validate_rfc(candidate)
        if result.valid:
            return result.rfc, Confianza.VALIDADO
        if fallback is None and result.formato_valido and not result.generico:
            fallback = result.rfc
    return (fallback, Confianza.INVALIDO) if fallback else (None, 0.0)


# ---------------------------------------------------------------------------
# Nombre completo en una sola línea
# ---------------------------------------------------------------------------
def split_full_name(full_name: str, curp: str) -> tuple[tuple[str, str, str] | None, bool]:
    """Divide un nombre completo en (nombre, primer apellido, segundo apellido) usando la CURP.

    Prueba todas las divisiones en los dos órdenes habituales (nombre primero o apellidos
    primero) y se queda con las que reproducen las letras de la CURP: las 4 iniciales y las
    3 consonantes internas. Devuelve la división y si fue ambigua (varias igual de buenas).
    """
    tokens = full_name.split()
    n = len(tokens)
    if n < 2 or len(curp) < 16:
        return None, False
    target_initials, target_consonants = curp[:4], curp[13:16]

    def join(part: list[str]) -> str:
        return " ".join(part)

    splits: list[tuple[str, str, str]] = []
    # Nombre primero: NOMBRE PATERNO [MATERNO]
    for i in range(1, n):
        for j in range(i + 1, n + 1):
            splits.append((join(tokens[:i]), join(tokens[i:j]), join(tokens[j:])))
    # Apellidos primero: PATERNO [MATERNO] NOMBRE
    for i in range(1, n):
        for j in range(i, n):
            splits.append((join(tokens[j:]), join(tokens[:i]), join(tokens[i:j])))

    candidates: list[tuple[int, tuple[str, str, str]]] = []
    for split in splits:
        initials, consonants = curp_name_letters(*split)
        same = initials == target_initials
        # Tolera la X de una palabra altisonante que no esté en nuestra lista.
        x_tolerada = target_initials[1] == "X" and (
            initials[0] + initials[2:] == target_initials[0] + target_initials[2:]
        )
        if same or x_tolerada:
            candidates.append((1 + (consonants == target_consonants), split))
    if not candidates:
        return None, False
    best = max(score for score, _ in candidates)
    winners = list(dict.fromkeys(split for score, split in candidates if score == best))
    return winners[0], len(winners) > 1
