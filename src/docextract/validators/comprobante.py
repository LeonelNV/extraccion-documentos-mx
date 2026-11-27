"""Validaciones del comprobante de domicilio."""

import calendar
from datetime import date

from docextract.config import ValidationConfig
from docextract.schemas import DocType, ExtractionWarning, WarningCode
from docextract.validators._common import make_warning

__all__ = ["add_months", "check_comprobante_age"]


def add_months(day: date, months: int) -> date:
    """Suma meses de calendario; si el día no existe en el mes destino, usa el último.

    >>> add_months(date(2026, 11, 30), 3)
    datetime.date(2027, 2, 28)
    """
    month_index = day.month - 1 + months
    year, month = day.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def check_comprobante_age(
    fecha_emision: date | None,
    *,
    today: date,
    config: ValidationConfig | None = None,
    docs: tuple[DocType, ...] = (DocType.COMPROBANTE_DOMICILIO,),
) -> list[ExtractionWarning]:
    """Advierte si el comprobante tiene más de ``comprobante_max_months`` meses.

    ``today`` es obligatorio para que el resultado no dependa del reloj (y sea reproducible
    en las pruebas). Una fecha futura indica un error de lectura. Sin fecha no se advierte
    aquí: la falta del dato la marca la fusión con ``CAMPO_NO_ENCONTRADO``.
    """
    config = config or ValidationConfig()
    if fecha_emision is None:
        return []
    if fecha_emision > today:
        return [
            make_warning(
                WarningCode.FECHA_INVALIDA,
                "La fecha de emisión del comprobante está en el futuro.",
                fields=("fecha_emision",),
                docs=docs,
            )
        ]
    if add_months(fecha_emision, config.comprobante_max_months) < today:
        return [
            make_warning(
                WarningCode.COMPROBANTE_ANTIGUO,
                f"El comprobante de domicilio tiene más de {config.comprobante_max_months} "
                "meses de antigüedad.",
                fields=("fecha_emision",),
                docs=docs,
            )
        ]
    return []
