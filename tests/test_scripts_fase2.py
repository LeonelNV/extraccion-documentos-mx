"""Pruebas de los scripts de la fase 2 (sin red: la descarga real no se prueba en CI)."""

import io
import json
from datetime import date
from pathlib import Path

import pytest

import download_sepomex
import verificar_claves
from docextract.validators.curp import build_curp
from docextract.validators.rfc import build_rfc

PAGINA = """
<form name="Form1" method="post" action="CodigoPostal_Exportar.aspx" id="Form1">
<input type="hidden" name="__EVENTTARGET" id="__EVENTTARGET" value="" />
<input type="hidden" name="__VIEWSTATE" id="__VIEWSTATE" value="abc&amp;123" />
<input type="hidden" name="__VIEWSTATEGENERATOR" id="__VIEWSTATEGENERATOR" value="BE1A6D2E" />
<input type="hidden" name="__EVENTVALIDATION" id="__EVENTVALIDATION" value="xyz" />
<input id="rblTipo_1" type="radio" name="rblTipo" value="txt" />
</form>
"""


# ---------------------------------------------------------------------------
# download_sepomex
# ---------------------------------------------------------------------------
def test_parse_hidden_fields() -> None:
    campos = download_sepomex.parse_hidden_fields(PAGINA)
    assert campos == {
        "__EVENTTARGET": "",
        "__VIEWSTATE": "abc&123",
        "__VIEWSTATEGENERATOR": "BE1A6D2E",
        "__EVENTVALIDATION": "xyz",
    }


def test_build_form_pide_txt_de_todos_los_estados() -> None:
    form = download_sepomex.build_form(download_sepomex.parse_hidden_fields(PAGINA))
    assert form["cboEdo"] == "00"
    assert form["rblTipo"] == "txt"
    assert form["__VIEWSTATE"] == "abc&123"
    assert "btnDescarga.x" in form
    assert form["__LASTFOCUS"] == ""  # faltante en la página: se envía vacío


def test_build_form_falla_si_la_pagina_cambio() -> None:
    with pytest.raises(RuntimeError, match="__VIEWSTATE"):
        download_sepomex.build_form({})


def test_from_file_instala_y_escribe_metadatos(sepomex_zip: Path, tmp_path: Path) -> None:
    destino = tmp_path / "data" / "sepomex" / "CPdescargatxt.zip"
    codigo = download_sepomex.main(["--from-file", str(sepomex_zip), "--output", str(destino)])
    assert codigo == 0
    assert destino.read_bytes() == sepomex_zip.read_bytes()
    metadatos = json.loads((destino.parent / "metadata.json").read_text(encoding="utf-8"))
    assert metadatos["codigos_postales"] == 3
    assert metadatos["asentamientos"] == 6
    assert len(metadatos["sha256"]) == 64


def test_from_file_invalido_no_instala(tmp_path: Path) -> None:
    falso = tmp_path / "falso.txt"
    falso.write_text("no es el catálogo", encoding="utf-8")
    destino = tmp_path / "out" / "CPdescargatxt.zip"
    assert download_sepomex.main(["--from-file", str(falso), "--output", str(destino)]) == 1
    assert not destino.exists()


def test_no_descarga_si_ya_existe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    destino = tmp_path / "CPdescargatxt.zip"
    destino.write_bytes(b"ya estaba")

    def sin_red(_: Path) -> None:
        raise AssertionError("no debía descargar")

    monkeypatch.setattr(download_sepomex, "download", sin_red)
    assert download_sepomex.main(["--output", str(destino)]) == 0


# ---------------------------------------------------------------------------
# verificar_claves
# ---------------------------------------------------------------------------
def _claves() -> tuple[str, str]:
    datos = {
        "nombre": "Laura",
        "apellido_paterno": "Gómez",
        "apellido_materno": "Ruiz",
        "fecha_nacimiento": date(1991, 4, 7),
    }
    return build_curp(**datos, sexo="M", clave_entidad="NT"), build_rfc(**datos)  # type: ignore[arg-type]


def test_summarize_cuenta_por_tipo() -> None:
    curp, rfc = _claves()
    curp_mala = curp[:17] + str((int(curp[17]) + 1) % 10)
    conteo = verificar_claves.summarize(
        [curp, curp.lower(), curp_mala, rfc, "XAXX010101000", "123", ""]
    )
    assert conteo["CURP con dígito verificador correcto"] == 2
    assert conteo["CURP con dígito verificador INCORRECTO"] == 1
    assert conteo["RFC con dígito verificador correcto"] == 1
    assert conteo["RFC genérico (no cuenta)"] == 1
    assert conteo["Longitud distinta de 18 y 13 (ignorada)"] == 1


def test_main_nunca_imprime_las_claves(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    curp, rfc = _claves()
    monkeypatch.setattr("sys.stdin", io.StringIO(f"{curp}\n{rfc}\n"))
    assert verificar_claves.main() == 0
    salida = capsys.readouterr()
    for texto in (salida.out, salida.err):
        assert curp not in texto
        assert rfc not in texto
        assert curp[:10] not in texto
    assert "CURP con dígito verificador correcto" in salida.out
