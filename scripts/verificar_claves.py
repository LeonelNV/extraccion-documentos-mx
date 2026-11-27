"""Comprueba los algoritmos de CURP y RFC contra claves reales **sin exponerlas**.

Los algoritmos de los dígitos verificadores no están publicados por RENAPO ni por el SAT;
este script permite confirmarlos con claves reales que solo existen en tu máquina.

- Lee una clave por línea desde la entrada estándar o, si no hay entrada redirigida, las pide
  sin mostrarlas en pantalla (como una contraseña). Termina con una línea vacía.
- **Solo imprime conteos.** Nunca escribe las claves en pantalla, en disco ni en logs.

Uso::

    uv run python scripts/verificar_claves.py                    # captura oculta
    uv run python scripts/verificar_claves.py < claves.txt       # archivo fuera del repo

Las claves de 18 caracteres se tratan como CURP y las de 13 como RFC.
"""

from __future__ import annotations

import getpass
import sys
from collections import Counter
from collections.abc import Iterable, Iterator

from docextract.normalize import clean_identifier
from docextract.validators.curp import validate_curp
from docextract.validators.rfc import validate_rfc


def _interactive() -> Iterator[str]:
    while True:
        value = getpass.getpass("Clave (Enter vacío para terminar): ")
        if not value.strip():
            return
        yield value


def summarize(values: Iterable[str]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for raw in values:
        value = clean_identifier(raw)
        if not value:
            continue
        if len(value) == 18:
            result = validate_curp(value)
            if result.info is None:
                counts["CURP con formato inválido"] += 1
            elif result.info.digito_verificador_valido:
                counts["CURP con dígito verificador correcto"] += 1
            else:
                counts["CURP con dígito verificador INCORRECTO"] += 1
        elif len(value) == 13:
            rfc = validate_rfc(value)
            if rfc.generico:
                counts["RFC genérico (no cuenta)"] += 1
            elif not rfc.formato_valido:
                counts["RFC con formato inválido"] += 1
            elif rfc.digito_verificador_valido:
                counts["RFC con dígito verificador correcto"] += 1
            else:
                counts["RFC con dígito verificador INCORRECTO"] += 1
        else:
            counts["Longitud distinta de 18 y 13 (ignorada)"] += 1
    return counts


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):  # acentos correctos en la consola de Windows
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    values = sys.stdin if not sys.stdin.isatty() else _interactive()
    counts = summarize(values)
    if not counts:
        print("No se recibió ninguna clave.")
        return 0
    for label, count in sorted(counts.items()):
        print(f"{count:6d}  {label}")
    incorrect = sum(c for label, c in counts.items() if "INCORRECTO" in label)
    return 1 if incorrect else 0


if __name__ == "__main__":
    raise SystemExit(main())
