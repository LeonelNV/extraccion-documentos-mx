"""Pruebas de antigüedad del comprobante de domicilio."""

from datetime import date

import pytest

from docextract.config import ValidationConfig
from docextract.schemas import WarningCode
from docextract.validators.comprobante import add_months, check_comprobante_age

HOY = date(2026, 11, 26)


@pytest.mark.parametrize(
    ("fecha", "meses", "esperado"),
    [
        (date(2026, 1, 31), 1, date(2026, 2, 28)),
        (date(2024, 1, 31), 1, date(2024, 2, 29)),  # bisiesto
        (date(2026, 11, 30), 3, date(2027, 2, 28)),
        (date(2026, 10, 15), 3, date(2027, 1, 15)),
        (date(2026, 5, 10), 12, date(2027, 5, 10)),
        (date(2026, 3, 31), -1, date(2026, 2, 28)),
    ],
)
def test_add_months(fecha: date, meses: int, esperado: date) -> None:
    assert add_months(fecha, meses) == esperado


@pytest.mark.parametrize(
    "fecha",
    [HOY, date(2026, 9, 1), date(2026, 8, 26)],  # 26 de agosto: exactamente 3 meses
)
def test_comprobante_vigente(fecha: date) -> None:
    assert check_comprobante_age(fecha, today=HOY) == []


def test_comprobante_antiguo() -> None:
    warnings = check_comprobante_age(date(2026, 8, 25), today=HOY)
    assert [w.code for w in warnings] == [WarningCode.COMPROBANTE_ANTIGUO]
    assert "3 meses" in warnings[0].message


def test_meses_configurables() -> None:
    config = ValidationConfig(comprobante_max_months=6)
    assert check_comprobante_age(date(2026, 6, 1), today=HOY, config=config) == []
    assert check_comprobante_age(date(2026, 5, 1), today=HOY, config=config)


def test_fecha_futura() -> None:
    warnings = check_comprobante_age(date(2026, 11, 27), today=HOY)
    assert [w.code for w in warnings] == [WarningCode.FECHA_INVALIDA]


def test_sin_fecha_no_advierte() -> None:
    assert check_comprobante_age(None, today=HOY) == []
