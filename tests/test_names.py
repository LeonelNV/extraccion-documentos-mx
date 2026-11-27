"""Pruebas de comparación de nombres entre documentos (nombres inventados)."""

import pytest

from docextract.config import ValidationConfig
from docextract.schemas import DocType, WarningCode
from docextract.validators.names import PersonName, compare_names, name_key, name_similarity


@pytest.mark.parametrize(
    ("texto", "es_nombre", "esperado"),
    [
        ("María José", True, "MARIA JOSE"),
        ("Ma. José", True, "MARIA JOSE"),
        ("MA JOSE", True, "MARIA JOSE"),
        ("J. Antonio", True, "JOSE ANTONIO"),
        ("Ma. de los Ángeles", True, "MARIA DE LOS ANGELES"),
        ("Gpe.", True, "GUADALUPE"),
        ("Núñez", False, "NUÑEZ"),
        # Las abreviaturas de nombres de pila no se aplican a los apellidos.
        ("Ma", False, "MA"),
    ],
)
def test_name_key(texto: str, es_nombre: bool, esperado: str) -> None:
    assert name_key(texto, es_nombre=es_nombre) == esperado


def test_name_similarity() -> None:
    assert name_similarity("MARÍA", "maria") == 1.0
    assert name_similarity("Ma. José", "María José", es_nombre=True) == 1.0
    assert 0.8 < name_similarity("GONZALEZ", "GONZALES") < 0.9
    assert name_similarity("PEREZ", "RAMIREZ") < 0.8


def _persona(nombre: str | None, paterno: str | None, materno: str | None) -> PersonName:
    return PersonName(nombre=nombre, apellido_paterno=paterno, apellido_materno=materno)


def test_mismos_datos_con_acentos_y_mayusculas_distintos() -> None:
    curp = _persona("MARIA JOSE", "PEREZ", "NUÑEZ")
    ine = _persona("María José", "Pérez", "Núñez")
    assert compare_names(curp, ine) == []


def test_abreviatura_de_nombre_compuesto() -> None:
    assert (
        compare_names(
            _persona("Ma. Fernanda", "Ramos", "Vega"), _persona("María Fernanda", "Ramos", "Vega")
        )
        == []
    )


def test_apellido_distinto() -> None:
    warnings = compare_names(
        _persona("Laura", "Gómez", "Ruiz"),
        _persona("Laura", "Ramírez", "Ruiz"),
        docs=(DocType.CURP, DocType.INE),
    )
    assert [w.code for w in warnings] == [WarningCode.NOMBRE_NO_COINCIDE]
    assert warnings[0].fields == ("apellido_paterno",)
    assert warnings[0].docs == (DocType.CURP, DocType.INE)


def test_varios_campos_distintos_dan_una_sola_advertencia() -> None:
    warnings = compare_names(_persona("Laura", "Gómez", "Ruiz"), _persona("Sofía", "Gómez", "Lara"))
    assert len(warnings) == 1
    assert warnings[0].fields == ("nombre", "apellido_materno")


def test_apellido_materno_vacio_en_un_documento() -> None:
    warnings = compare_names(_persona("Hugo", "Barrera", ""), _persona("Hugo", "Barrera", "Soto"))
    assert warnings[0].fields == ("apellido_materno",)


def test_ambos_sin_apellido_materno() -> None:
    assert compare_names(_persona("Hugo", "Barrera", ""), _persona("Hugo", "Barrera", "")) == []


def test_campo_no_extraido_no_se_compara() -> None:
    assert (
        compare_names(_persona("Hugo", "Barrera", None), _persona("Hugo", "Barrera", "Soto")) == []
    )
    assert compare_names(_persona(None, None, None), _persona("Hugo", "Barrera", "Soto")) == []


def test_apellido_compuesto_repartido_distinto() -> None:
    # Mismo nombre completo, distinta separación entre campos: no se advierte.
    a = _persona("Juan", "De la Cruz", "Soto")
    b = _persona("Juan De", "La Cruz", "Soto")
    assert compare_names(a, b) == []


def test_umbral_configurable() -> None:
    a, b = _persona("Laura", "González", "Ruiz"), _persona("Laura", "Gonzales", "Ruiz")
    assert compare_names(a, b)  # 0.875 < 0.90 por defecto
    assert compare_names(a, b, config=ValidationConfig(name_similarity_threshold=0.85)) == []


def test_el_mensaje_no_incluye_los_nombres() -> None:
    warnings = compare_names(_persona("Laura", "Gómez", "Ruiz"), _persona("Sofía", "Lara", "Paz"))
    for valor in ("Laura", "Gómez", "Ruiz", "Sofía", "Lara", "Paz", "LAURA", "GOMEZ"):
        assert valor not in warnings[0].message
