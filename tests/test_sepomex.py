"""Pruebas del catálogo de SEPOMEX y de la validación de domicilios.

Usan el catálogo ficticio de ``conftest.py``. Las pruebas marcadas al final corren contra el
catálogo real solo si está descargado (``make sepomex``); en CI se omiten.
"""

import zipfile
from collections import defaultdict
from pathlib import Path

import pytest

from conftest import FILAS_FICTICIAS, sepomex_text
from docextract.config import ValidationConfig
from docextract.entidades import ENTIDADES
from docextract.schemas import WarningCode
from docextract.validators import sepomex
from docextract.validators.sepomex import (
    SepomexCatalog,
    SepomexNotAvailableError,
    read_sepomex,
    validate_address,
)


def _codes(result: sepomex.AddressValidation) -> list[WarningCode]:
    return [w.code for w in result.warnings]


# ---------------------------------------------------------------------------
# Lectura del archivo
# ---------------------------------------------------------------------------
def test_lee_txt_y_zip_igual(sepomex_txt: Path, sepomex_zip: Path) -> None:
    desde_txt, desde_zip = read_sepomex(sepomex_txt), read_sepomex(sepomex_zip)
    assert desde_txt == desde_zip
    assert len(desde_txt) == len(FILAS_FICTICIAS)


def test_decodifica_latin1(sepomex_txt: Path) -> None:
    nombres = {a.nombre for a in read_sepomex(sepomex_txt)}
    assert "San José del Valle" in nombres
    assert "La Peña" in nombres


def test_archivo_inexistente(tmp_path: Path) -> None:
    with pytest.raises(SepomexNotAvailableError):
        read_sepomex(tmp_path / "no-existe.zip")


def test_archivo_sin_encabezados(tmp_path: Path) -> None:
    path = tmp_path / "otro.txt"
    path.write_text("hola|mundo\n1|2\n", encoding="latin-1")
    with pytest.raises(ValueError, match="encabezados"):
        read_sepomex(path)


def test_fila_con_columnas_de_mas(tmp_path: Path) -> None:
    path = tmp_path / "roto.txt"
    path.write_bytes((sepomex_text() + "63901|extra\n").encode("latin-1"))
    with pytest.raises(ValueError, match="columnas"):
        read_sepomex(path)


def test_zip_con_dos_txt(tmp_path: Path, sepomex_txt: Path) -> None:
    path = tmp_path / "doble.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.write(sepomex_txt, arcname="a.txt")
        archive.write(sepomex_txt, arcname="b.txt")
    with pytest.raises(ValueError, match="exactamente un"):
        read_sepomex(path)


def test_catalogo_por_codigo_postal(catalogo: SepomexCatalog) -> None:
    assert len(catalogo) == 3
    assert "63901" in catalogo
    assert "99999" not in catalogo
    assert len(catalogo.lookup("63901")) == 4
    assert catalogo.lookup("99999") == ()


