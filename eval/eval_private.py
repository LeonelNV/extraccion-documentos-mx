"""Evalúa la ruta de texto con documentos REALES sin exponer sus datos.

Estructura (todo dentro de ``data/real/``, que git ignora y el hook bloquea)::

    data/real/curp/*.pdf        constancias de CURP descargadas de RENAPO
    data/real/csf/*.pdf         constancias de situación fiscal descargadas del SAT
    data/real/etiquetas.json    opcional: valores correctos, escritos a mano

``etiquetas.json``: ``{"curp/archivo.pdf": {"curp": "...", "nombre": "...", ...}, ...}``,
con los nombres de campo del formulario.

**Solo imprime conteos agregados.** Nunca imprime ni escribe valores extraídos, nombres de
archivo ni mensajes de error (pueden contener datos del documento): de un error solo cuenta
su tipo. No escribe nada a disco.

Sin etiquetas mide lo que se puede comprobar sin conocer la respuesta: si se encontró cada
campo, si los identificadores pasan su dígito verificador y si los datos del documento son
coherentes entre sí (nombre y fecha contra la CURP, RFC contra CURP, domicilio contra
SEPOMEX).
"""

import argparse
import json
import logging
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from docextract.evaluation import field_matches
from docextract.normalize import comparison_key, parse_date
from docextract.parsers import PARSERS, extract_text_route
from docextract.router import RouteKind
from docextract.schemas import DocType, ExtractedField
from docextract.validators import (
    PersonName,
    check_curp_consistency,
    check_rfc_against_curp,
    compare_names,
    validate_address,
    validate_curp,
    validate_rfc,
)
from docextract.validators.sepomex import SepomexCatalog

ROOT = Path(__file__).resolve().parents[1]
CARPETAS = {"curp": DocType.CURP, "csf": DocType.CSF}


@dataclass
class Conteo:
    """Pares (aciertos, total) por métrica. Solo números: nada que identifique a alguien."""

    metricas: dict[str, list[int]] = field(default_factory=dict)

    def add(self, nombre: str, ok: bool) -> None:
        par = self.metricas.setdefault(nombre, [0, 0])
        par[0] += int(ok)
        par[1] += 1


@dataclass
class Reporte:
    documentos: Counter[str] = field(default_factory=Counter)
    errores: Counter[str] = field(default_factory=Counter)
    por_tipo: dict[str, Conteo] = field(default_factory=dict)
    cruce: Conteo = field(default_factory=Conteo)
    con_etiquetas: bool = False

    def conteo(self, doc_type: DocType) -> Conteo:
        return self.por_tipo.setdefault(doc_type.value, Conteo())


def _valor(campos: dict[str, ExtractedField], nombre: str) -> str | None:
    extraido = campos.get(nombre)
    return extraido.value if extraido else None


def _sin_etiquetas(
    doc_type: DocType,
    campos: dict[str, ExtractedField],
    c: Conteo,
    catalog: SepomexCatalog | None,
) -> None:
    curp = _valor(campos, "curp")
    curp_ok = validate_curp(curp)
    c.add("CURP con dígito verificador válido", curp_ok.valid)
    nombre, paterno, materno = (
        _valor(campos, k) for k in ("nombre", "apellido_paterno", "apellido_materno")
    )
    if curp_ok.info is not None and nombre and paterno:
        coinciden = not check_curp_consistency(
            curp_ok.info, nombre=nombre, apellido_paterno=paterno, apellido_materno=materno
        )
        c.add("Nombre coherente con la CURP", coinciden)

    if doc_type is DocType.CURP:
        fecha = parse_date(_valor(campos, "fecha_nacimiento"))
        if curp_ok.info is not None:
            c.add(
                "Fecha de nacimiento coherente con la CURP", fecha == curp_ok.info.fecha_nacimiento
            )
        return

    rfc = _valor(campos, "rfc")
    c.add("RFC con dígito verificador válido", validate_rfc(rfc).valid)
    if rfc and curp:
        c.add("RFC coherente con la CURP", not check_rfc_against_curp(rfc, curp))
    if catalog is not None:
        domicilio = validate_address(
            catalog,
            codigo_postal=_valor(campos, "codigo_postal"),
            estado=_valor(campos, "estado"),
            ciudad=_valor(campos, "municipio"),
            colonia=_valor(campos, "colonia"),
        )
        codigos = {w.code.value for w in domicilio.warnings}
        c.add("CP existe en SEPOMEX", "CP_NO_EXISTE" not in codigos)
        if "CP_NO_EXISTE" not in codigos:
            c.add("Estado coherente con el CP", "CP_NO_COINCIDE_CON_ESTADO" not in codigos)
            c.add("Municipio coherente con el CP", "CP_NO_COINCIDE_CON_MUNICIPIO" not in codigos)
            c.add("Colonia encontrada en el CP", "COLONIA_NO_ENCONTRADA" not in codigos)


