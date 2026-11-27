"""Comparación difusa de nombres entre documentos (CURP, INE, CSF).

Se compara sobre la clave normalizada (mayúsculas, sin acentos, con Ñ, sin puntuación), con
las abreviaturas comunes de nombres de pila expandidas ("MA." → MARIA, "J." → JOSE). Los
valores originales no se modifican.
"""

from pydantic import BaseModel, ConfigDict
from rapidfuzz import fuzz

from docextract.config import ValidationConfig
from docextract.normalize import comparison_key
from docextract.schemas import DocType, ExtractionWarning, WarningCode
from docextract.validators._common import make_warning

__all__ = ["NAME_FIELDS", "PersonName", "compare_names", "name_key", "name_similarity"]

NAME_FIELDS = ("nombre", "apellido_paterno", "apellido_materno")

# Abreviaturas de nombres de pila (solo aplican al campo "nombre").
_ABREVIATURAS_NOMBRE = {
    "MA": "MARIA",
    "MARI": "MARIA",
    "J": "JOSE",
    "JOS": "JOSE",
    "GPE": "GUADALUPE",
    "FCO": "FRANCISCO",
    "FDO": "FERNANDO",
    "FCA": "FRANCISCA",
    "JN": "JUAN",
}


def name_key(text: str | None, *, es_nombre: bool = False) -> str:
    """Clave de comparación de un nombre o apellido.

    >>> name_key("Ma. de los Ángeles", es_nombre=True)
    'MARIA DE LOS ANGELES'
    """
    words = comparison_key(text).split()
    if es_nombre:
        words = [_ABREVIATURAS_NOMBRE.get(w, w) for w in words]
    return " ".join(words)


def name_similarity(a: str | None, b: str | None, *, es_nombre: bool = False) -> float:
    """Similitud entre 0 y 1 (distancia de edición normalizada) entre dos nombres."""
    key_a, key_b = name_key(a, es_nombre=es_nombre), name_key(b, es_nombre=es_nombre)
    if key_a == key_b:
        return 1.0
    return fuzz.ratio(key_a, key_b) / 100


class PersonName(BaseModel):
    """Nombre de una persona como aparece en un documento.

    ``None`` = no se extrajo; ``""`` en el apellido materno = el documento indica que no tiene.
    """

    model_config = ConfigDict(frozen=True)

    nombre: str | None = None
    apellido_paterno: str | None = None
    apellido_materno: str | None = None

    def full_key(self) -> str:
        parts = (
            name_key(self.nombre, es_nombre=True),
            name_key(self.apellido_paterno),
            name_key(self.apellido_materno),
        )
        return "".join(parts).replace(" ", "")


def compare_names(
    a: PersonName,
    b: PersonName,
    *,
    config: ValidationConfig | None = None,
    docs: tuple[DocType, ...] = (),
) -> list[ExtractionWarning]:
    """Compara nombre y apellidos de dos documentos y advierte si difieren.

    Devuelve a lo sumo una advertencia ``NOMBRE_NO_COINCIDE`` con los campos que difieren.
    Si el nombre completo es igual pero está repartido distinto entre los campos (p. ej. un
    apellido compuesto), no se advierte.
    """
    config = config or ValidationConfig()
    complete = all(getattr(p, f) is not None for p in (a, b) for f in NAME_FIELDS)
    if complete and a.full_key() == b.full_key():
        return []

    differing: list[str] = []
    for field in NAME_FIELDS:
        value_a, value_b = getattr(a, field), getattr(b, field)
        if value_a is None or value_b is None:
            continue
        if not value_a.strip() and not value_b.strip():
            continue
        if not value_a.strip() or not value_b.strip():  # uno dice "no tiene" y el otro no
            differing.append(field)
            continue
        similarity = name_similarity(value_a, value_b, es_nombre=field == "nombre")
        if similarity < config.name_similarity_threshold:
            differing.append(field)

    if not differing:
        return []
    return [
        make_warning(
            WarningCode.NOMBRE_NO_COINCIDE,
            "El nombre no coincide entre documentos en: " + ", ".join(differing) + ".",
            fields=differing,
            docs=docs,
        )
    ]
