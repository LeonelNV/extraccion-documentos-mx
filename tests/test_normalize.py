"""Pruebas de normalización de texto, fechas y domicilio."""

from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from docextract.normalize import (
    address_key,
    clean_identifier,
    clean_text,
    comparison_key,
    is_sin_numero,
    normalize_codigo_postal,
    parse_date,
    strip_accents,
    to_form_format,
)


# ---------------------------------------------------------------------------
# Texto
# ---------------------------------------------------------------------------
def test_clean_text_conserva_el_valor_original_salvo_espacios() -> None:
    assert clean_text("  María   José\n") == "María José"
    assert clean_text(None) is None


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("María", "MARIA"),
        ("JOSÉ", "JOSE"),
        ("Núñez", "NUÑEZ"),  # la Ñ se conserva
        ("Argüello", "ARGUELLO"),  # la diéresis se quita
        ("López-Castillo", "LOPEZ CASTILLO"),
        ("O'Brian", "O BRIAN"),
        ("  ma.  de   los ángeles ", "MA DE LOS ANGELES"),
        ("", ""),
        (None, ""),
    ],
)
def test_comparison_key(texto: str | None, esperado: str) -> None:
    assert comparison_key(texto) == esperado


def test_comparison_key_iguala_formas_unicode_compuestas_y_descompuestas() -> None:
    compuesta = "Peña"  # "ñ" como un solo carácter
    descompuesta = "Peña"  # "n" + tilde combinante
    assert comparison_key(compuesta) == comparison_key(descompuesta) == "PEÑA"


def test_strip_accents_puede_quitar_la_enie() -> None:
    assert strip_accents("Peña") == "Peña"
    assert strip_accents("Peña", keep_enie=False) == "Pena"


@given(st.text())
def test_comparison_key_es_idempotente(texto: str) -> None:
    assert comparison_key(comparison_key(texto)) == comparison_key(texto)


def test_clean_identifier() -> None:
    assert clean_identifier(" abcd-123 456.x ") == "ABCD123456X"
    assert clean_identifier(None) == ""


@pytest.mark.parametrize("invisible", [0xFEFF, 0x200B, 0x200C, 0x200D, 0x00AD])
def test_quita_caracteres_invisibles(invisible: int) -> None:
    # Llegan en texto copiado de PDFs y en la entrada que manda PowerShell (BOM).
    char = chr(invisible)
    assert clean_identifier(f"{char}ABCD{char}12") == "ABCD12"
    assert comparison_key(f"{char}Ma{char}ría") == "MARIA"
    assert clean_text(f"{char}María ") == "María"


# ---------------------------------------------------------------------------
# Fechas
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "texto",
    [
        "07/04/1991",
        "7/4/1991",
        "07-04-1991",
        "07.04.1991",
        "1991-04-07",
        "1991/04/07",
        "07/ABR/1991",
        "07-abr-1991",
        "07 ABR. 1991",
        "7 de abril de 1991",
        "7 DE ABRIL DEL 1991",
        "07 Abril 1991",
        "abril 7, 1991",
        "Abril 7 de 1991",
    ],
)
def test_parse_date_formatos(texto: str) -> None:
    assert parse_date(texto) == date(1991, 4, 7)


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("15 de septiembre de 2026", date(2026, 9, 15)),
        ("15/SEPT/2026", date(2026, 9, 15)),
        ("15/SEP/2026", date(2026, 9, 15)),
        ("01 de diciembre de 2026", date(2026, 12, 1)),
        ("29/02/2024", date(2024, 2, 29)),  # bisiesto
    ],
)
def test_parse_date_meses_y_bisiestos(texto: str, esperado: date) -> None:
    assert parse_date(texto) == esperado


@pytest.mark.parametrize(
    "texto",
    ["30/02/1991", "29/02/2023", "31/04/1991", "00/01/1991", "15/13/1991", "15/FOO/1991", "", None],
)
def test_parse_date_invalidas(texto: str | None) -> None:
    assert parse_date(texto) is None


def test_parse_date_anio_de_dos_digitos_solo_si_se_permite() -> None:
    assert parse_date("15/03/26") is None
    assert parse_date("15/03/26", allow_two_digit_year=True) == date(2026, 3, 15)
    assert parse_date("15 MAR 26", allow_two_digit_year=True) == date(2026, 3, 15)


@given(st.dates(min_value=date(1900, 1, 1), max_value=date(2099, 12, 31)))
def test_parse_date_ida_y_vuelta(fecha: date) -> None:
    assert parse_date(fecha.strftime("%d/%m/%Y")) == fecha
    assert parse_date(fecha.isoformat()) == fecha


# ---------------------------------------------------------------------------
# Domicilio
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("63901", "63901"),
        (" 63 901 ", "63901"),
        ("C.P. 63901", "63901"),
        ("CP: 01901", "01901"),
        ("Código Postal 01901", "01901"),
        ("1901", "01901"),  # Excel quita el cero inicial
        ("639011", None),
        ("63A01", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize_codigo_postal(texto: str | None, esperado: str | None) -> None:
    assert normalize_codigo_postal(texto) == esperado


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("Av. Insurgentes", "AVENIDA INSURGENTES"),
        ("AVENIDA INSURGENTES", "AVENIDA INSURGENTES"),
        ("Col. Centro", "COLONIA CENTRO"),
        ("Fracc. Los Fresnos", "FRACCIONAMIENTO LOS FRESNOS"),
        ("Blvd. Gral. Pérez", "BOULEVARD GENERAL PEREZ"),
    ],
)
def test_address_key(texto: str, esperado: str) -> None:
    assert address_key(texto) == esperado


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("S/N", True),
        ("s/n", True),
        ("SN", True),
        ("S N", True),
        ("Sin número", True),
        ("SIN NUM.", True),
        ("12", False),
        ("12-B", False),
        ("", False),
        (None, False),
    ],
)
def test_is_sin_numero(texto: str | None, esperado: bool) -> None:
    assert is_sin_numero(texto) is esperado


# ---------------------------------------------------------------------------
# Formato de la FEA
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("María José", "MARIA JOSE"),
        ("Núñez", "NUÑEZ"),  # la Ñ se conserva
        ("Argüello", "ARGUELLO"),
        ("O'Brian", "O'BRIAN"),  # la puntuación se conserva
        ("  Calle  Juárez ", "CALLE JUAREZ"),
        ("S/N", "S/N"),
        ("", ""),  # "no existe" sigue siendo cadena vacía
        (None, None),
    ],
)
def test_to_form_format(texto: str | None, esperado: str | None) -> None:
    assert to_form_format(texto) == esperado
