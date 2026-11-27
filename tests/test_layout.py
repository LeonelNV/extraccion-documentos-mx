"""Pruebas del TextLayout: líneas, etiquetas y valores."""

import io

import pytest
from reportlab.pdfgen.canvas import Canvas

from docextract.layout import TextLayout, Word


def layout(*rows: str | list[tuple[float, str]], line_height: float = 20) -> TextLayout:
    """Arma un layout: cada fila es un texto (desde x=50) o una lista de (x, texto)."""
    words = []
    for i, row in enumerate(rows):
        chunks = [(50.0, row)] if isinstance(row, str) else row
        top = 50 + i * line_height
        for x, text in chunks:
            for word in text.split():
                width = 6.0 * len(word)
                words.append(Word(word, x, x + width, top, top + 10))
                x += width + 4
    return TextLayout(words, width=612, height=792)


VOCAB = ("Nombre(s)", "Nombre", "Primer apellido", "Código Postal", "Tipo de Vialidad", "Colonia")


def test_agrupa_palabras_en_lineas_aunque_varie_un_poco_la_altura() -> None:
    words = [
        Word("Sexo:", 50, 80, 100.0, 110.0),
        Word("HOMBRE", 200, 250, 100.8, 111.2),  # otra fuente, casi la misma altura
        Word("Abajo", 50, 80, 125.0, 135.0),
    ]
    lines = TextLayout(words).lines
    assert [line.text for line in lines] == ["Sexo: HOMBRE", "Abajo"]


def test_columnas_vecinas_casi_a_la_misma_altura_no_se_mezclan() -> None:
    words = [Word("Izquierda", 50, 100, 92.7, 98.7), Word("Derecha", 300, 350, 89.9, 96.9)]
    assert len(TextLayout(words).lines) == 2


def test_gana_la_etiqueta_mas_larga() -> None:
    lay = layout("Nombre(s): JUAN CARLOS")
    assert lay.value(("Nombre(s)",), VOCAB) == "JUAN CARLOS"
    assert lay.value(("Nombre",), VOCAB) is None  # "Nombre" no coincide con "Nombre(s):"


def test_dos_columnas() -> None:
    lay = layout([(50, "Código Postal: 63000"), (300, "Tipo de Vialidad: CALLE")])
    assert lay.value(("Código Postal",), VOCAB) == "63000"
    assert lay.value(("Tipo de Vialidad",), VOCAB) == "CALLE"


def test_valor_vacio_y_etiqueta_ausente() -> None:
    lay = layout([(50, "Primer apellido:"), (300, "Código Postal: 63000")], "Sexo: H")
    assert lay.value(("Primer apellido",), (*VOCAB, "Sexo")) == ""
    assert lay.value(("Colonia",), VOCAB) is None


def test_valor_en_la_linea_de_abajo() -> None:
    lay = layout("Nombre:", "JUAN PEREZ LOPEZ")
    assert lay.value(("Nombre",), VOCAB) == "JUAN PEREZ LOPEZ"
    assert lay.value(("Nombre",), VOCAB, below=False) == ""


def test_no_toma_la_linea_de_abajo_si_tiene_etiquetas_o_esta_lejos() -> None:
    assert layout("Nombre:", "Primer apellido: PEREZ").value(("Nombre",), VOCAB) == ""
    assert layout("Nombre:", "JUAN", line_height=60).value(("Nombre",), VOCAB) == ""


def test_una_palabra_del_valor_no_es_etiqueta() -> None:
    # La colonia "DULCES NOMBRES": "NOMBRES" sin dos puntos y a media línea es parte del valor.
    lay = layout("Colonia: DULCES NOMBRES")
    assert lay.value(("Colonia",), (*VOCAB, "Nombres")) == "DULCES NOMBRES"


def test_etiqueta_sin_dos_puntos_al_inicio_de_la_linea() -> None:
    assert layout("Primer apellido PEREZ").value(("Primer apellido",), VOCAB) == "PEREZ"


def _pdf_etiqueta_pegada(gap: float) -> bytes:
    """Etiqueta en negritas y valor a ``gap`` puntos, como en la constancia del SAT."""
    from reportlab.pdfbase.pdfmetrics import stringWidth

    buffer = io.BytesIO()
    canvas = Canvas(buffer, invariant=1)
    pares = [("Primer Apellido:", "PEREZ"), ("Nombre (s):", "JUAN CARLOS"), ("RFC:", "X")]
    for i, (etiqueta, valor) in enumerate(pares):
        y = 700 - i * 14
        canvas.setFont("Helvetica-Bold", 8)
        canvas.drawString(50, y, etiqueta)
        canvas.setFont("Helvetica", 8)
        canvas.drawString(50 + stringWidth(etiqueta, "Helvetica-Bold", 8) + gap, y, valor)
    canvas.save()
    return buffer.getvalue()


@pytest.mark.parametrize("gap", [0.0, 1.5, 4.0])
def test_etiqueta_pegada_a_su_valor(gap: float) -> None:
    # Con menos de 3 pt de separación pdfplumber entrega "Apellido:PEREZ" en una palabra.
    lay = TextLayout.from_pdf(_pdf_etiqueta_pegada(gap))
    vocab = (*VOCAB, "Nombre (s)", "RFC")
    assert lay.value(("Primer apellido",), vocab) == "PEREZ"
    assert lay.value(("Nombre (s)",), vocab) == "JUAN CARLOS"


def test_no_separa_horas_ni_urls() -> None:
    lay = layout("Sello: 2026/08/12 14:31:01 http://sat.gob.mx")
    assert lay.lines[0].text == "Sello: 2026/08/12 14:31:01 http://sat.gob.mx"


def test_desde_pdf_con_varias_paginas() -> None:
    buffer = io.BytesIO()
    canvas = Canvas(buffer, invariant=1)
    canvas.drawString(72, 700, "Primera: UNO")
    canvas.showPage()
    canvas.drawString(72, 700, "Segunda: DOS")
    canvas.showPage()
    canvas.save()
    lay = TextLayout.from_pdf(buffer.getvalue())
    assert [line.text for line in lay.lines] == ["Primera: UNO", "Segunda: DOS"]
    assert lay.alnum_chars == len("PrimeraUNOSegundaDOS")
