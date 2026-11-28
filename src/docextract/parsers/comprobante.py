"""Parser genérico de comprobantes de domicilio: no depende del diseño del recibo.

Cada empresa acomoda el domicilio a su manera (renglones, una línea con comas, campos con
etiqueta), así que el parser no busca posiciones fijas:

1. **Código postal:** un número de 5 dígitos, de preferencia tras "C.P." y que exista en
   SEPOMEX.
2. **Bloque de domicilio:** los renglones alrededor del CP en la misma columna, partidos en
   piezas por comas.
3. **Calle y números:** la primera pieza con la forma "calle + número".
4. **Colonia, ciudad y estado:** la pieza que más se parece a lo que SEPOMEX dice de ese CP.
   Si la ciudad o el estado no aparecen impresos pero el CP los determina, se toman del
   catálogo con confianza ``DERIVADO``.
5. **Fecha de emisión:** la fecha junto a una etiqueta de emisión o de corte; si no hay
   etiqueta, la más reciente que no sea una fecha límite de pago.

Las reglas se escribieron mirando solo los diseños de train (luz, agua y banco). El diseño
de teléfono, reservado para test, no aportó ninguna etiqueta: mide la generalización.

Sin catálogo de SEPOMEX funciona con reglas más débiles (prefijo "COL", "ciudad, estado").
"""

import re
import time
from dataclasses import dataclass

from rapidfuzz import fuzz

from docextract.entidades import find_entidad
from docextract.layout import Line, TextLayout, Word
from docextract.normalize import comparison_key, parse_date
from docextract.parsers.address import CP_RE, PREFIJOS_COLONIA, split_street
from docextract.parsers.base import EXTRACTOR_NAME, Confianza, field
from docextract.schemas import DocType, ExtractedField, ExtractionResult
from docextract.validators.sepomex import SepomexCatalog, SepomexNotAvailableError

__all__ = ["ComprobanteParser", "find_dates"]

DOMICILIO_FIELDS = (
    "calle", "numero_exterior", "numero_interior", "colonia", "codigo_postal", "ciudad", "estado",
)  # fmt: skip
ETIQUETAS_FECHA = ("EMISION", "FECHA DE CORTE")
"""Etiquetas de la fecha del documento. "Fecha límite de pago" y "periodo" no lo son."""
NO_ES_EMISION = ("LIMITE", "VENCIMIENTO", "VENCE")
ETIQUETAS_DOMICILIO = re.compile(
    r"^(?:DOMICILIO|DIRECCION|USUARIO|TITULAR|CLIENTE|NOMBRE)\s*:?\s*", re.IGNORECASE
)

_MES = r"[A-Za-zÁÉÍÓÚáéíóú]{3,10}\.?"
FECHA_RE = re.compile(
    rf"""\b(?:
        \d{{4}}-\d{{2}}-\d{{2}}
      | \d{{1,2}}\s?[/-]\s?\d{{1,2}}\s?[/-]\s?\d{{4}}
      | \d{{1,2}}\s?/\s?{_MES}\s?/\s?\d{{4}}
      | \d{{1,2}}\s+(?:de\s+)?{_MES}\s+(?:de\s+|del\s+)?\d{{4}}
    )\b""",
    re.IGNORECASE | re.VERBOSE,
)


def find_dates(text: str) -> list[str]:
    """Fechas reconocibles en ``text``, tal como están escritas.

    >>> find_dates("PERIODO 05 AGO 2026 - 05 OCT 2026, límite 20/10/2026")
    ['05 AGO 2026', '05 OCT 2026', '20/10/2026']
    """
    return [m.group(0) for m in FECHA_RE.finditer(text) if parse_date(m.group(0))]


@dataclass(frozen=True)
class _Chunk:
    """Palabras contiguas de un renglón (una columna)."""

    line_index: int
    words: tuple[Word, ...]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def x0(self) -> float:
        return self.words[0].x0

    @property
    def top(self) -> float:
        return min(w.top for w in self.words)

    @property
    def bottom(self) -> float:
        return max(w.bottom for w in self.words)


def _chunks(lines: tuple[Line, ...]) -> list[_Chunk]:
    """Parte cada renglón donde hay un hueco grande: separa columnas que comparten altura."""
    out = []
    for index, line in enumerate(lines):
        height = max(line.bottom - line.top, 1.0)
        current: list[Word] = []
        for word in line.words:
            if current and word.x0 - current[-1].x1 > 3 * height:
                out.append(_Chunk(index, tuple(current)))
                current = []
            current.append(word)
        if current:
            out.append(_Chunk(index, tuple(current)))
    return out


