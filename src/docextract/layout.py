"""Texto de una página con posiciones: la entrada común de los parsers.

Un ``TextLayout`` es una lista de palabras con su caja. En la ruta 2a sale de la capa de
texto del PDF (``from_pdf``); en la fase 5 saldrá del OCR. Así los mismos parsers sirven
para PDFs digitales y para escaneos o fotos.

Búsqueda por etiquetas: cada línea se divide en segmentos ``etiqueta → valor``, donde el
valor son las palabras que siguen a la etiqueta hasta la siguiente etiqueta conocida o el
final de la línea. Esto resuelve los formularios a dos columnas ("Código Postal: 63000
Tipo de Vialidad: CALLE").
"""

import io
import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import cached_property

from docextract.normalize import comparison_key

__all__ = ["WORD_OPTIONS", "Line", "Segment", "TextLayout", "Word", "split_glued"]


@dataclass(frozen=True)
class Word:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float

    @property
    def height(self) -> float:
        return self.bottom - self.top

    @property
    def center_y(self) -> float:
        return (self.top + self.bottom) / 2


@dataclass(frozen=True)
class Line:
    words: tuple[Word, ...]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def top(self) -> float:
        return min(w.top for w in self.words)

    @property
    def bottom(self) -> float:
        return max(w.bottom for w in self.words)


@dataclass(frozen=True)
class Segment:
    """Una etiqueta encontrada en una línea y el texto que la sigue."""

    label: str
    """Clave normalizada de la etiqueta (p. ej. ``"CODIGO POSTAL"``)."""
    value: str
    """Texto original que sigue a la etiqueta; ``""`` si no hay nada."""
    line_index: int
    x0: float


WORD_OPTIONS = {"x_tolerance_ratio": 0.15, "keep_blank_chars": False, "use_text_flow": False}
"""Cómo pdfplumber arma palabras a partir de caracteres.

Por omisión junta los caracteres a menos de 3 pt. La constancia del SAT no tiene caracteres
de espacio: separa las palabras con huecos de menos de 3 pt (un espacio mide ~0.28 em, 2.2 pt
a 8 pt), así que pdfplumber entregaba "PrimerApellido:" y ninguna etiqueta coincidía. Con
``x_tolerance_ratio`` el umbral es proporcional al tamaño de letra: un hueco mayor a 0.15 em
separa palabras; entre letras de una misma palabra el hueco es ~0. Medido con
``make esqueleto`` sobre una constancia real.
"""

GLUED_COLON = re.compile(r"(?:(?<=[^\W\d_])|(?<=\))):(?=\w)")
"""Dos puntos entre una letra (o ")") y una letra o dígito: "Postal:63000"."""


def split_glued(word: Word) -> list[Word]:
    """Separa una etiqueta pegada a su valor: ``"Apellido:PEREZ"`` → ``"Apellido:"``,
    ``"PEREZ"``.

    En la constancia del SAT el código postal va pegado a su etiqueta ("Código Postal:85173"
    aun en un visor de PDF), y el OCR también puede omitir el espacio. No separa horas
    (``14:31``) ni URLs (``http://``). Las cajas de las piezas se reparten en proporción a
    sus caracteres.

    >>> [w.text for w in split_glued(Word("Postal:63000", 0, 60, 0, 10))]
    ['Postal:', '63000']
    >>> [w.text for w in split_glued(Word("14:31", 0, 25, 0, 10))]
    ['14:31']
    """
    cuts = [m.end() for m in GLUED_COLON.finditer(word.text)]
    if not cuts:
        return [word]
    pieces, start, n = [], 0, len(word.text)
    per_char = (word.x1 - word.x0) / n
    for cut in [*cuts, n]:
        x0, x1 = word.x0 + start * per_char, word.x0 + cut * per_char
        pieces.append(Word(word.text[start:cut], x0, x1, word.top, word.bottom))
        start = cut
    return pieces


