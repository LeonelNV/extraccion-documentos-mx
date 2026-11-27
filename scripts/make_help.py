"""Imprime los objetivos del Makefile que tienen una descripción ``## ...``."""

import re
import sys
from pathlib import Path

TARGET = re.compile(r"^([a-zA-Z0-9_-]+):.*?## (.+)$")


def main(makefile: str = "Makefile") -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    lines = Path(makefile).read_text(encoding="utf-8").splitlines()
    targets = [m.groups() for line in lines if (m := TARGET.match(line))]
    width = max(len(name) for name, _ in targets)
    print("Uso: make <objetivo>\n")
    for name, description in targets:
        print(f"  {name:<{width}}  {description}")


if __name__ == "__main__":
    main(*sys.argv[1:])