def test_load_default_usa_la_variable_de_entorno(
    sepomex_zip: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sepomex._load_cached.cache_clear()
    monkeypatch.setenv(sepomex.ENV_VAR, str(sepomex_zip))
    try:
        assert len(SepomexCatalog.load_default()) == 3
    finally:
        sepomex._load_cached.cache_clear()


def test_load_default_sin_catalogo_explica_como_descargarlo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sepomex._load_cached.cache_clear()
    monkeypatch.setenv(sepomex.ENV_VAR, str(tmp_path / "no-existe.zip"))
    try:
        with pytest.raises(SepomexNotAvailableError, match="make sepomex"):
            SepomexCatalog.load_default()
    finally:
        sepomex._load_cached.cache_clear()


# ---------------------------------------------------------------------------
# Validación de domicilios
# ---------------------------------------------------------------------------
def test_domicilio_correcto(catalogo: SepomexCatalog) -> None:
    result = validate_address(
        catalogo,
        codigo_postal="63901",
        estado="Nay.",
        ciudad="Municipio Uno",
        colonia="Col. Centro",
    )
    assert result.warnings == ()
    assert result.codigo_postal == "63901"
    assert result.estado_catalogo == "Nayarit"
    assert result.municipio_catalogo == "Municipio Uno"
    assert result.colonia_catalogo == "Centro"


def test_la_ciudad_puede_coincidir_con_d_ciudad(catalogo: SepomexCatalog) -> None:
    result = validate_address(catalogo, codigo_postal="63901", ciudad="CIUDAD FICTICIA")
    assert result.warnings == ()


@pytest.mark.parametrize(
    ("colonia", "oficial"),
    [
        ("LOS FRESNOS", "Los Fresnos"),
        ("Fracc. Los Fresnoz", "Los Fresnos"),  # error de OCR
        ("Fresnos", "Los Fresnos"),  # nombre parcial
        ("SAN JOSE DEL VALLE", "San José del Valle"),
        ("Lomas Altas", "Lomas Altas"),
    ],
)
def test_colonia_tolerante(catalogo: SepomexCatalog, colonia: str, oficial: str) -> None:
    result = validate_address(catalogo, codigo_postal="63901", colonia=colonia)
    assert result.warnings == ()
    assert result.colonia_catalogo == oficial


def test_colonia_no_encontrada_sugiere_las_mas_parecidas(catalogo: SepomexCatalog) -> None:
    result = validate_address(catalogo, codigo_postal="63901", colonia="Valle Verde")
    assert _codes(result) == [WarningCode.COLONIA_NO_ENCONTRADA]
    assert result.colonia_catalogo is None
    assert len(result.sugerencias_colonia) == 3
    assert result.sugerencias_colonia[0] == "San José del Valle"


@pytest.mark.parametrize(
    ("codigo_postal", "mensaje"),
    [("99999", "no existe"), ("ABCDE", "5 dígitos"), (None, "5 dígitos")],
)
def test_cp_invalido_o_inexistente(
    catalogo: SepomexCatalog, codigo_postal: str | None, mensaje: str
) -> None:
    result = validate_address(catalogo, codigo_postal=codigo_postal, estado="Nayarit")
    assert _codes(result) == [WarningCode.CP_NO_EXISTE]
    assert mensaje in result.warnings[0].message


def test_cp_de_cuatro_digitos_se_completa(catalogo: SepomexCatalog) -> None:
    result = validate_address(catalogo, codigo_postal="1901", estado="Aguascalientes")
    assert result.codigo_postal == "01901"
    assert result.warnings == ()


@pytest.mark.parametrize("estado", ["Jalisco", "Narnia"])
def test_estado_que_no_corresponde(catalogo: SepomexCatalog, estado: str) -> None:
    result = validate_address(catalogo, codigo_postal="63901", estado=estado)
    assert _codes(result) == [WarningCode.CP_NO_COINCIDE_CON_ESTADO]


def test_municipio_que_no_corresponde(catalogo: SepomexCatalog) -> None:
    result = validate_address(catalogo, codigo_postal="63901", ciudad="Municipio Dos Mil")
    assert _codes(result) == [WarningCode.CP_NO_COINCIDE_CON_MUNICIPIO]


def test_campos_no_extraidos_no_se_validan(catalogo: SepomexCatalog) -> None:
    assert validate_address(catalogo, codigo_postal="63902").warnings == ()


def test_umbral_de_colonia_configurable(catalogo: SepomexCatalog) -> None:
    estricto = ValidationConfig(colonia_similarity_threshold=0.99)
    result = validate_address(catalogo, codigo_postal="63901", colonia="Fresnos", config=estricto)
    assert _codes(result) == [WarningCode.COLONIA_NO_ENCONTRADA]


def test_los_mensajes_no_incluyen_el_domicilio(catalogo: SepomexCatalog) -> None:
    result = validate_address(
        catalogo, codigo_postal="63901", estado="Jalisco", ciudad="Otra", colonia="Valle Verde"
    )
    assert len(result.warnings) == 3
    for warning in result.warnings:
        for valor in ("63901", "Jalisco", "Otra", "Valle Verde"):
            assert valor not in warning.message


# ---------------------------------------------------------------------------
# Catálogo real (solo si está descargado)
# ---------------------------------------------------------------------------
_REAL = SepomexCatalog.default_path()
requiere_catalogo_real = pytest.mark.skipif(
    not _REAL.exists(), reason="catálogo de SEPOMEX no descargado (make sepomex)"
)


@pytest.fixture(scope="module")
def asentamientos_reales() -> list[sepomex.Asentamiento]:
    return read_sepomex(_REAL)


@requiere_catalogo_real
def test_catalogo_real_tiene_la_forma_esperada(
    asentamientos_reales: list[sepomex.Asentamiento],
) -> None:
    assert len(asentamientos_reales) > 100_000
    assert all(
        len(a.codigo_postal) == 5 and a.codigo_postal.isdigit() for a in asentamientos_reales
    )
    estados_por_cp: dict[str, set[str]] = defaultdict(set)
    for a in asentamientos_reales:
        estados_por_cp[a.codigo_postal].add(a.clave_estado)
    assert len(estados_por_cp) > 30_000
    # La validación asume que cada CP pertenece a un solo estado.
    assert all(len(estados) == 1 for estados in estados_por_cp.values())


@requiere_catalogo_real
def test_catalogo_de_entidades_coincide_con_sepomex(
    asentamientos_reales: list[sepomex.Asentamiento],
) -> None:
    en_sepomex = {(a.clave_estado, a.estado) for a in asentamientos_reales}
    nuestro = {(e.clave_inegi, e.nombre) for e in ENTIDADES}
    assert en_sepomex == nuestro
