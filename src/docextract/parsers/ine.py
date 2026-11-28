"""Parser de la credencial para votar (INE), sobre texto de OCR o capa de texto.

La credencial lleva etiquetas pequeñas ("NOMBRE", "DOMICILIO") con el valor en los renglones
de abajo, y el resto en pares etiqueta-valor ("CURP", "FECHA DE NACIMIENTO", "SEXO"):

* **Nombre:** los renglones entre "NOMBRE" y "DOMICILIO": primer apellido, segundo apellido
  (si hay) y nombre(s). Se confirma con las letras de la CURP; si no cuadra, se divide el
  nombre completo con la CURP (``split_full_name``).
* **Domicilio:** los renglones entre "DOMICILIO" y la siguiente etiqueta: calle y números,
  colonia y código postal, municipio y estado. Con las abreviaturas de la credencial ("C",
  "COL", "NAY.") tal como vienen; la normalización y SEPOMEX van después.
* **CURP** en todo el texto, con corrección de OCR. Fecha y sexo por etiqueta; si faltan,
  se derivan de la CURP.
"""

import re
import time

from docextract.layout import Line, TextLayout
from docextract.normalize import comparison_key, parse_date
from docextract.parsers.address import (
    CP_RE,
    default_catalog,
    repair_cp,
    split_city_state,
    split_colonia_cp,
    split_street,
)
from docextract.parsers.base import EXTRACTOR_NAME, Confianza, field, find_curp, split_full_name
from docextract.schemas import DocType, ExtractedField, ExtractionResult
from docextract.validators.curp import CurpInfo, check_curp_consistency

__all__ = ["IneParser"]

ETIQUETAS = (
    "NOMBRE", "DOMICILIO", "CLAVE DE ELECTOR", "CURP", "FECHA DE NACIMIENTO", "SEXO",
    "AÑO DE REGISTRO", "SECCION", "VIGENCIA",
)  # fmt: skip
"""Solo etiquetas que no pueden abrir un renglón de domicilio: "ESTADO" o "MUNICIPIO" sí
podrían (un municipio que empiece así), y cortarían el bloque."""
NOMBRE_FIELDS = ("nombre", "apellido_paterno", "apellido_materno")
DOMICILIO_FIELDS = (
    "calle", "numero_exterior", "numero_interior", "colonia", "codigo_postal", "ciudad", "estado",
)  # fmt: skip
FECHA_RE = re.compile(r"\b(\d{2})\s?/\s?(\d{2})\s?/\s?(\d{4})\b")
ANCHO_COLUMNA = 0.33
"""Ancho de la columna de nombre y domicilio, como fracción del ancho de la página: deja
fuera lo que va a la derecha en el mismo renglón (p. ej. "SEXO H")."""


def _column(line: Line, left: float) -> str:
    """Las palabras del renglón desde ``left`` (deja fuera lo que está a la izquierda)."""
    return " ".join(w.text for w in line.words if w.x0 >= left)


_SOLO_LETRAS = re.compile(r"^[A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑ' .-]*$")


def _blocks_sin_etiquetas(layout: TextLayout) -> tuple[list[str], list[str]]:
    """Nombre y domicilio cuando el OCR perdió las etiquetas chicas (fotos).

    Ancla: el primer renglón con forma de calle y número seguido, a 1 o 2 renglones, de uno
    con código postal. El nombre son los renglones de solo letras justo arriba (hasta 3).
    """
    lines = layout.lines
    labeled = {s.line_index for s in layout.segments(ETIQUETAS)}
    for i, line in enumerate(lines):
        if i in labeled or not split_street(line.text):
            continue
        if not any(CP_RE.search(lines[j].text) for j in range(i + 1, min(i + 3, len(lines)))):
            continue
        left = line.words[0].x0 - 15
        address = [
            _column(lines[j], left) for j in range(i, min(i + 3, len(lines))) if j not in labeled
        ]
        names: list[str] = []
        for j in range(i - 1, max(i - 4, -1), -1):
            text = _column(lines[j], left)
            if j in labeled or not _SOLO_LETRAS.match(text) or "CREDENCIAL" in text.upper():
                break
            names.insert(0, text)
        return names, address
    return [], []


def _block(layout: TextLayout, label: str, max_lines: int) -> list[str]:
    """Los renglones que siguen a ``label`` hasta el siguiente renglón con etiqueta."""
    segments = layout.segments(ETIQUETAS)
    start = next((s for s in segments if s.label == comparison_key(label)), None)
    if start is None:
        return []
    with_labels = {s.line_index for s in segments}
    right = start.x0 + ANCHO_COLUMNA * (layout.width or 612)
    out: list[str] = []
    for index in range(start.line_index + 1, len(layout.lines)):
        if index in with_labels or len(out) == max_lines:
            break
        line: Line = layout.lines[index]
        words = [w.text for w in line.words if start.x0 - 15 <= w.x0 < right]
        if words:
            out.append(" ".join(words))
    return out


