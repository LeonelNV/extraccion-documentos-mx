"""Imprime el "esqueleto" de tus documentos reales: su estructura, sin datos personales.

Sirve para ajustar los parsers y las plantillas sintéticas a un formato real sin ver sus
datos. Lee el PDF igual que el parser (pdfplumber + ``TextLayout``) y muestra:

* páginas, fuentes y tamaños;
* palabras que pdfplumber juntó (``Etiqueta:valor`` o dos palabras sin espacio);
* cada línea con la posición x de cada palabra;
* qué etiquetas encuentra el parser y si su valor está en la misma línea, abajo o vacío.

**Enmascarado.** Una palabra se muestra tal cual solo si es parte de una etiqueta o título
conocido, con las mismas mayúsculas (los valores de estos documentos van en mayúsculas y las
etiquetas no, así que "CALLE" se enmascara aunque exista la etiqueta "Entre Calle"). Todo lo
demás se reemplaza por su forma: mayúscula → ``A``, minúscula → ``a``, dígito → ``9``; la
puntuación se conserva. Se ve la longitud de cada palabra, no su contenido.

No imprime nombres de archivo ni mensajes de error (solo su tipo) y no escribe nada a disco.
**Revisa la salida antes de compartirla.**

    uv run python eval/esqueleto.py                    # data/real/csf/ y data/real/curp/
    uv run python eval/esqueleto.py data/real/csf      # una carpeta o archivos sueltos
"""

import argparse
import io
import logging
import sys
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from docextract.classify import classify_text
from docextract.layout import GLUED_COLON, WORD_OPTIONS, TextLayout, Word
from docextract.parsers import csf as csf_parser
from docextract.parsers import curp as curp_parser
from docextract.schemas import DocType

ROOT = Path(__file__).resolve().parents[1]
CARPETAS = {"curp": DocType.CURP, "csf": DocType.CSF}
ETIQUETAS = {DocType.CURP: curp_parser.ETIQUETAS, DocType.CSF: csf_parser.ETIQUETAS}
VOCABULARIOS = {DocType.CURP: curp_parser.VOCABULARIO, DocType.CSF: csf_parser.VOCABULARIO}

TITULOS = (
    "CÉDULA DE IDENTIFICACIÓN FISCAL", "CONSTANCIA DE SITUACIÓN FISCAL",
    "VALIDA TU INFORMACIÓN FISCAL", "Registro Federal de Contribuyentes",
    "Nombre, denominación o razón social", "Datos de Identificación del Contribuyente:",
    "Datos del domicilio registrado", "Actividades Económicas:", "Regímenes:", "Orden",
    "Actividad Económica", "Porcentaje", "Página de", "Cadena Original Sello:",
    "Sello Digital:", "CLAVE ÚNICA DE REGISTRO DE POBLACIÓN", "Constancia de la CURP",
    "Clave Única de Registro de Población",
)  # fmt: skip
MAYUSCULAS_CORTAS = {"RFC", "Y"}
"""Palabras en mayúsculas de menos de 4 letras que sí se muestran. Las demás ("DE", "LA")
se enmascaran: también aparecen dentro de los valores."""


def palabras_conocidas(frases: Iterable[str]) -> frozenset[str]:
    conocidas: set[str] = set()
    for frase in frases:
        for palabra in frase.replace(",", " ").split():
            base = palabra.strip(":")
            letras = sum(c.isalpha() for c in base)
            if base.isupper() and letras < 4 and base not in MAYUSCULAS_CORTAS:
                continue
            conocidas |= {base, f"{base}:", f"{base},"}
    return frozenset(conocidas)


CONOCIDAS = palabras_conocidas(
    [*TITULOS, *curp_parser.VOCABULARIO, *csf_parser.VOCABULARIO, "Nombre (s)", "(s):", "(s)"]
)


def mascara(texto: str) -> str:
    """>>> mascara("Postal:")
    'Postal:'
    >>> mascara("Juárez-12")
    'Aaaaaa-99'
    """
    if texto in CONOCIDAS:
        return texto
    cortes = [m.end() for m in GLUED_COLON.finditer(texto)]
    if cortes:  # "Postal:63000": se enmascara cada pieza, así la etiqueta queda visible
        piezas = [texto[a:b] for a, b in zip([0, *cortes], [*cortes, len(texto)], strict=True)]
        return "".join(mascara(p) for p in piezas)
    return "".join(
        "9" if c.isdigit() else "A" if c.isupper() else "a" if c.isalpha() else c for c in texto
    )


def _fuente(nombre: str) -> str:
    """Sin el prefijo del subconjunto embebido (``ABCDEF+Arial-Bold`` → ``Arial-Bold``)."""
    return nombre.split("+", 1)[-1]


def _marca_huecos(chars: list[dict]) -> str | None:
    """Palabra enmascarada con ``·`` donde hay un hueco mayor a 0.1 del tamaño de letra:
    posibles palabras que pdfplumber juntó. Con ``WORD_OPTIONS`` (umbral 0.15 em) esta lista
    debería salir vacía; si no, el umbral no basta para ese documento."""
    piezas, actual = [], ""
    for i, ch in enumerate(chars):
        if i and ch["x0"] - chars[i - 1]["x1"] > 0.1 * ch["size"]:
            piezas.append(actual)
            actual = ""
        actual += ch["text"]
    if not piezas:
        return None
    return "·".join(mascara(p) for p in [*piezas, actual])


