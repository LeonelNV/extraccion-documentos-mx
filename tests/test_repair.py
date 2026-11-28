"""Corrección de CURP y RFC leídos por OCR. Las claves las genera el código."""

from datetime import date

from docextract.layout import TextLayout, Word
from docextract.parsers.base import Confianza, find_curp, find_rfc
from docextract.repair import CURP_PATTERN, candidate_strings, repair
from docextract.validators.curp import build_curp
from docextract.validators.rfc import build_rfc

CURP = build_curp(
    nombre="Laura", apellido_paterno="Rico", apellido_materno="Cano",
    fecha_nacimiento=date(2003, 1, 1), sexo="M", clave_entidad="NT",
)  # fmt: skip
CURP_1999 = build_curp(
    nombre="Fernando", apellido_paterno="Galván", apellido_materno="Coronado",
    fecha_nacimiento=date(1999, 12, 14), sexo="H", clave_entidad="NT",
)  # fmt: skip
RFC = build_rfc(
    nombre="Laura", apellido_paterno="Rico", apellido_materno="Cano",
    fecha_nacimiento=date(2003, 1, 1),
)  # fmt: skip


def _ocr(text: str) -> str:
    """Error típico del OCR: los ceros de la fecha leídos como O (3 cambios; la reparación
    acepta hasta 4)."""
    return text[:4] + text[4:10].replace("0", "O") + text[10:]


def test_repair_respeta_letras_y_digitos() -> None:
    variants = [v for v, _ in repair(_ocr(CURP), CURP_PATTERN)]
    assert variants[0] == CURP
    assert repair("CORTA", CURP_PATTERN) == []


def test_candidatos_partidos_pegados_y_con_un_caracter_de_mas() -> None:
    lineas = [f"CURP{CURP}", f"{CURP[:9]} {CURP[9:]}", CURP[:5] + "X" + CURP[5:]]
    found = {c for c, _ in candidate_strings(lineas, 18)}
    assert CURP in found


def test_find_curp_corrige_solo_con_ocr() -> None:
    texto = f"Clave:\n{_ocr(CURP)}\n"
    assert find_curp(texto)[0] != CURP
    curp, info, confidence = find_curp(texto, ocr=True)
    assert curp == CURP
    assert info is not None
    assert confidence == Confianza.REPARADO


def test_o_y_cero_en_el_diferenciador_se_resuelve_por_la_fecha() -> None:
    # El dígito verificador no distingue O de 0 en la posición 17; con O la persona habría
    # nacido en 2099.
    leida = CURP_1999[:16] + "O" + CURP_1999[17]
    assert find_curp(leida, ocr=True)[0] == CURP_1999


def test_rfc_con_ocr_no_toma_el_inicio_de_la_curp() -> None:
    assert find_rfc(f"CURP: {_ocr(CURP)}", ocr=True) == (None, 0.0)
    rfc, confidence = find_rfc(f"RFC: {_ocr(RFC)}", ocr=True)
    assert rfc == RFC
    assert confidence == Confianza.REPARADO


def test_etiquetas_con_una_letra_cambiada_solo_con_ocr() -> None:
    words = [Word("NOWBRE", 50, 90, 10, 20), Word("JUAN", 50, 80, 30, 40)]
    assert TextLayout(words).value(("NOMBRE",), ()) is None
    assert TextLayout(words, ocr=True).value(("NOMBRE",), ()) == "JUAN"
    # Una letra de más o de menos no cuenta: "Nombre" no es la etiqueta "Nombres".
    words = [Word("Nombre", 50, 90, 10, 20), Word("JUAN", 50, 80, 30, 40)]
    assert TextLayout(words, ocr=True).value(("Nombres",), ()) is None
