"""Parser de la Constancia de Situación Fiscal con capa de texto.

RFC y CURP se validan con sus dígitos verificadores; el nombre se compara contra la CURP; el
domicilio fiscal se lee por etiquetas (la constancia lo trae en campos separados, a dos
columnas). La calle se arma con el tipo y el nombre de la vialidad.
"""

import time

from docextract.entidades import find_entidad
from docextract.layout import TextLayout
from docextract.normalize import normalize_codigo_postal
from docextract.parsers.base import EXTRACTOR_NAME, Confianza, field, find_curp, find_rfc
from docextract.schemas import DocType, ExtractedField, ExtractionResult
from docextract.validators.curp import check_curp_consistency
from docextract.validators.rfc import check_rfc_against_curp

__all__ = ["CsfParser"]

ETIQUETAS: dict[str, tuple[str, ...]] = {
    "rfc": ("RFC",),
    "curp": ("CURP",),
    "nombre": ("Nombre (s)", "Nombre(s)", "Nombres"),
    "apellido_paterno": ("Primer Apellido",),
    "apellido_materno": ("Segundo Apellido",),
    "codigo_postal": ("Código Postal",),
    "tipo_vialidad": ("Tipo de Vialidad",),
    "nombre_vialidad": ("Nombre de Vialidad",),
    "numero_exterior": ("Número Exterior",),
    "numero_interior": ("Número Interior",),
    "colonia": ("Nombre de la Colonia",),
    "ciudad": ("Nombre de la Localidad",),
    "municipio": ("Nombre del Municipio o Demarcación Territorial",),
    "estado": ("Nombre de la Entidad Federativa",),
}
OTRAS = (
    "Entre Calle", "Y Calle", "Fecha inicio de operaciones", "Estatus en el padrón",
    "Fecha de último cambio de estado", "Nombre Comercial", "Correo Electrónico",
    "Tel. Fijo Lada", "Número", "Tel. Móvil Lada", "Estado de la conexión", "Régimen",
    "Fecha Inicio", "Fecha Fin", "idCIF", "Lugar y Fecha de Emisión",
    "Nombre, denominación o razón social", "Registro Federal de Contribuyentes",
)  # fmt: skip
VOCABULARIO = tuple(label for labels in ETIQUETAS.values() for label in labels) + OTRAS

NOMBRE_FIELDS = ("nombre", "apellido_paterno", "apellido_materno")
DOMICILIO_FIELDS = (
    "tipo_vialidad",
    "nombre_vialidad",
    "numero_exterior",
    "numero_interior",
    "colonia",
    "ciudad",
    "municipio",
)


class CsfParser:
    doc_type = DocType.CSF
    fields = (
        "rfc",
        "curp",
        "nombre",
        "apellido_paterno",
        "apellido_materno",
        "codigo_postal",
        "calle",
        "numero_exterior",
        "numero_interior",
        "colonia",
        "ciudad",
        "municipio",
        "estado",
    )

    def parse(self, layout: TextLayout) -> ExtractionResult:
        start = time.perf_counter()
        out: dict[str, ExtractedField] = {}

        def get(name: str) -> str | None:
            return layout.value(ETIQUETAS[name], VOCABULARIO)

        # Identificadores
        rfc, rfc_confidence = find_rfc(layout.text, prefer=get("rfc"))
        curp_etiquetada = get("curp") or ""
        curp, info, curp_confidence = find_curp(f"{curp_etiquetada}\n{layout.text}")
        rfc_warnings = []
        if rfc and curp:
            rfc_warnings = check_rfc_against_curp(rfc, curp, docs=(DocType.CSF,))
        out["rfc"] = field(rfc, rfc_confidence, rfc_warnings)
        out["curp"] = field(curp, curp_confidence)

        # Nombre
        nombres = {name: get(name) for name in NOMBRE_FIELDS}
        confidence, warnings = Confianza.ETIQUETADO, []
        if info is not None and nombres["nombre"] and nombres["apellido_paterno"]:
            warnings = check_curp_consistency(
                info,
                nombre=nombres["nombre"],
                apellido_paterno=nombres["apellido_paterno"],
                apellido_materno=nombres["apellido_materno"],
                docs=(DocType.CSF,),
            )
            confidence = Confianza.INCONSISTENTE if warnings else Confianza.VALIDADO
        for name, value in nombres.items():
            out[name] = field(value, confidence, warnings)

        # Domicilio fiscal
        cp = get("codigo_postal")
        cp_ok = normalize_codigo_postal(cp) is not None
        out["codigo_postal"] = field(cp, Confianza.ETIQUETADO if cp_ok else Confianza.INVALIDO)
        valores = {name: get(name) for name in DOMICILIO_FIELDS}
        for name in ("numero_exterior", "numero_interior", "colonia", "ciudad", "municipio"):
            out[name] = field(valores[name], Confianza.ETIQUETADO)
        tipo, nombre_vialidad = valores["tipo_vialidad"], valores["nombre_vialidad"]
        calle = " ".join(p for p in (tipo, nombre_vialidad) if p) or None
        out["calle"] = field(calle, Confianza.ETIQUETADO)
        out["tipo_vialidad"] = field(tipo, Confianza.ETIQUETADO)
        out["nombre_vialidad"] = field(nombre_vialidad, Confianza.ETIQUETADO)
        estado = get("estado")
        estado_ok = find_entidad(estado) is not None
        out["estado"] = field(estado, Confianza.ETIQUETADO if estado_ok else Confianza.DUDOSO)

        # Un valor que no se encontró no lleva advertencia aquí: la fusión agrega
        # CAMPO_NO_ENCONTRADO a todo campo sin valor.
        return ExtractionResult(
            doc_type=DocType.CSF,
            extractor=EXTRACTOR_NAME,
            fields=out,
            latency_ms=(time.perf_counter() - start) * 1000,
        )