def evaluar(directorio: Path, *, catalog: SepomexCatalog | None = None) -> Reporte:
    reporte = Reporte()
    etiquetas_path = directorio / "etiquetas.json"
    etiquetas: dict[str, dict[str, str]] = {}
    if etiquetas_path.exists():
        try:
            etiquetas = json.loads(etiquetas_path.read_text(encoding="utf-8"))
            reporte.con_etiquetas = True
        except (OSError, ValueError) as error:
            reporte.errores[f"etiquetas.json: {type(error).__name__}"] += 1

    extraidos: dict[DocType, list[dict[str, ExtractedField]]] = {d: [] for d in CARPETAS.values()}
    for carpeta, doc_type in CARPETAS.items():
        c = reporte.conteo(doc_type)
        for path in sorted((directorio / carpeta).glob("*.pdf")):
            reporte.documentos[doc_type.value] += 1
            try:
                salida = extract_text_route(path.read_bytes(), doc_type)
            except Exception as error:  # solo se cuenta el tipo
                reporte.errores[type(error).__name__] += 1
                continue
            c.add("Va por la ruta de texto", salida.route.kind is RouteKind.TEXT)
            if salida.classification is not None:
                c.add(
                    "Clasificado como el tipo correcto", salida.classification.doc_type == doc_type
                )
            if salida.result is None:
                continue
            campos = salida.result.fields
            extraidos[doc_type].append(campos)
            for nombre in PARSERS[doc_type].fields:
                c.add(f"Encontrado: {nombre}", _valor(campos, nombre) is not None)
            _sin_etiquetas(doc_type, campos, c, catalog)

            verdad = etiquetas.get(f"{carpeta}/{path.name}")
            if verdad:
                for nombre, esperado in verdad.items():
                    if nombre in PARSERS[doc_type].fields:
                        c.add(
                            f"Correcto (etiquetas): {nombre}",
                            field_matches(nombre, _valor(campos, nombre), esperado),
                        )

    # Cruce entre documentos: solo si hay exactamente una CURP y una CSF (de la misma persona).
    curps, csfs = extraidos[DocType.CURP], extraidos[DocType.CSF]
    if len(curps) == 1 and len(csfs) == 1:
        a, b = curps[0], csfs[0]
        reporte.cruce.add(
            "Misma CURP en la constancia CURP y en la CSF", _valor(a, "curp") == _valor(b, "curp")
        )
        persona = [
            PersonName(
                nombre=_valor(x, "nombre"),
                apellido_paterno=_valor(x, "apellido_paterno"),
                apellido_materno=_valor(x, "apellido_materno"),
            )
            for x in (a, b)
        ]
        reporte.cruce.add("Mismo nombre en ambos documentos", not compare_names(*persona))
        # Sin tolerancia: dos nombres pegados ("JUANCARLOS" contra "JUAN CARLOS") pasan la
        # comparación difusa, pero no esta.
        reporte.cruce.add(
            "Mismo nombre, idéntico palabra por palabra",
            all(
                comparison_key(_valor(a, k) or "") == comparison_key(_valor(b, k) or "")
                for k in ("nombre", "apellido_paterno", "apellido_materno")
            ),
        )
    return reporte


def imprimir(reporte: Reporte) -> None:
    print("Evaluación con documentos reales (solo conteos; ningún dato sale de este equipo)")
    print()
    total = sum(reporte.documentos.values())
    if not total:
        print("No se encontraron PDFs en data/real/curp/ ni en data/real/csf/.")
    for doc_type, conteo in reporte.por_tipo.items():
        if not reporte.documentos[doc_type]:
            continue
        print(f"== {doc_type.upper()}: {reporte.documentos[doc_type]} documento(s)")
        for nombre, (ok, n) in conteo.metricas.items():
            print(f"  {ok:3d}/{n:<3d}  {nombre}")
        print()
    if reporte.cruce.metricas:
        print("== Cruce entre documentos")
        for nombre, (ok, n) in reporte.cruce.metricas.items():
            print(f"  {ok:3d}/{n:<3d}  {nombre}")
        print()
    if not reporte.con_etiquetas:
        print("Sin etiquetas.json: solo se midieron campos encontrados y coherencia.")
    if reporte.errores:
        print("Errores (solo el tipo):")
        for tipo, n in reporte.errores.items():
            print(f"  {n:3d}  {tipo}")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    logging.disable(logging.CRITICAL)  # ninguna biblioteca escribe nada del documento
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dir", type=Path, default=ROOT / "data" / "real")
    args = parser.parse_args(argv)

    try:
        catalog = SepomexCatalog.load_default()
    except FileNotFoundError:
        catalog = None
        print("(Sin catálogo de SEPOMEX: no se valida el domicilio. Usa `make sepomex`.)\n")
    imprimir(evaluar(args.dir, catalog=catalog))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
