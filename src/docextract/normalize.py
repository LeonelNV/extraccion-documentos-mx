"""Normalización de texto, fechas y datos de domicilio.

Regla general: el ``value`` que llega al formulario conserva el texto **tal como viene en el
documento** (solo se limpian espacios). Las funciones ``*_key`` producen una **clave de
comparación** (mayúsculas, sin acentos, con Ñ) que se usa únicamente para comparar valores
entre documentos o contra catálogos; nunca se muestra ni se guarda como valor.

Las excepciones son los datos con un formato canónico propio: identificadores (CURP, RFC),
código postal y fechas, que se convierten a su forma estándar.
"""

import re
import unicodedata
from datetime import date

__all__ = [
    "address_key",
    "clean_identifier",
    "clean_text",
    "comparison_key",
    "is_sin_numero",
    "normalize_codigo_postal",
    "parse_date",
    "strip_accents",
]

_WHITESPACE = re.compile(r"\s+")
# Caracteres invisibles que aparecen en texto copiado de PDFs o en la entrada de PowerShell:
# BOM / espacio de ancho cero sin salto (U+FEFF), espacio de ancho cero (U+200B), no-unión y
# unión de ancho cero (U+200C, U+200D) y guion suave (U+00AD).
_INVISIBLE = re.compile("[" + "".join(map(chr, (0xFEFF, 0x200B, 0x200C, 0x200D, 0x00AD))) + "]")


def _visible(text: str) -> str:
    return _INVISIBLE.sub("", text)


# Puntuación que se descarta en la clave de comparación. Se reemplaza por espacio para no
# pegar palabras ("LOPEZ-CASTILLO" -> "LOPEZ CASTILLO").
_PUNCTUATION = re.compile(r"[^\w\s]|_")


def clean_text(text: str | None) -> str | None:
    """Quita espacios sobrantes sin cambiar nada más. ``None`` se conserva."""
    if text is None:
        return None
    return _WHITESPACE.sub(" ", _visible(text)).strip()


def strip_accents(text: str, *, keep_enie: bool = True) -> str:
    """Quita acentos y diéresis (Á→A, Ü→U). Con ``keep_enie`` la Ñ se conserva."""
    out: list[str] = []
    for char in text:
        if keep_enie and char in "ñÑ":
            out.append(char)
            continue
        decomposed = unicodedata.normalize("NFD", char)
        out.append("".join(c for c in decomposed if not unicodedata.combining(c)))
    return "".join(out)


def comparison_key(text: str | None) -> str:
    """Clave para comparar: mayúsculas, sin acentos, con Ñ, sin puntuación ni espacios extra.

    >>> comparison_key("  María  José ")
    'MARIA JOSE'
    >>> comparison_key("Peña-Núñez")
    'PEÑA NUÑEZ'
    """
    if not text:
        return ""
    key = strip_accents(unicodedata.normalize("NFC", _visible(text))).upper()
    key = _PUNCTUATION.sub(" ", key)
    return _WHITESPACE.sub(" ", key).strip()


def clean_identifier(text: str | None) -> str:
    """Forma canónica de CURP y RFC: mayúsculas, sin espacios, guiones ni puntos."""
    if not text:
        return ""
    return re.sub(r"[\s\-.]", "", unicodedata.normalize("NFC", _visible(text))).upper()


# ---------------------------------------------------------------------------
# Fechas
# ---------------------------------------------------------------------------
_MONTHS = {
    "ENERO": 1,
    "ENE": 1,
    "FEBRERO": 2,
    "FEB": 2,
    "MARZO": 3,
    "MAR": 3,
    "ABRIL": 4,
    "ABR": 4,
    "MAYO": 5,
    "MAY": 5,
    "JUNIO": 6,
    "JUN": 6,
    "JULIO": 7,
    "JUL": 7,
    "AGOSTO": 8,
    "AGO": 8,
    "SEPTIEMBRE": 9,
    "SETIEMBRE": 9,
    "SEPT": 9,
    "SEP": 9,
    "SET": 9,
    "OCTUBRE": 10,
    "OCT": 10,
    "NOVIEMBRE": 11,
    "NOV": 11,
    "DICIEMBRE": 12,
    "DIC": 12,
}
_MONTH_NAMES = "|".join(sorted(_MONTHS, key=len, reverse=True))
_SEP = r"[/\-. ]"

# Día, mes y año numéricos: 15/03/1990, 15-03-1990, 15.03.90
_DMY_NUMERIC = re.compile(rf"^(\d{{1,2}}){_SEP}(\d{{1,2}}){_SEP}(\d{{4}}|\d{{2}})$")
# ISO y variantes: 1990-03-15, 1990/03/15
_YMD_NUMERIC = re.compile(rf"^(\d{{4}}){_SEP}(\d{{1,2}}){_SEP}(\d{{1,2}})$")
# Mes con nombre: 15 DE MARZO DE 1990, 15/MAR/1990, 15-MAR-90, 15 MARZO 1990
_DMY_TEXT = re.compile(
    rf"^(\d{{1,2}})(?:\s+DE\s+|{_SEP}+)({_MONTH_NAMES})(?:\s+DE\s+|\s+DEL\s+|{_SEP}+)(\d{{4}}|\d{{2}})$"
)
# Mes primero: MARZO 15, 1990 / MARZO 15 DE 1990
_MDY_TEXT = re.compile(rf"^({_MONTH_NAMES})\s+(\d{{1,2}}),?\s+(?:DE\s+)?(\d{{4}})$")


