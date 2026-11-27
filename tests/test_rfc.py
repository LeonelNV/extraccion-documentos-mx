"""Pruebas del RFC de persona física.

Todos los RFCs de este archivo los genera ``build_rfc`` a partir de nombres y fechas
inventados. La única excepción son los RFC genéricos del SAT (``XAXX010101000`` y
``XEXX010101000``), que no pertenecen a ninguna persona.
"""

from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from docextract.schemas import WarningCode
from docextract.validators.curp import build_curp
from docextract.validators.rfc import (
    RFC_PF_RE,
    build_rfc,
    check_rfc_against_curp,
    rfc_check_digit,
    validate_rfc,
)

FECHA = date(1991, 4, 7)


def _rfc(nombre: str, paterno: str, materno: str | None, fecha: date = FECHA) -> str:
    return build_rfc(
        nombre=nombre, apellido_paterno=paterno, apellido_materno=materno, fecha_nacimiento=fecha
    )


def _curp(nombre: str, paterno: str, materno: str | None, fecha: date = FECHA) -> str:
    return build_curp(
        nombre=nombre,
        apellido_paterno=paterno,
        apellido_materno=materno,
        fecha_nacimiento=fecha,
        sexo="M",
        clave_entidad="NT",
    )


def _codes(warnings: object) -> list[WarningCode]:
    return [w.code for w in warnings]  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Letras del nombre (reglas del SAT)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("nombre", "paterno", "materno", "letras"),
    [
        ("Laura", "Gómez", "Ruiz", "GORL"),
        # Un solo apellido: dos letras del apellido y dos del nombre.
        ("Hugo", "Barrera", "", "BAHU"),
        ("Hugo", "Barrera", None, "BAHU"),
        ("Hugo", "", "Barrera", "BAHU"),  # el único apellido viene como materno
        # Apellido paterno de una o dos letras: inicial de cada apellido y dos del nombre.
        ("Ana", "Ow", "Lima", "OLAN"),
        # JOSE / MARIA en nombre compuesto se omiten.
        ("José Luis", "Ramos", "Vega", "RAVL"),
        ("Ma. Fernanda", "Ramos", "Vega", "RAVF"),
        ("María", "Ramos", "Vega", "RAVM"),
        # Partículas.
        ("Pablo", "de la Fuente", "Mc Allen", "FUAP"),
        # El RFC conserva la Ñ (la CURP la cambia por X).
        ("Andrea", "Ñuñez", "Soto", "ÑUSA"),
        # Palabra inconveniente: la última letra cambia por X.
        ("Omar", "Peña", "Díaz", "PEDX"),
    ],
)
def test_letras_del_rfc(nombre: str, paterno: str, materno: str | None, letras: str) -> None:
    assert _rfc(nombre, paterno, materno)[:4] == letras


def test_build_rfc_estructura() -> None:
    rfc = _rfc("Laura", "Gómez", "Ruiz")
    assert len(rfc) == 13
    assert rfc[4:10] == "910407"
    assert RFC_PF_RE.match(rfc)
    assert rfc[12] == rfc_check_digit(rfc[:12])


def test_la_homonimia_depende_del_nombre_completo() -> None:
    # Mismas 10 primeras posiciones, distinto nombre completo -> distinta homoclave.
    a, b = _rfc("Laura", "Gómez", "Ruiz"), _rfc("Lucía", "Gómez", "Ruiz")
    assert a[:10] == b[:10]
    assert a[10:12] != b[10:12]


# ---------------------------------------------------------------------------
# Dígito verificador
# ---------------------------------------------------------------------------
def test_digito_verificador_calculado_a_mano() -> None:
    # Primeros 12 caracteres del RFC genérico: X=34, A=10, 0=0, 1=1; pesos 13 a 2.
    # 34*13 + 10*12 + 34*11 + 34*10 + 1*8 + 1*6 + 1*4 = 1294; 1294 mod 11 = 7; 11-7 = 4.
    # (El RFC genérico termina en 0: es una clave especial que no sigue el algoritmo.)
    assert rfc_check_digit("XAXX01010100") == "4"


def test_digito_verificador_a_cuando_resulta_10() -> None:
    # Buscar una base cuyo dígito sea "A" y comprobar que se valida.
    base = next(
        f"GORL9104{d:02d}A1" for d in range(1, 29) if rfc_check_digit(f"GORL9104{d:02d}A1") == "A"
    )
    assert validate_rfc(base + "A").valid


def test_digito_verificador_rechaza_entradas_invalidas() -> None:
    with pytest.raises(ValueError):
        rfc_check_digit("GORL")
    with pytest.raises(ValueError):
        rfc_check_digit("GORL910407*1")


