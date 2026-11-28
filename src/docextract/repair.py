"""Corrige los errores típicos del OCR en CURP y RFC usando su estructura.

El OCR confunde caracteres parecidos (``0``/``O``, ``1``/``I``, ``5``/``S``, ``8``/``B``),
inserta un carácter de más o pega la clave a su etiqueta ("CURPABCD..."). Pero cada posición
de la CURP y del RFC admite solo letras o solo dígitos, y el último carácter es un dígito
verificador.

Se generan variantes con su número de cambios y quien llama acepta la variante **válida con
menos cambios**. Si dos variantes distintas empatan, la corrección es ambigua.

>>> [v for v, cambios in repair("LIRCO30101MNTMJLAS", CURP_PATTERN)][:3]
['LIRC030101MNTMJLA5', 'LIRC030101MNTMJLA3', 'LIRC030101MNTMJLA8']
"""

import re
from collections.abc import Iterable, Iterator

__all__ = ["CURP_PATTERN", "RFC_PATTERN", "candidate_strings", "repair"]

CURP_PATTERN = "LLLLDDDDDDLLLLLLAD"
"""L: letra, D: dígito, A: letra o dígito (el diferenciador de la CURP, la homoclave)."""
RFC_PATTERN = "LLLLDDDDDDAAA"

# Confusiones del OCR, de la más a la menos probable.
COMO_DIGITO = {
    "O": "0", "Q": "0", "D": "0", "U": "0", "I": "1", "L": "1", "|": "1", "T": "7",
    "Z": "2", "S": "538", "B": "83", "G": "69", "A": "4", "E": "3",
}  # fmt: skip
COMO_LETRA = {
    "0": "ODQ", "1": "IL", "2": "Z", "3": "BE", "4": "A", "5": "S", "6": "G", "7": "T",
    "8": "B", "9": "G",
}  # fmt: skip


def _options(char: str, kind: str) -> list[tuple[str, int]]:
    """Caracteres posibles en una posición, con su costo (0 si se deja igual)."""
    if kind == "D":
        if char.isdigit():
            return [(char, 0)]
        return [(c, 1) for c in COMO_DIGITO.get(char, "")]
    if kind == "L":
        if char.isalpha():
            return [(char, 0)]
        return [(c, 1) for c in COMO_LETRA.get(char, "")]
    out = [(char, 0)] if char.isalnum() else []
    out += [(c, 1) for c in COMO_DIGITO.get(char, "") + COMO_LETRA.get(char, "")]
    return out


def repair(text: str, pattern: str, *, max_changes: int = 4) -> list[tuple[str, int]]:
    """Variantes de ``text`` que respetan ``pattern``, de menos a más cambios.

    ``[]`` si el largo no coincide o si alguna posición no tiene corrección posible.
    """
    if len(text) != len(pattern):
        return []
    out: list[tuple[str, int]] = [("", 0)]
    for char, kind in zip(text.upper(), pattern, strict=True):
        options = _options(char, kind)
        out = [(p + c, n + k) for p, n in out for c, k in options if n + k <= max_changes]
        if not out:
            return []
    return sorted(dict(out).items(), key=lambda item: item[1])


def candidate_strings(
    lines: Iterable[str], length: int, *, max_extra: int = 6
) -> Iterator[tuple[str, int]]:
    """Cadenas de ``length`` caracteres que podrían ser una clave mal leída, con su costo.

    Por línea: cada palabra y cada unión de 2 o 3 palabras seguidas (el OCR puede partir la
    clave), costo 0. Con un carácter de más se prueba quitar cada uno (costo 1); con 2 a 6
    de más (la etiqueta pegada), cada ventana de ``length`` (costo 0).
    """
    seen: set[str] = set()
    for line in lines:
        tokens = re.findall(r"[A-Z0-9Ñ&|]+", line.upper())
        joined = ["".join(tokens[i : i + n]) for n in (1, 2, 3) for i in range(len(tokens) - n + 1)]
        for s in joined:
            extra = len(s) - length
            if extra == 0:
                variants = [(s, 0)]
            elif extra == 1:
                variants = [(s[:i] + s[i + 1 :], 1) for i in range(len(s))]
            elif 2 <= extra <= max_extra:
                variants = [(s[i : i + length], 0) for i in range(extra + 1)]
            else:
                continue
            for v, cost in variants:
                if v not in seen:
                    seen.add(v)
                    yield v, cost
