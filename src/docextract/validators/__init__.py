"""Validadores: CURP, RFC, nombres, domicilio (SEPOMEX) y comprobante de domicilio.

Son funciones puras: reciben valores y devuelven datos derivados y advertencias
(``ExtractionWarning``) cuyos mensajes nunca incluyen datos personales. Combinar las
advertencias de varios documentos en el formulario final le corresponde a la fusión.
"""

from docextract.validators.comprobante import check_comprobante_age
from docextract.validators.curp import (
    CurpInfo,
    CurpValidation,
    build_curp,
    check_curp_consistency,
    validate_curp,
)
from docextract.validators.names import PersonName, compare_names
from docextract.validators.rfc import (
    RfcValidation,
    build_rfc,
    check_rfc_against_curp,
    validate_rfc,
)
from docextract.validators.sepomex import AddressValidation, SepomexCatalog, validate_address

__all__ = [
    "AddressValidation",
    "CurpInfo",
    "CurpValidation",
    "PersonName",
    "RfcValidation",
    "SepomexCatalog",
    "build_curp",
    "build_rfc",
    "check_comprobante_age",
    "check_curp_consistency",
    "check_rfc_against_curp",
    "compare_names",
    "validate_address",
    "validate_curp",
    "validate_rfc",
]