def _parts(text: str) -> list[str]:
    """Piezas de un renglón de domicilio separadas por comas, sin etiquetas."""
    text = ETIQUETAS_DOMICILIO.sub("", text.strip())
    return [p.strip(" .;:") for p in text.split(",") if p.strip(" .;:")]


class ComprobanteParser:
    doc_type = DocType.COMPROBANTE_DOMICILIO
    fields = (*DOMICILIO_FIELDS, "fecha_emision")

    def __init__(self, catalog: SepomexCatalog | None = None) -> None:
        self._catalog = catalog

    @property
    def catalog(self) -> SepomexCatalog | None:
        if self._catalog is None:
            try:
                self._catalog = SepomexCatalog.load_default()
            except SepomexNotAvailableError:
                return None
        return self._catalog

    def parse(self, layout: TextLayout) -> ExtractionResult:
        start = time.perf_counter()
        out: dict[str, ExtractedField] = {k: field(None, 0.0) for k in self.fields}
        out.update(self._address(layout))
        out["fecha_emision"] = self._fecha(layout)
        return ExtractionResult(
            doc_type=DocType.COMPROBANTE_DOMICILIO,
            extractor=EXTRACTOR_NAME,
            fields=out,
            latency_ms=(time.perf_counter() - start) * 1000,
        )

    # ------------------------------------------------------------------
    # Domicilio
    # ------------------------------------------------------------------
    def _find_cp(self, chunks: list[_Chunk]) -> tuple[_Chunk, str] | None:
        catalog = self.catalog
        best: tuple[int, _Chunk, str] | None = None
        for chunk in chunks:
            for match in CP_RE.finditer(chunk.text):
                cp = match.group(1)
                score = 2 * bool(re.match(r"(?i)C\.?\s?P", match.group(0)))
                score += 3 * bool(catalog is not None and cp in catalog)
                if best is None or score > best[0]:
                    best = (score, chunk, cp)
        if best is None or (self.catalog is not None and best[0] < 3):
            return None
        return best[1], best[2]

    def _block(self, chunks: list[_Chunk], anchor: _Chunk) -> list[str]:
        """Renglones de la misma columna que el CP, hasta 4 arriba y 2 abajo, sin saltar un
        hueco vertical grande. Otra columna puede ir intercalada a la misma altura."""
        column = sorted(
            (c for c in chunks if abs(c.x0 - anchor.x0) <= 40), key=lambda c: c.line_index
        )
        at = column.index(anchor)
        block = [anchor]
        for step in (-1, 1):
            i, limit = at + step, 4 if step < 0 else 2
            while 0 <= i < len(column) and abs(i - at) <= limit:
                near = block[0] if step < 0 else block[-1]
                upper, lower = (column[i], near) if step < 0 else (near, column[i])
                if lower.top - upper.bottom > 2.5 * (upper.bottom - upper.top):
                    break
                block.insert(0, column[i]) if step < 0 else block.append(column[i])
                i += step
        return [c.text for c in block]

    def _address(self, layout: TextLayout) -> dict[str, ExtractedField]:
        chunks = _chunks(layout.lines)
        found = self._find_cp(chunks)
        if found is None:
            return {}
        anchor, cp = found
        out: dict[str, ExtractedField] = {"codigo_postal": field(cp, Confianza.ETIQUETADO)}
        parts = [p for line in self._block(chunks, anchor) for p in _parts(line)]
        # Sin el CP ni la palabra "C.P." para comparar piezas con el catálogo.
        clean = [
            re.sub(r"(?i)\bC\.?\s?P\.?\s*\d{5}\b|\b\d{5}\b", "", p).strip(" ,.") for p in parts
        ]

        street_index = None
        for i, part in enumerate(parts):
            street = split_street(part)
            if street and not FECHA_RE.search(part) and "$" not in part:
                street_index = i
                calle, ext, interior = street
                # "Calle X No. 12" con el interior en la pieza siguiente ("Int. 3").
                if not interior and i + 1 < len(parts):
                    nxt = re.match(r"(?i)^INT(?:ERIOR)?\.?\s*(.+)$", parts[i + 1])
                    if nxt:
                        interior = nxt.group(1)
                out["calle"] = field(calle, Confianza.ETIQUETADO)
                out["numero_exterior"] = field(ext, Confianza.ETIQUETADO)
                out["numero_interior"] = field(interior, Confianza.ETIQUETADO)
                break
        candidates = [
            (i, c) for i, c in enumerate(clean) if c and (street_index is None or i > street_index)
        ]
        out.update(self._catalog_fields(cp, candidates))
        return out

    def _catalog_fields(
        self, cp: str, candidates: list[tuple[int, str]]
    ) -> dict[str, ExtractedField]:
        """Colonia, ciudad y estado: la pieza impresa que más se parece al catálogo."""
        catalog = self.catalog
        rows = catalog.lookup(cp) if catalog is not None else ()
        texts = [t for _, t in candidates]
        if not rows:
            return self._without_catalog(texts)
        out: dict[str, ExtractedField] = {}

        def best(targets: set[str], options: list[str]) -> tuple[str | None, float]:
            scored = [
                (max(fuzz.ratio(comparison_key(o), comparison_key(t)) for t in targets), o)
                for o in options
            ]
            if not scored:
                return None, 0.0
            score, option = max(scored)
            return option, score

        colonias = {PREFIJOS_COLONIA.sub("", r.nombre) for r in rows}
        options = [PREFIJOS_COLONIA.sub("", t) for t in texts]
        colonia, score = best(colonias, options)
        out["colonia"] = field(colonia, Confianza.VALIDADO) if score >= 85 else field(None, 0.0)

        ciudades = {r.ciudad or r.municipio for r in rows} | {r.municipio for r in rows}
        # La ciudad y el estado pueden ir en la misma pieza ("TEPIC, NAYARIT" ya está partido;
        # "C.P. 63000 TEPIC" queda como "TEPIC").
        rest = [o for o in options if o != colonia]
        ciudad, score = best(ciudades, rest)
        if score >= 85:
            out["ciudad"] = field(ciudad, Confianza.VALIDADO)
        elif len({r.ciudad or r.municipio for r in rows}) == 1:
            out["ciudad"] = field(rows[0].ciudad or rows[0].municipio, Confianza.DERIVADO)

        estado_catalogo = rows[0].estado
        entidad = find_entidad(estado_catalogo)
        printed = next(
            (o for o in rest if o != ciudad and entidad and find_entidad(o) == entidad), None
        )
        if printed:
            out["estado"] = field(printed, Confianza.VALIDADO)
        else:
            out["estado"] = field(estado_catalogo, Confianza.DERIVADO)
        return out

    def _without_catalog(self, texts: list[str]) -> dict[str, ExtractedField]:
        out: dict[str, ExtractedField] = {}
        colonia = next((t for t in texts if PREFIJOS_COLONIA.match(t)), None)
        if colonia:
            out["colonia"] = field(PREFIJOS_COLONIA.sub("", colonia), Confianza.DUDOSO)
        estados = [t for t in texts if find_entidad(t) is not None]
        if estados:
            out["estado"] = field(estados[-1], Confianza.DUDOSO)
            i = texts.index(estados[-1])
            if i > 0 and texts[i - 1] != colonia:
                out["ciudad"] = field(texts[i - 1], Confianza.DUDOSO)
        return out

    # ------------------------------------------------------------------
    # Fecha de emisión
    # ------------------------------------------------------------------
    def _fecha(self, layout: TextLayout) -> ExtractedField:
        lines = [comparison_key(line.text) for line in layout.lines]
        raw = [line.text for line in layout.lines]
        for i, key in enumerate(lines):
            if any(label in key for label in ETIQUETAS_FECHA):
                # La fecha en el mismo renglón, después de la etiqueta, o en el de abajo.
                for text in (raw[i], raw[i + 1] if i + 1 < len(raw) else ""):
                    dates = find_dates(text)
                    if dates:
                        return field(
                            dates[-1] if text is raw[i] else dates[0], Confianza.ETIQUETADO
                        )
        candidates = [
            d
            for i, text in enumerate(raw)
            if not any(word in lines[i] for word in NO_ES_EMISION)
            for d in find_dates(text)
        ]
        if not candidates:
            return field(None, 0.0)
        latest = max(candidates, key=lambda d: parse_date(d))
        return field(latest, Confianza.DUDOSO)
