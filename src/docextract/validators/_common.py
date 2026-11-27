"""Utilidades compartidas por los validadores."""

import unicodedata
from collections.abc import Iterable

from docextract.normalize import strip_accents
from docextract.schemas import DocType, ExtractionWarning, WarningCode

VOCALES = frozenset("AEIOU")
LETRAS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ")


def make_warning(
    code: WarningCode,
    message: str,
    *,
    fields: Iterable[str] = (),
    docs: Iterable[DocType] = (),
) -> ExtractionWarning:
    """Crea una advertencia. ``message`` nunca debe incluir valores extraídos."""
    return ExtractionWarning(code=code, message=message, fields=tuple(fields), docs=tuple(docs))


def palabras_para_clave(text: str | None) -> list[str]:
    """Prepara un nombre o apellido para construir CURP o RFC.

    Mayúsculas, sin acentos (Ü→U), con Ñ. El guion separa palabras (apellidos compuestos
    como "LOPEZ-CASTILLO"); los demás caracteres especiales se conservan porque las reglas
    de RENAPO les asignan una "X" cuando caen en una posición de la clave.
    """
    if not text:
        return []
    plain = strip_accents(unicodedata.normalize("NFC", text)).upper()
    return plain.replace("-", " ").split()


def quitar_iniciales(
    words: list[str],
    *,
    particulas: frozenset[str],
    nombres_comunes: frozenset[str] = frozenset(),
) -> list[str]:
    """Quita del inicio un nombre común (JOSE, MARIA…) y las partículas (DE, DEL, LA…).

    Siempre deja al menos una palabra: un nombre que solo es "MARIA" o un apellido que solo
    es "DE" se usan tal cual.
    """
    if len(words) > 1 and words[0].rstrip(".") in nombres_comunes:
        words = words[1:]
    while len(words) > 1 and words[0].rstrip(".") in particulas:
        words = words[1:]
    return words