class IneParser:
    doc_type = DocType.INE
    fields = (
        "curp", *NOMBRE_FIELDS, "fecha_nacimiento", "sexo", *DOMICILIO_FIELDS,
    )  # fmt: skip

    def parse(self, layout: TextLayout) -> ExtractionResult:
        start = time.perf_counter()
        out: dict[str, ExtractedField] = {}
        curp, info, curp_confidence = find_curp(layout.text, ocr=layout.ocr)
        out["curp"] = field(curp, curp_confidence)
        names, address = _block(layout, "NOMBRE", 3), _block(layout, "DOMICILIO", 4)
        if not names or not address:
            fallback_names, fallback_address = _blocks_sin_etiquetas(layout)
            names, address = names or fallback_names, address or fallback_address
        out.update(self._names(names, curp, info))
        out.update(self._address(address))
        if layout.ocr and out["codigo_postal"].value:
            cp = out["codigo_postal"].value
            corregido = repair_cp(
                cp, default_catalog(), municipio=out["ciudad"].value, estado=out["estado"].value
            )
            if corregido != cp:
                out["codigo_postal"] = field(corregido, Confianza.REPARADO)

        fecha = layout.value(("FECHA DE NACIMIENTO",), ETIQUETAS)
        match = FECHA_RE.search(fecha or "") or FECHA_RE.search(layout.text)
        if match:
            impresa = "/".join(match.groups())
            ok = info is not None and parse_date(impresa) == info.fecha_nacimiento
            out["fecha_nacimiento"] = field(
                impresa, Confianza.VALIDADO if ok else Confianza.ETIQUETADO
            )
        elif info is not None:
            out["fecha_nacimiento"] = field(info.fecha_nacimiento.isoformat(), Confianza.DERIVADO)
        else:
            out["fecha_nacimiento"] = field(None, 0.0)

        sexo = (layout.value(("SEXO",), ETIQUETAS, below=False) or "").split()
        if sexo and sexo[0].upper() in ("H", "M", "X"):
            ok = info is not None and sexo[0].upper() == info.sexo
            out["sexo"] = field(sexo[0].upper(), Confianza.VALIDADO if ok else Confianza.ETIQUETADO)
        elif info is not None:
            out["sexo"] = field(info.sexo, Confianza.DERIVADO)
        else:
            out["sexo"] = field(None, 0.0)

        return ExtractionResult(
            doc_type=DocType.INE,
            extractor=EXTRACTOR_NAME,
            fields=out,
            latency_ms=(time.perf_counter() - start) * 1000,
        )

    # ------------------------------------------------------------------
    def _names(
        self, lines: list[str], curp: str | None, info: CurpInfo | None
    ) -> dict[str, ExtractedField]:
        if len(lines) == 3:
            paterno, materno, nombre = lines
        elif len(lines) == 2:
            (paterno, nombre), materno = lines, ""
        else:
            return {k: field(None, 0.0) for k in NOMBRE_FIELDS}
        values = {"nombre": nombre, "apellido_paterno": paterno, "apellido_materno": materno}
        if info is None:
            return {k: field(v, Confianza.ETIQUETADO) for k, v in values.items()}
        inconsistente = check_curp_consistency(
            info, nombre=nombre, apellido_paterno=paterno, apellido_materno=materno
        )
        if not inconsistente:
            return {k: field(v, Confianza.VALIDADO) for k, v in values.items()}
        # Un renglón mal partido o de más: se divide el nombre completo con la CURP.
        split, ambiguo = split_full_name(" ".join(lines), curp or "")
        if split:
            confidence = Confianza.DUDOSO if ambiguo else Confianza.VALIDADO
            return {k: field(v, confidence) for k, v in zip(NOMBRE_FIELDS, split, strict=True)}
        return {k: field(v, Confianza.INCONSISTENTE, inconsistente) for k, v in values.items()}

    def _address(self, lines: list[str]) -> dict[str, ExtractedField]:
        out = {k: field(None, 0.0) for k in DOMICILIO_FIELDS}
        if not lines:
            return out
        street = split_street(lines[0])
        if street:
            for name, value in zip(
                ("calle", "numero_exterior", "numero_interior"), street, strict=True
            ):
                out[name] = field(value, Confianza.ETIQUETADO)
        cp_line = next((i for i, line in enumerate(lines[1:], 1) if CP_RE.search(line)), None)
        if cp_line is not None:
            colonia, cp = split_colonia_cp(lines[cp_line])
            out["colonia"] = field(colonia or None, Confianza.ETIQUETADO)
            out["codigo_postal"] = field(cp, Confianza.ETIQUETADO)
            rest = lines[cp_line + 1 :]
        else:
            rest = lines[2:]
            if len(lines) > 1:
                out["colonia"] = field(split_colonia_cp(lines[1])[0], Confianza.DUDOSO)
        if rest:
            ciudad, estado = split_city_state(rest[0])
            out["ciudad"] = field(ciudad or None, Confianza.ETIQUETADO)
            out["estado"] = field(estado or None, Confianza.ETIQUETADO)
        return out
