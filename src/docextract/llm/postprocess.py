"""Del JSON del modelo a ``ExtractedField``: los mismos validadores que las reglas.

El modelo no da una confianza calibrada. Cada valor parte de :attr:`Confianza.MODELO` y se
ajusta con lo que sí se puede verificar, igual que en los parsers de reglas:

* **CURP y RFC:** dígito verificador. Si no pasa, se intenta la corrección por estructura
  (:mod:`docextract.repair`); si tampoco, el valor queda con ``INVALIDO`` y su advertencia.
* **Nombre y apellidos:** contra las letras de la CURP del mismo documento.
* **Fecha de nacimiento, sexo, entidad y nacionalidad:** contra la CURP o derivados de ella
  si no están impresos (las mismas funciones que el parser de la CURP).
* **Código postal:** 5 dígitos y, con el catálogo de SEPOMEX, corrección de un dígito con
  el municipio o el estado impresos.
* **Estado y fechas:** que se reconozcan como entidad o fecha.
"""

from __future__ import annotations

from docextract.entidades import find_entidad
from docextract.normalize import clean_identifier, normalize_codigo_postal, parse_date
from docextract.parsers.address import default_catalog, repair_cp
from docextract.parsers.base import Confianza, field, find_curp, find_rfc
from docextract.parsers.curp import (
    entidad_vs_curp,
    fecha_vs_curp,
    nacionalidad_vs_curp,
    sexo_vs_curp,
)
from docextract.schemas import DocType, ExtractedField, WarningCode
from docextract.validators._common import make_warning
from docextract.validators.curp import check_curp_consistency
from docextract.validators.rfc import check_rfc_against_curp

__all__ = ["CONFIANZA_MODELO", "build_fields"]

CONFIANZA_MODELO = 0.85
"""Valor leído por el modelo que no se puede verificar. Provisional, como las demás
confianzas: se calibra con la fusión (fase 8)."""

NOMBRE_FIELDS = ("nombre", "apellido_paterno", "apellido_materno")

CATALOGO_DESCARGADO = object()
"""Valor por defecto de ``catalog``: el catálogo de SEPOMEX descargado, si existe."""


def _curp(doc_type: DocType, raw: str | None):
    if not raw:
        return field(None, 0.0), None, None
    curp, info, confidence = find_curp(clean_identifier(raw), ocr=True)
    if curp is None:
        warning = make_warning(
            WarningCode.CURP_FORMATO_INVALIDO,
            "La CURP no tiene el formato oficial.",
            fields=("curp",),
            docs=(doc_type,),
        )
        return field(raw, Confianza.INVALIDO, [warning]), None, None
    warnings = []
    if confidence <= Confianza.INVALIDO:
        warnings.append(
            make_warning(
                WarningCode.CURP_DIGITO_VERIFICADOR_INVALIDO,
                "El dígito verificador de la CURP no corresponde.",
                fields=("curp",),
                docs=(doc_type,),
            )
        )
    return field(curp, confidence, warnings), curp, info


def _rfc(doc_type: DocType, raw: str | None, curp: str | None) -> ExtractedField:
    if not raw:
        return field(None, 0.0)
    rfc, confidence = find_rfc(clean_identifier(raw), ocr=True)
    if rfc is None:
        warning = make_warning(
            WarningCode.RFC_FORMATO_INVALIDO,
            "El RFC no tiene el formato de persona física.",
            fields=("rfc",),
            docs=(doc_type,),
        )
        return field(raw, Confianza.INVALIDO, [warning])
    warnings = check_rfc_against_curp(rfc, curp, docs=(doc_type,)) if curp else []
    return field(rfc, confidence, warnings)


