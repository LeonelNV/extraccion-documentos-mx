"""Catálogo de entidades federativas.

Une tres formas de nombrar la misma entidad:

- ``clave_curp``: las dos letras de las posiciones 12 y 13 de la CURP. ``NE`` = nacido en el
  extranjero.
- ``clave_inegi``: la clave numérica de dos dígitos que usa SEPOMEX (``c_estado``).
- ``nombre``: el nombre exactamente como aparece en el catálogo de SEPOMEX.

Fuentes y verificación:

- Los nombres y las claves numéricas se verificaron contra el catálogo de SEPOMEX descargado
  el 2026-11-26 (``tests/test_sepomex.py`` lo vuelve a comprobar si el catálogo está
  descargado).
- Las Reglas de RENAPO para la asignación de la CURP remiten las claves de dos letras a su
  "Anexo 03. Catálogo de Entidades Federativas para la conformación de la CURP", que no está
  publicado en línea. Las claves de abajo son las de uso público; si se consigue el anexo,
  hay que compararlas.
"""

from dataclasses import dataclass
from functools import cache

from rapidfuzz import fuzz, process

from docextract.normalize import comparison_key

__all__ = ["ENTIDADES", "NACIDO_EN_EXTRANJERO", "Entidad", "find_entidad", "por_clave_curp"]


@dataclass(frozen=True)
class Entidad:
    clave_curp: str
    clave_inegi: str
    nombre: str
    variantes: tuple[str, ...] = ()


ENTIDADES: tuple[Entidad, ...] = (
    Entidad("AS", "01", "Aguascalientes", ("AGS",)),
    Entidad("BC", "02", "Baja California", ("BC", "B C")),
    Entidad("BS", "03", "Baja California Sur", ("BCS", "B C S")),
    Entidad("CC", "04", "Campeche", ("CAMP",)),
    Entidad("CL", "05", "Coahuila de Zaragoza", ("COAHUILA", "COAH")),
    Entidad("CM", "06", "Colima", ("COL",)),
    Entidad("CS", "07", "Chiapas", ("CHIS",)),
    Entidad("CH", "08", "Chihuahua", ("CHIH",)),
    Entidad(
        "DF",
        "09",
        "Ciudad de México",
        ("CDMX", "CD MX", "CD DE MEXICO", "DISTRITO FEDERAL", "D F", "DF", "MEXICO D F"),
    ),
    Entidad("DG", "10", "Durango", ("DGO",)),
    Entidad("GT", "11", "Guanajuato", ("GTO",)),
    Entidad("GR", "12", "Guerrero", ("GRO",)),
    Entidad("HG", "13", "Hidalgo", ("HGO",)),
    Entidad("JC", "14", "Jalisco", ("JAL",)),
    Entidad(
        "MC",
        "15",
        "México",
        ("ESTADO DE MEXICO", "EDO DE MEXICO", "EDO MEX", "EDOMEX", "EDO DE MEX", "MEX"),
    ),
    Entidad("MN", "16", "Michoacán de Ocampo", ("MICHOACAN", "MICH")),
    Entidad("MS", "17", "Morelos", ("MOR",)),
    Entidad("NT", "18", "Nayarit", ("NAY",)),
    Entidad("NL", "19", "Nuevo León", ("N L",)),
    Entidad("OC", "20", "Oaxaca", ("OAX",)),
    Entidad("PL", "21", "Puebla", ("PUE",)),
    Entidad("QT", "22", "Querétaro", ("QUERETARO DE ARTEAGA", "QRO")),
    Entidad("QR", "23", "Quintana Roo", ("Q ROO", "QROO")),
    Entidad("SP", "24", "San Luis Potosí", ("SLP", "S L P")),
    Entidad("SL", "25", "Sinaloa", ("SIN",)),
    Entidad("SR", "26", "Sonora", ("SON",)),
    Entidad("TC", "27", "Tabasco", ("TAB",)),
    Entidad("TS", "28", "Tamaulipas", ("TAMPS",)),
    Entidad("TL", "29", "Tlaxcala", ("TLAX",)),
    Entidad("VZ", "30", "Veracruz de Ignacio de la Llave", ("VERACRUZ", "VER")),
    Entidad("YN", "31", "Yucatán", ("YUC",)),
    Entidad("ZS", "32", "Zacatecas", ("ZAC",)),
)

NACIDO_EN_EXTRANJERO = "NE"
"""Clave de la CURP para personas nacidas en el extranjero."""

CLAVES_CURP: frozenset[str] = frozenset(e.clave_curp for e in ENTIDADES) | {NACIDO_EN_EXTRANJERO}

# Umbral para aceptar un nombre de entidad escrito con errores (OCR). Es alto a propósito:
# los nombres de entidad son cortos y distintos entre sí.
_FUZZY_THRESHOLD = 88


@cache
def _index() -> dict[str, Entidad]:
    index: dict[str, Entidad] = {}
    for entidad in ENTIDADES:
        for name in (entidad.nombre, *entidad.variantes):
            index[comparison_key(name)] = entidad
    return index


def por_clave_curp(clave: str) -> Entidad | None:
    """Entidad para una clave de la CURP. ``NE`` y las claves desconocidas devuelven ``None``."""
    return next((e for e in ENTIDADES if e.clave_curp == clave), None)


def find_entidad(text: str | None) -> Entidad | None:
    """Reconoce una entidad por su nombre, una variante o una abreviatura común.

    Tolera acentos, puntuación ("Edo. de Méx.") y errores leves de OCR.
    """
    key = comparison_key(text)
    if not key:
        return None
    index = _index()
    if key in index:
        return index[key]
    # Abreviaturas cortas solo por coincidencia exacta: con difusa, "SIN" y "SON" se confunden.
    if len(key) <= 4:
        return None
    match = process.extractOne(key, index.keys(), scorer=fuzz.ratio, score_cutoff=_FUZZY_THRESHOLD)
    return index[match[0]] if match else None