def esqueleto(pdf: bytes, doc_type: DocType | None, *, max_pages: int = 3) -> list[str]:
    import pdfplumber

    out: list[str] = []
    words: list[Word] = []
    pegadas: list[str] = []
    juntas: list[str] = []
    fuentes: Counter[tuple[str, float]] = Counter()
    offsets: list[float] = []
    offset = 0.0
    with pdfplumber.open(io.BytesIO(pdf)) as document:
        out.append(f"Páginas: {len(document.pages)} (se leen las primeras {max_pages})")
        for page in document.pages[:max_pages]:
            offsets.append(offset)
            # Mismos parámetros que TextLayout.from_pdf: con extra_attrs, pdfplumber cortaría
            # las palabras donde cambia la fuente y ya no veríamos lo que ve el parser.
            for w in page.extract_words(**WORD_OPTIONS, return_chars=True):
                words.append(
                    Word(w["text"], w["x0"], w["x1"], w["top"] + offset, w["bottom"] + offset)
                )
                for ch in w["chars"]:
                    fuentes[(_fuente(ch["fontname"]), round(ch["size"], 1))] += 1
                if GLUED_COLON.search(w["text"]):
                    pegadas.append(mascara(w["text"]))
                elif marcado := _marca_huecos(w["chars"]):
                    juntas.append(marcado)
            offset += float(page.height)
    layout = TextLayout(words)

    out.append("Fuentes (fuente, tamaño: caracteres):")
    for (fuente, size), n in sorted(fuentes.items()):
        out.append(f"  {fuente} {size} pt: {n}")
    out.append(f"Palabras 'Etiqueta:valor' pegadas (el parser ya las separa): {len(pegadas)}")
    out += [f"  {p}" for p in pegadas[:40]]
    out.append(f"Palabras con huecos internos grandes (· = hueco): {len(juntas)}")
    out += [f"  {j}" for j in juntas[:40]]

    out.append("")
    out.append("Líneas (pág, y, alto | palabra@x ...):")
    for index, line in enumerate(layout.lines):
        pagina = sum(line.top >= o for o in offsets)
        y = line.top - offsets[pagina - 1]
        palabras = " ".join(f"{mascara(w.text)}@{w.x0:.0f}" for w in line.words)
        out.append(f"{index:3d} p{pagina} y={y:6.1f} h={line.bottom - line.top:4.1f} | {palabras}")

    clasificacion = classify_text(layout)
    out.append("")
    puntajes = ", ".join(f"{d.value} {s:g}" for d, s in clasificacion.scores.items())
    tipo = clasificacion.doc_type.value if clasificacion.doc_type else "no reconocido"
    out.append(f"Clasificador: {tipo} (puntajes: {puntajes})")
    if doc_type in ETIQUETAS:
        vocabulario = VOCABULARIOS[doc_type]
        out.append("Etiquetas encontradas (línea: etiqueta → valor):")
        for s in layout.segments(vocabulario):
            valor = " ".join(mascara(p) for p in s.value.split()) or "(vacío)"
            out.append(f"  {s.line_index:3d}: {s.label} → {valor}")
        out.append("Campos del parser (misma línea / abajo / vacío / sin etiqueta):")
        for campo, labels in ETIQUETAS[doc_type].items():
            misma = layout.value(labels, vocabulario, below=False)
            con_abajo = layout.value(labels, vocabulario)
            if misma is None:
                estado = "sin etiqueta"
            elif misma:
                estado = "misma línea"
            elif con_abajo:
                estado = "abajo"
            else:
                estado = "vacío"
            out.append(f"  {campo}: {estado}")
    return out


def _pdfs(rutas: list[Path]) -> list[tuple[Path, DocType | None]]:
    encontrados = []
    for ruta in rutas:
        archivos = sorted(ruta.glob("*.pdf")) if ruta.is_dir() else [ruta]
        carpeta = ruta if ruta.is_dir() else ruta.parent
        encontrados += [(a, CARPETAS.get(carpeta.name)) for a in archivos]
    return encontrados


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    logging.disable(logging.CRITICAL)  # pdfminer registra fragmentos del documento
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("rutas", nargs="*", type=Path, help="PDFs o carpetas")
    args = parser.parse_args(argv)
    rutas = args.rutas or [ROOT / "data" / "real" / "csf", ROOT / "data" / "real" / "curp"]
    pdfs = _pdfs([r for r in rutas if r.exists()])
    if not pdfs:
        print("No se encontraron PDFs.")
        return 1
    for numero, (archivo, doc_type) in enumerate(pdfs, start=1):
        tipo = doc_type.value if doc_type else "tipo desconocido"
        print(f"\n===== Documento {numero} ({tipo}) =====")
        try:
            print("\n".join(esqueleto(archivo.read_bytes(), doc_type)))
        except Exception as error:  # el mensaje podría incluir contenido del documento
            print(f"No se pudo leer ({type(error).__name__}).")
    print("\nRevisa la salida antes de compartirla: no debería haber nombres ni datos.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