def build_fields(
    doc_type: DocType, raw: dict[str, str | None], *, catalog=CATALOGO_DESCARGADO
) -> dict[str, ExtractedField]:
    """Los campos validados. ``catalog``: SEPOMEX (``None`` = sin catálogo)."""
    out: dict[str, ExtractedField] = {}
    info = curp = None
    if "curp" in raw:
        out["curp"], curp, info = _curp(doc_type, raw["curp"])
    if "rfc" in raw:
        out["rfc"] = _rfc(doc_type, raw["rfc"], curp)

    if "nombre" in raw:
        nombres = {k: raw.get(k) for k in NOMBRE_FIELDS}
        confidence, warnings = CONFIANZA_MODELO, []
        # La CURP solo se compara con los tres (el segundo apellido puede ser "").
        comparable = nombres["nombre"] and nombres["apellido_paterno"]
        if info is not None and comparable and nombres["apellido_materno"] is not None:
            warnings = check_curp_consistency(
                info,
                nombre=nombres["nombre"],
                apellido_paterno=nombres["apellido_paterno"],
                apellido_materno=nombres["apellido_materno"],
                docs=(doc_type,),
            )
            confidence = Confianza.INCONSISTENTE if warnings else Confianza.VALIDADO
        for name, value in nombres.items():
            out[name] = field(value, confidence if value is not None else 0.0, warnings)

    # Lo que también dice la CURP. Un valor impreso que coincide sube a VALIDADO; uno que
    # no está impreso se deriva de la CURP (DERIVADO).
    if "fecha_nacimiento" in raw:
        out["fecha_nacimiento"] = fecha_vs_curp(raw["fecha_nacimiento"], info, (doc_type,))
    if "sexo" in raw:
        out["sexo"] = sexo_vs_curp(raw["sexo"], info)
    if "entidad_nacimiento" in raw:
        out["entidad_nacimiento"] = entidad_vs_curp(raw["entidad_nacimiento"], info)
    if "nacionalidad" in raw:
        out["nacionalidad"] = nacionalidad_vs_curp(raw["nacionalidad"], info)
    # Las funciones de la CURP dan ETIQUETADO a un valor impreso sin verificar; el del
    # modelo no tiene etiqueta que lo respalde.
    for name in ("fecha_nacimiento", "sexo", "entidad_nacimiento", "nacionalidad"):
        if name in out and out[name].confidence == Confianza.ETIQUETADO:
            out[name] = out[name].model_copy(update={"confidence": CONFIANZA_MODELO})

    # Domicilio
    for name in ("calle", "numero_exterior", "numero_interior", "colonia", "ciudad", "municipio"):
        if name in raw:
            value = raw[name]
            out[name] = field(value, CONFIANZA_MODELO if value is not None else 0.0)
    if "estado" in raw:
        estado = raw["estado"]
        ok = estado is not None and find_entidad(estado) is not None
        out["estado"] = field(estado, CONFIANZA_MODELO if ok else Confianza.DUDOSO)
    if "codigo_postal" in raw:
        out["codigo_postal"] = _codigo_postal(raw, catalog)

    if "fecha_emision" in raw:
        fecha = raw["fecha_emision"]
        ok = fecha is not None and parse_date(fecha, allow_two_digit_year=True) is not None
        out["fecha_emision"] = field(fecha, CONFIANZA_MODELO if ok else Confianza.DUDOSO)

    # Ningún campo pedido se queda fuera (None = no se encontró).
    for name, value in raw.items():
        out.setdefault(name, field(value, CONFIANZA_MODELO if value is not None else 0.0))
    return out


def _codigo_postal(raw: dict[str, str | None], catalog) -> ExtractedField:
    leido = raw.get("codigo_postal")
    if not leido:
        return field(None, 0.0)
    cp = normalize_codigo_postal(leido)
    if cp is None:
        return field(leido, Confianza.INVALIDO)
    if catalog is CATALOGO_DESCARGADO:
        catalog = default_catalog()
    municipio = raw.get("municipio") or raw.get("ciudad")
    corregido = repair_cp(cp, catalog, municipio=municipio, estado=raw.get("estado"))
    if corregido != cp:
        return field(corregido, Confianza.REPARADO)
    return field(cp, CONFIANZA_MODELO)
