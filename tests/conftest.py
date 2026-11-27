"""Fixtures compartidas.

El catálogo de SEPOMEX no se puede redistribuir, así que las pruebas usan un catálogo
**ficticio** (CPs, municipios y asentamientos inventados) con el mismo formato que el
archivo oficial: Latin-1, delimitado por "|", con una línea de aviso y una de encabezados.
"""

import zipfile
from pathlib import Path

import pytest

from docextract.validators.sepomex import COLUMNS, ENCODING, SepomexCatalog

AVISO = "Catálogo ficticio para pruebas: no son datos de SEPOMEX."

# d_codigo | d_asenta | d_tipo_asenta | D_mnpio | d_estado | d_ciudad | c_estado | c_mnpio | d_zona
_FILAS = """
63901|Centro|Colonia|Municipio Uno|Nayarit|Ciudad Ficticia|18|101|Urbano
63901|Los Fresnos|Fraccionamiento|Municipio Uno|Nayarit|Ciudad Ficticia|18|101|Urbano
63901|San José del Valle|Pueblo|Municipio Uno|Nayarit|Ciudad Ficticia|18|101|Urbano
63901|Lomas Altas|Colonia|Municipio Uno|Nayarit|Ciudad Ficticia|18|101|Urbano
63902|La Peña|Ejido|Municipio Uno|Nayarit||18|101|Rural
01901|Jardines del Sur|Colonia|Municipio Dos|Aguascalientes|Aguascalientes|01|102|Urbano
"""
FILAS_FICTICIAS = tuple(tuple(linea.split("|")) for linea in _FILAS.strip().splitlines())


def _linea(fila: tuple[str, ...]) -> str:
    cp, asenta, tipo, mnpio, estado, ciudad, c_estado, c_mnpio, zona = fila
    valores = {
        "d_codigo": cp,
        "d_asenta": asenta,
        "d_tipo_asenta": tipo,
        "D_mnpio": mnpio,
        "d_estado": estado,
        "d_ciudad": ciudad,
        "d_CP": cp,
        "c_estado": c_estado,
        "c_oficina": cp,
        "c_CP": "",
        "c_tipo_asenta": "09",
        "c_mnpio": c_mnpio,
        "id_asenta_cpcons": "0001",
        "d_zona": zona,
        "c_cve_ciudad": "01" if ciudad else "",
    }
    return "|".join(valores[c] for c in COLUMNS)


def sepomex_text(filas: tuple[tuple[str, ...], ...] = FILAS_FICTICIAS) -> str:
    return "\r\n".join([AVISO, "|".join(COLUMNS), *(_linea(f) for f in filas)]) + "\r\n"


@pytest.fixture
def sepomex_txt(tmp_path: Path) -> Path:
    path = tmp_path / "CPdescarga.txt"
    path.write_bytes(sepomex_text().encode(ENCODING))
    return path


@pytest.fixture
def sepomex_zip(tmp_path: Path, sepomex_txt: Path) -> Path:
    path = tmp_path / "CPdescargatxt.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.write(sepomex_txt, arcname="CPdescarga.txt")
    return path


@pytest.fixture
def catalogo(sepomex_txt: Path) -> SepomexCatalog:
    return SepomexCatalog.from_file(sepomex_txt)