# ---------------------------------------------------------------------------
# Validación
# ---------------------------------------------------------------------------
def test_rfc_valido() -> None:
    result = validate_rfc(_rfc("Laura", "Gómez", "Ruiz"))
    assert result.valid
    assert result.warnings == ()


def test_validate_rfc_limpia_formato() -> None:
    rfc = _rfc("Laura", "Gómez", "Ruiz")
    result = validate_rfc(f" {rfc[:4].lower()}-{rfc[4:10]}-{rfc[10:]} ")
    assert result.rfc == rfc
    assert result.valid


@pytest.mark.parametrize("generico", ["XAXX010101000", "XEXX010101000", "xaxx-010101-000"])
def test_rfc_generico(generico: str) -> None:
    result = validate_rfc(generico)
    assert not result.valid
    assert result.generico
    assert _codes(result.warnings) == [WarningCode.RFC_GENERICO]


def test_digito_verificador_incorrecto() -> None:
    rfc = _rfc("Laura", "Gómez", "Ruiz")
    otro = "1" if rfc[12] != "1" else "2"
    result = validate_rfc(rfc[:12] + otro)
    assert result.formato_valido
    assert not result.valid
    assert _codes(result.warnings) == [WarningCode.RFC_HOMOCLAVE_INVALIDA]


@pytest.mark.parametrize(
    "texto",
    [
        "",
        None,
        "GORL910407",  # sin homoclave
        "GOR910407AB1",  # 12 caracteres: persona moral
        "GORL911307AB1",  # mes 13
        "GORL910431AB1",  # 31 de abril
        "GORL910407AB",  # incompleto
        "G0RL910407AB1",  # cero en las letras
        "GORL910407ABZ",  # verificador debe ser dígito o A
    ],
)
def test_formato_invalido(texto: str | None) -> None:
    result = validate_rfc(texto)
    assert not result.formato_valido
    assert _codes(result.warnings) == [WarningCode.RFC_FORMATO_INVALIDO]


def test_29_de_febrero_de_anio_00_es_valido() -> None:
    # 2000 fue bisiesto (1900 no): basta con que exista en alguno de los dos siglos.
    assert validate_rfc(_rfc("Laura", "Gómez", "Ruiz", date(2000, 2, 29))).valid


# ---------------------------------------------------------------------------
# Cruce con la CURP
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("nombre", "paterno", "materno"),
    [
        ("Laura", "Gómez", "Ruiz"),
        ("Omar", "Peña", "Díaz"),  # CURP PXDO / RFC PEDX: cada lista pone su X
        ("Andrea", "Ñuñez", "Soto"),  # CURP XUSA / RFC ÑUSA
        ("Hugo", "Barrera", ""),  # sin materno: CURP BAXH / RFC BAHU, la 4a letra difiere
    ],
)
def test_rfc_y_curp_de_la_misma_persona(nombre: str, paterno: str, materno: str) -> None:
    rfc, curp = _rfc(nombre, paterno, materno), _curp(nombre, paterno, materno)
    warnings = check_rfc_against_curp(rfc, curp)
    if materno:
        assert warnings == []
    else:
        # SAT y RENAPO resuelven distinto el apellido único: por eso es advertencia, no error.
        assert _codes(warnings) == [WarningCode.RFC_NO_COINCIDE_CON_CURP]


def test_rfc_y_curp_con_fecha_distinta() -> None:
    rfc = _rfc("Laura", "Gómez", "Ruiz", date(1991, 4, 8))
    curp = _curp("Laura", "Gómez", "Ruiz")
    assert _codes(check_rfc_against_curp(rfc, curp)) == [WarningCode.RFC_NO_COINCIDE_CON_CURP]


def test_rfc_generico_o_incompleto_no_se_cruza() -> None:
    curp = _curp("Laura", "Gómez", "Ruiz")
    assert check_rfc_against_curp("XAXX010101000", curp) == []
    assert check_rfc_against_curp("GORL", curp) == []


# ---------------------------------------------------------------------------
# Propiedades
# ---------------------------------------------------------------------------
_letras = "ABCDEFGHIJKLMNÑOPQRSTUVWXYZÁÉÍÓÚÜabcdefghijklmnñopqrstuvwxyzáéíóúü"
_nombres = st.text(alphabet=_letras + " -.'", min_size=1, max_size=30)


@given(
    nombre=_nombres,
    paterno=_nombres,
    materno=st.one_of(st.none(), st.just(""), _nombres),
    fecha=st.dates(min_value=date(1900, 1, 1), max_value=date(2099, 12, 31)),
)
def test_todo_rfc_construido_es_valido(
    nombre: str, paterno: str, materno: str | None, fecha: date
) -> None:
    rfc = _rfc(nombre, paterno, materno, fecha)
    result = validate_rfc(rfc)
    # Un RFC construido nunca debe coincidir con los genéricos.
    assert result.valid, rfc
