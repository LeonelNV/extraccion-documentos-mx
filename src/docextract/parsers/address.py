"""Reglas para leer un domicilio escrito en renglones (INE y comprobantes).

>>> split_street("C 5 DE MAYO 123 INT 4")
('C 5 DE MAYO', '123', '4')
>>> split_street("Calle Juárez No. 45-B, Int. Depto. 3")
('Calle Juárez', '45-B', 'Depto. 3')
>>> split_street("AV HIDALGO S/N")
('AV HIDALGO', 'S/N', '')
>>> split_colonia_cp("FRACC LOS MANGOS 63738")
('LOS MANGOS', '63738')
>>> split_colonia_cp("COL. CENTRO")
('CENTRO', None)
>>> split_city_state("BAHIA DE BANDERAS, NAY.")
('BAHIA DE BANDERAS', 'NAY.')
"""

import re

__all__ = [
    "CP_RE",
    "PREFIJOS_COLONIA",
    "default_catalog",
    "repair_cp",
    "split_city_state",
    "split_colonia_cp",
    "split_street",
]

# El número exterior va al final de la calle (la calle puede llevar números: "5 DE MAYO").
_STREET_RE = re.compile(
    r"""^(?P<calle>.+?)[\s,]+
        (?:N[OÚU]M?\.?\s*|\#\s*)?
        (?P<ext>S\s?/\s?N|\d+(?:\s?-\s?[A-Z0-9]+|\s(?:[A-C]|BIS))?)
        (?:[\s,]+INT(?:ERIOR)?\.?\s*(?P<int>.+?))?
        [\s,.]*$""",
    re.IGNORECASE | re.VERBOSE,
)
CP_RE = re.compile(r"(?:C\.?\s?P\.?\s*)?(?<!\d)(\d{5})(?!\d)", re.IGNORECASE)
PREFIJOS_COLONIA = re.compile(
    r"^(?:COL(?:ONIA)?|FRACC(?:IONAMIENTO)?|BO|BARRIO|U\.?\s?HAB|UNIDAD HABITACIONAL)\.?\s+",
    re.IGNORECASE,
)


def split_street(line: str) -> tuple[str, str, str] | None:
    """(calle, número exterior, número interior); interior ``""`` si no hay."""
    match = _STREET_RE.match(line.strip())
    if not match:
        return None
    ext = re.sub(r"\s*/\s*", "/", match["ext"])
    interior = (match["int"] or "").strip(" ,")
    return match["calle"].strip(" ,"), ext, interior


def split_colonia_cp(line: str) -> tuple[str, str | None]:
    """(colonia sin prefijo, código postal o ``None``)."""
    cp = None
    match = CP_RE.search(line)
    if match:
        cp = match[1]
        line = (line[: match.start()] + line[match.end() :]).strip(" ,")
    return PREFIJOS_COLONIA.sub("", line.strip(" ,")).strip(" ,"), cp


def split_city_state(line: str) -> tuple[str, str]:
    """(ciudad o municipio, estado), separados por la última coma."""
    if "," in line:
        ciudad, estado = line.rsplit(",", 1)
        return ciudad.strip(), estado.strip()
    return line.strip(), ""


# ---------------------------------------------------------------------------
# Código postal leído por OCR
# ---------------------------------------------------------------------------
# Dígitos que el OCR confunde entre sí (medido en train: 5↔6, 0↔6, 8↔6, 3↔8...).
DIGITOS_PARECIDOS = {
    "0": "689", "1": "7", "2": "7", "3": "85", "4": "9", "5": "63", "6": "5089",
    "7": "12", "8": "6309", "9": "8604",
}  # fmt: skip


def default_catalog():
    """El catálogo de SEPOMEX si está descargado (``make sepomex``); si no, ``None``."""
    from docextract.validators.sepomex import SepomexCatalog, SepomexNotAvailableError

    try:
        return SepomexCatalog.load_default()
    except SepomexNotAvailableError:
        return None


def repair_cp(cp: str | None, catalog, *, municipio: str | None, estado: str | None) -> str | None:
    """Corrige un dígito mal leído del CP con el catálogo y el municipio o estado impresos.

    Solo cambia el CP si el leído no existe o no corresponde a lo impreso, y si hay
    exactamente una sustitución de un dígito parecido que exista en SEPOMEX y coincida con el
    municipio (o, sin municipio, con el estado). Si no, devuelve el CP tal cual.
    """
    from rapidfuzz import fuzz

    from docextract.entidades import find_entidad
    from docextract.normalize import comparison_key

    if catalog is None or not cp or not re.fullmatch(r"\d{5}", cp):
        return cp
    entidad = find_entidad(estado) if estado else None

    def coincide(codigo: str) -> bool:
        rows = catalog.lookup(codigo)
        if not rows:
            return False
        if municipio:
            key = comparison_key(municipio)
            return any(fuzz.ratio(key, comparison_key(r.municipio)) >= 85 for r in rows)
        return entidad is not None and find_entidad(rows[0].estado) == entidad

    if not municipio and entidad is None:
        return cp
    if coincide(cp):
        return cp
    candidatos = {
        cp[:i] + d + cp[i + 1 :]
        for i, c in enumerate(cp)
        for d in DIGITOS_PARECIDOS.get(c, "")
        if coincide(cp[:i] + d + cp[i + 1 :])
    }
    return candidatos.pop() if len(candidatos) == 1 else cp
