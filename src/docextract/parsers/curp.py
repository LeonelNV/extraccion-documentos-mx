"""Parser de la constancia de CURP con capa de texto.

Estrategia, de lo más confiable a lo menos:

1. La CURP se busca en todo el texto y se valida con el dígito verificador.
2. Nombre y apellidos por sus etiquetas. Si el documento trae el nombre completo en una
   sola línea, se divide con la CURP (``split_full_name``), así funciona aunque el
   formato real no tenga campos separados.
3. Fecha, sexo y entidad por sus etiquetas; si no están impresos, se derivan de la CURP
   con menor confianza.

Cada valor se devuelve tal como está impreso. Si contradice a la CURP, baja su confianza y
lleva la advertencia ``CURP_DATOS_NO_COINCIDEN``.
"""

import time
from collections.abc import Callable

from docextract.entidades import por_clave_curp
from docextract.layout import TextLayout
from docextract.normalize import comparison_key, parse_date
from docextract.parsers.base import (
    EXTRACTOR_NAME,
    Confianza,
    field,
    find_curp,
    split_full_name,
)
from docextract.schemas import DocType, ExtractedField, ExtractionResult, WarningCode
from docextract.validators._common import make_warning
from docextract.validators.curp import CurpInfo, check_curp_consistency

__all__ = ["CurpParser"]

ETIQUETAS: dict[str, tuple[str, ...]] = {
    "nombre": ("Nombre(s)", "Nombres", "Nombre (s)"),
    "apellido_paterno": ("Primer apellido", "Apellido paterno"),
    "apellido_materno": ("Segundo apellido", "Apellido materno"),
    "nombre_completo": ("Nombre", "Nombre completo"),
    "sexo": ("Sexo",),
    "fecha_nacimiento": ("Fecha de nacimiento",),
    "entidad_nacimiento": ("Entidad de nacimiento", "Lugar de nacimiento"),
    "nacionalidad": ("Nacionalidad",),
}
# Etiquetas que solo sirven para cortar valores.
OTRAS = (
    "Clave", "CURP", "Folio", "Fecha de emisión", "Fecha de inscripción", "Fecha de registro",
    "Entidad de registro", "Municipio de registro", "Año de registro", "Libro", "Foja", "Acta",
)  # fmt: skip
VOCABULARIO = tuple(label for labels in ETIQUETAS.values() for label in labels) + OTRAS

SEXOS = {"H": "H", "HOMBRE": "H", "MASCULINO": "H", "M": "M", "MUJER": "M", "FEMENINO": "M"}
SEXOS |= {"X": "X", "NO BINARIO": "X", "NB": "X"}

NOMBRE_FIELDS = ("nombre", "apellido_paterno", "apellido_materno")


def _sexo_codigo(texto: str) -> str | None:
    return SEXOS.get(comparison_key(texto))


class CurpParser:
    doc_type = DocType.CURP
    fields = (
        "curp",
        "nombre",
        "apellido_paterno",
        "apellido_materno",
        "fecha_nacimiento",
        "sexo",
        "entidad_nacimiento",
        "nacionalidad",
    )

    def parse(self, layout: TextLayout) -> ExtractionResult:
        start = time.perf_counter()
        out: dict[str, ExtractedField] = {}

        curp, info, curp_confidence = find_curp(layout.text)
        warnings = []
        if curp and curp_confidence < Confianza.VALIDADO:
            warnings.append(
                make_warning(
                    WarningCode.CURP_DIGITO_VERIFICADOR_INVALIDO,
                    "El dígito verificador de la CURP no corresponde.",
                    fields=("curp",),
                    docs=(DocType.CURP,),
                )
            )
        out["curp"] = field(curp, curp_confidence, warnings)

        def get(name: str) -> str | None:
            return layout.value(ETIQUETAS[name], VOCABULARIO)

        out.update(self._names(get, curp, info))
        out["fecha_nacimiento"] = self._fecha(get("fecha_nacimiento"), info)
        out["sexo"] = self._sexo(get("sexo"), info)
        out["entidad_nacimiento"] = self._entidad(get("entidad_nacimiento"), info)
        nacionalidad = get("nacionalidad")
        out["nacionalidad"] = field(nacionalidad or None, Confianza.ETIQUETADO)

        return ExtractionResult(
            doc_type=DocType.CURP,
            extractor=EXTRACTOR_NAME,
            fields=out,
            latency_ms=(time.perf_counter() - start) * 1000,
        )

    # ------------------------------------------------------------------
    def _names(
        self, get: Callable[[str], str | None], curp: str | None, info: CurpInfo | None
    ) -> dict[str, ExtractedField]:
        separados = {name: get(name) for name in NOMBRE_FIELDS}
        confidence = Confianza.ETIQUETADO
        if separados["nombre"] is None and separados["apellido_paterno"] is None:
            completo = get("nombre_completo")
            if completo and curp:
                split, ambiguo = split_full_name(completo, curp)
                if split:
                    separados = dict(zip(NOMBRE_FIELDS, split, strict=True))
                    confidence = Confianza.DUDOSO if ambiguo else Confianza.VALIDADO
                    return {k: field(v, confidence) for k, v in separados.items()}
            return {k: field(None, 0.0) for k in NOMBRE_FIELDS}

        warnings = []
        if info is not None and separados["nombre"] and separados["apellido_paterno"]:
            consistency = check_curp_consistency(
                info,
                nombre=separados["nombre"],
                apellido_paterno=separados["apellido_paterno"],
                apellido_materno=separados["apellido_materno"],
            )
            if consistency:
                confidence, warnings = Confianza.INCONSISTENTE, consistency
            else:
                confidence = Confianza.VALIDADO
        return {k: field(v, confidence, warnings) for k, v in separados.items()}

    def _fecha(self, impresa: str | None, info: CurpInfo | None) -> ExtractedField:
        if impresa:
            fecha = parse_date(impresa)
            if info is None or fecha is None:
                return field(impresa, Confianza.ETIQUETADO if fecha else Confianza.DUDOSO)
            if fecha == info.fecha_nacimiento:
                return field(impresa, Confianza.VALIDADO)
            return field(
                impresa,
                Confianza.INCONSISTENTE,
                [
                    make_warning(
                        WarningCode.CURP_DATOS_NO_COINCIDEN,
                        "La fecha de nacimiento impresa no coincide con la de la CURP.",
                        fields=("fecha_nacimiento", "curp"),
                        docs=(DocType.CURP,),
                    )
                ],
            )
        if info is not None:
            return field(info.fecha_nacimiento.isoformat(), Confianza.DERIVADO)
        return field(None, 0.0)

    def _sexo(self, impreso: str | None, info: CurpInfo | None) -> ExtractedField:
        if impreso:
            codigo = _sexo_codigo(impreso)
            if info is None or codigo is None:
                return field(impreso, Confianza.ETIQUETADO if codigo else Confianza.DUDOSO)
            confidence = Confianza.VALIDADO if codigo == info.sexo else Confianza.INCONSISTENTE
            return field(impreso, confidence)
        if info is not None:
            return field(info.sexo, Confianza.DERIVADO)
        return field(None, 0.0)

    def _entidad(self, impresa: str | None, info: CurpInfo | None) -> ExtractedField:
        if impresa:
            return field(impresa, Confianza.ETIQUETADO)
        if info is not None:
            entidad = por_clave_curp(info.clave_entidad)
            nombre = entidad.nombre if entidad else "NACIDO EN EL EXTRANJERO"
            return field(nombre, Confianza.DERIVADO)
        return field(None, 0.0)
