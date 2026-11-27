"""Pruebas del catálogo de entidades federativas."""

import pytest

from docextract.entidades import (
    CLAVES_CURP,
    ENTIDADES,
    NACIDO_EN_EXTRANJERO,
    find_entidad,
    por_clave_curp,
)


def test_hay_32_entidades_con_claves_unicas() -> None:
    assert len(ENTIDADES) == 32
    assert len({e.clave_curp for e in ENTIDADES}) == 32
    assert [e.clave_inegi for e in ENTIDADES] == [f"{i:02d}" for i in range(1, 33)]


def test_ne_es_clave_de_curp_pero_no_entidad() -> None:
    assert NACIDO_EN_EXTRANJERO in CLAVES_CURP
    assert por_clave_curp(NACIDO_EN_EXTRANJERO) is None
    assert por_clave_curp("NT").nombre == "Nayarit"  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("texto", "clave"),
    [
        ("Nayarit", "NT"),
        ("NAYARIT", "NT"),
        ("Nay.", "NT"),
        ("Ciudad de México", "DF"),
        ("CDMX", "DF"),
        ("Distrito Federal", "DF"),
        ("D.F.", "DF"),
        ("México", "MC"),
        ("Estado de México", "MC"),
        ("Edo. de Méx.", "MC"),
        ("Michoacán", "MN"),
        ("Michoacan de Ocampo", "MN"),
        ("Michoacán de 0campo", "MN"),  # error de OCR: cero por O
        ("Veracruz", "VZ"),
        ("Coahuila", "CL"),
        ("Querétaro de Arteaga", "QT"),
        ("Q. Roo", "QR"),
        ("San Luis Potosi", "SP"),
        ("Nuevo Leon", "NL"),
        ("SIN", "SL"),
    ],
)
def test_find_entidad(texto: str, clave: str) -> None:
    entidad = find_entidad(texto)
    assert entidad is not None
    assert entidad.clave_curp == clave


@pytest.mark.parametrize("texto", ["Narnia", "SXN", "", None, "Texas"])
def test_find_entidad_desconocida(texto: str | None) -> None:
    assert find_entidad(texto) is None