class TextLayout:
    def __init__(self, words: Iterable[Word], *, width: float = 0, height: float = 0) -> None:
        self.words = tuple(piece for w in words if w.text.strip() for piece in split_glued(w))
        self.width = width
        self.height = height

    # ------------------------------------------------------------------
    # Construcción
    # ------------------------------------------------------------------
    @classmethod
    def from_pdf(cls, pdf: bytes, *, max_pages: int = 3) -> "TextLayout":
        """Palabras de la capa de texto de las primeras páginas, apiladas verticalmente."""
        import pdfplumber  # importación diferida: solo la ruta de texto la necesita

        words: list[Word] = []
        offset = 0.0
        width = 0.0
        with pdfplumber.open(io.BytesIO(pdf)) as document:
            for page in document.pages[:max_pages]:
                for w in page.extract_words(**WORD_OPTIONS):
                    words.append(
                        Word(w["text"], w["x0"], w["x1"], w["top"] + offset, w["bottom"] + offset)
                    )
                offset += float(page.height)
                width = max(width, float(page.width))
        return cls(words, width=width, height=offset)

    # ------------------------------------------------------------------
    # Texto
    # ------------------------------------------------------------------
    @cached_property
    def lines(self) -> tuple[Line, ...]:
        """Palabras agrupadas en líneas por su centro vertical, de arriba abajo.

        La tolerancia es estricta (35% de la altura de la palabra más baja) para no juntar
        columnas vecinas que van casi a la misma altura.
        """
        lines: list[list[Word]] = []
        for word in sorted(self.words, key=lambda w: (w.center_y, w.x0)):
            if lines:
                last = lines[-1]
                center = sum(w.center_y for w in last) / len(last)
                tolerance = 0.35 * min(word.height, min(w.height for w in last))
                if abs(word.center_y - center) <= max(tolerance, 1.0):
                    last.append(word)
                    continue
            lines.append([word])
        return tuple(Line(tuple(sorted(line, key=lambda w: w.x0))) for line in lines)

    @cached_property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    @property
    def alnum_chars(self) -> int:
        return sum(c.isalnum() for c in self.text)

    # ------------------------------------------------------------------
    # Etiquetas
    # ------------------------------------------------------------------
    def segments(self, labels: Iterable[str]) -> list[Segment]:
        """Todas las etiquetas conocidas encontradas, con su valor, en orden de lectura.

        Una etiqueta debe ocupar palabras completas: "Nombre" no coincide con el inicio
        de "Nombre(s):". Si dos etiquetas empiezan en la misma palabra gana la más larga. Y
        debe terminar en ":" o abrir la línea, para no confundirla con una palabra de un
        valor.
        """
        keys = sorted({comparison_key(label) for label in labels} - {""}, key=len, reverse=True)
        label_tokens = [(key, key.split()) for key in keys]
        found: list[Segment] = []
        for index, line in enumerate(self.lines):
            tokens: list[tuple[str, int]] = []  # (token, índice de palabra)
            ends: set[int] = set()  # posiciones de token donde termina una palabra
            for w_index, word in enumerate(line.words):
                for token in comparison_key(word.text).split():
                    tokens.append((token, w_index))
                ends.add(len(tokens))
            starts = {0} | ends

            matches: list[tuple[int, int, str]] = []  # (palabra inicial, palabra final, clave)
            position = 0
            while position < len(tokens):
                match = None
                if position in starts:
                    for key, parts in label_tokens:
                        end = position + len(parts)
                        if end in ends and [t for t, _ in tokens[position:end]] == parts:
                            first_word, last_word = tokens[position][1], tokens[end - 1][1]
                            # Una palabra de un valor puede coincidir con una etiqueta (la
                            # colonia "DULCES NOMBRES"). Solo es etiqueta si termina en ":" o
                            # si abre la línea.
                            if line.words[last_word].text.endswith(":") or first_word == 0:
                                match = (first_word, last_word, key)
                                position = end
                                break
                if match:
                    matches.append(match)
                else:
                    position += 1

            for i, (first, last, key) in enumerate(matches):
                stop = matches[i + 1][0] if i + 1 < len(matches) else len(line.words)
                value_words = line.words[last + 1 : stop]
                value = " ".join(w.text for w in value_words).strip(" :")
                found.append(Segment(key, value, index, line.words[first].x0))
        return found

    def values(
        self, labels: Sequence[str], vocabulary: Iterable[str], *, below: bool = True
    ) -> list[str]:
        """Valores de cualquiera de ``labels``, usando ``vocabulary`` para cortar.

        Si la etiqueta no tiene nada a su derecha y ``below`` es verdadero, toma la línea
        siguiente, siempre que esté cerca y no contenga etiquetas (si las tiene, el campo
        está vacío en el documento y se devuelve ``""``).
        """
        wanted = {comparison_key(label) for label in labels}
        vocabulary = set(vocabulary) | set(labels)
        segments = self.segments(vocabulary)
        lines_with_labels: dict[int, int] = defaultdict(int)
        for segment in segments:
            lines_with_labels[segment.line_index] += 1

        values: list[str] = []
        for segment in segments:
            if segment.label not in wanted:
                continue
            value = segment.value
            nxt = segment.line_index + 1
            if not value and below and nxt < len(self.lines) and not lines_with_labels[nxt]:
                current, following = self.lines[segment.line_index], self.lines[nxt]
                gap = following.top - current.bottom
                if gap <= 1.5 * (current.bottom - current.top):
                    value = following.text.strip(" :")
            values.append(value)
        return values

    def value(
        self, labels: Sequence[str], vocabulary: Iterable[str], *, below: bool = True
    ) -> str | None:
        """El primer valor no vacío; ``""`` si solo hay valores vacíos; ``None`` si la
        etiqueta no aparece."""
        found = self.values(labels, vocabulary, below=below)
        if not found:
            return None
        return next((v for v in found if v), "")