def _year(text: str, allow_two_digit_year: bool) -> int | None:
    if len(text) == 4:
        return int(text)
    # Un año de dos dígitos es ambiguo para fechas de nacimiento; solo se acepta cuando la
    # fecha es reciente (p. ej. la emisión de un comprobante), y entonces es del siglo XXI.
    return 2000 + int(text) if allow_two_digit_year else None


def _make_date(year: int | None, month: int, day: int) -> date | None:
    if year is None:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_date(text: str | None, *, allow_two_digit_year: bool = False) -> date | None:
    """Convierte una fecha como aparece en los documentos a ``date``.

    Acepta ``15/03/1990``, ``15-03-1990``, ``1990-03-15``, ``15/MAR/1990``,
    ``15 de marzo de 1990`` y ``marzo 15, 1990``. Devuelve ``None`` si no reconoce el
    formato o si la fecha no existe (p. ej. 30 de febrero); quien llama decide la advertencia.
    """
    if not text:
        return None
    candidate = strip_accents(text).upper()
    candidate = re.sub(r"(?<=[A-Z])\.", "", candidate)  # "MAR." -> "MAR"
    candidate = _WHITESPACE.sub(" ", candidate).strip()

    if m := _DMY_NUMERIC.match(candidate):
        day, month, year = m.groups()
        return _make_date(_year(year, allow_two_digit_year), int(month), int(day))
    if m := _YMD_NUMERIC.match(candidate):
        year, month, day = m.groups()
        return _make_date(int(year), int(month), int(day))
    if m := _DMY_TEXT.match(candidate):
        day, month, year = m.groups()
        return _make_date(_year(year, allow_two_digit_year), _MONTHS[month], int(day))
    if m := _MDY_TEXT.match(candidate):
        month, day, year = m.groups()
        return _make_date(int(year), _MONTHS[month], int(day))
    return None


# ---------------------------------------------------------------------------
# Domicilio
# ---------------------------------------------------------------------------
def normalize_codigo_postal(text: str | None) -> str | None:
    """CP de 5 dígitos. Rellena con cero un CP de 4 dígitos (Excel suele quitar el cero).

    Devuelve ``None`` si el texto no tiene la forma de un código postal.
    """
    if not text:
        return None
    digits = re.sub(r"(?i)^\s*(C\.?\s*P\.?|CODIGO POSTAL|CÓDIGO POSTAL)\s*:?\s*", "", text)
    digits = re.sub(r"\s", "", digits)
    if not digits.isdigit() or len(digits) not in (4, 5):
        return None
    return digits.zfill(5)


# Abreviaturas comunes en domicilios -> forma completa (solo para la clave de comparación).
_ADDRESS_ABBREVIATIONS = {
    "AV": "AVENIDA",
    "AVE": "AVENIDA",
    "AVDA": "AVENIDA",
    "C": "CALLE",
    "CLL": "CALLE",
    "COL": "COLONIA",
    "FRACC": "FRACCIONAMIENTO",
    "FRAC": "FRACCIONAMIENTO",
    "BLVD": "BOULEVARD",
    "BLV": "BOULEVARD",
    "BULEVAR": "BOULEVARD",
    "CDA": "CERRADA",
    "PRIV": "PRIVADA",
    "PROL": "PROLONGACION",
    "CARR": "CARRETERA",
    "CTO": "CIRCUITO",
    "CALZ": "CALZADA",
    "AND": "ANDADOR",
    "BO": "BARRIO",
    "U": "UNIDAD",
    "HAB": "HABITACIONAL",
    "INT": "INTERIOR",
    "EXT": "EXTERIOR",
    "NUM": "NUMERO",
    "NO": "NUMERO",
    "STA": "SANTA",
    "STO": "SANTO",
    "GRAL": "GENERAL",
    "LIC": "LICENCIADO",
    "PTE": "PONIENTE",
    "OTE": "ORIENTE",
}


def address_key(text: str | None) -> str:
    """Clave de comparación para partes del domicilio, con abreviaturas expandidas.

    >>> address_key("Av. Insurgentes Nte.")
    'AVENIDA INSURGENTES NTE'
    """
    words = comparison_key(text).split()
    return " ".join(_ADDRESS_ABBREVIATIONS.get(w, w) for w in words)


_SIN_NUMERO = re.compile(r"^(S\s*/?\s*N|SIN\s+NUMERO|SIN\s+NUM|SN)$")


def is_sin_numero(text: str | None) -> bool:
    """Verdadero si el número exterior o interior dice "sin número" (S/N, SN, SIN NUMERO)."""
    if not text:
        return False
    plain = _WHITESPACE.sub(" ", strip_accents(text).upper().replace(".", "")).strip()
    return bool(_SIN_NUMERO.match(plain))
