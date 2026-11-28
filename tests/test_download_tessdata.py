"""Pruebas de scripts/download_tessdata.py sin red: la descarga usa archivos locales."""

import hashlib
from pathlib import Path

import pytest

import download_tessdata
from download_tessdata import Variante, descargar


def _variante(contenido: dict[str, bytes]) -> Variante:
    return Variante(
        repo="tessdata_prueba",
        commit="0" * 40,
        sha256={k: hashlib.sha256(v).hexdigest() for k, v in contenido.items()},
    )


def _fetch(contenido: dict[str, bytes], llamadas: list[str]):
    def fetch(url: str, destino: Path) -> None:
        llamadas.append(url)
        destino.write_bytes(contenido[url.rsplit("/", 1)[1]])

    return fetch


def test_descarga_verifica_y_no_repite(tmp_path: Path) -> None:
    contenido = {"spa.traineddata": b"modelo es", "eng.traineddata": b"modelo en"}
    variante = _variante(contenido)
    llamadas: list[str] = []
    fetch = _fetch(contenido, llamadas)

    assert descargar(variante, tmp_path, fetch=fetch) == ["spa.traineddata", "eng.traineddata"]
    assert (tmp_path / "spa.traineddata").read_bytes() == b"modelo es"
    assert llamadas[0].endswith(f"/tessdata_prueba/{'0' * 40}/spa.traineddata")

    # Con el SHA-256 correcto ya no se vuelve a bajar.
    assert descargar(variante, tmp_path, fetch=fetch) == []
    assert len(llamadas) == 2


def test_hash_incorrecto_no_deja_el_archivo(tmp_path: Path) -> None:
    variante = _variante({"spa.traineddata": b"el bueno"})
    malo = {"spa.traineddata": b"alterado"}
    with pytest.raises(RuntimeError, match="no coincide"):
        descargar(variante, tmp_path, fetch=_fetch(malo, []))
    assert sorted(p.name for p in tmp_path.iterdir()) == []


def test_archivo_local_alterado_se_reemplaza(tmp_path: Path) -> None:
    contenido = {"spa.traineddata": b"modelo es"}
    (tmp_path / "spa.traineddata").write_bytes(b"corrupto")
    assert descargar(_variante(contenido), tmp_path, fetch=_fetch(contenido, [])) == [
        "spa.traineddata"
    ]
    assert (tmp_path / "spa.traineddata").read_bytes() == b"modelo es"


def test_variantes_fijadas() -> None:
    for variante in download_tessdata.VARIANTES.values():
        assert len(variante.commit) == 40
        assert set(variante.sha256) == {"spa.traineddata", "eng.traineddata", "osd.traineddata"}
        assert all(len(h) == 64 for h in variante.sha256.values())
