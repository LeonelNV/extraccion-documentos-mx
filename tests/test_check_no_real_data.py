"""Pruebas del bloqueo de documentos reales (scripts/check_no_real_data.py)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from check_no_real_data import check, check_files, check_history, detect_content, main

# Encabezados mínimos de cada formato. El relleno con NUL hace que git los trate como binarios.
PADDING = b"\x00" * 32
SIGNATURES = {
    "PDF": b"%PDF-1.7\n",
    "PNG": b"\x89PNG\r\n\x1a\n",
    "JPEG": b"\xff\xd8\xff\xe0",
    "GIF": b"GIF89a",
    "TIFF": b"II*\x00",
    "WEBP": b"RIFF\x24\x00\x00\x00WEBPVP8 ",
    "HEIF/AVIF": b"\x00\x00\x00\x18ftypheic",
    "JPEG 2000": b"\x00\x00\x00\x0cjP  \r\n\x87\n",
    "BMP": b"BM\x36\x00\x0c\x00\x00\x00\x00\x00",
}


# ---------------------------------------------------------------------------
# Detección por contenido
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(("kind", "head"), SIGNATURES.items())
def test_detecta_cada_formato(kind: str, head: bytes) -> None:
    assert detect_content(head + PADDING) == kind


@pytest.mark.parametrize(
    "head",
    [
        b"",
        b"print('hola')\n",
        b"# Documento\nEl encabezado de un PDF empieza con b'%PDF-1.4'.\n",
        b"BMW es una marca de autos\n",
    ],
)
def test_texto_comun_no_se_confunde_con_documento(head: bytes) -> None:
    assert detect_content(head) is None


def test_pdf_con_basura_antes_del_encabezado() -> None:
    assert detect_content(b"\x1b%-12345X@PJL\n%PDF-1.4\n") == "PDF"


# ---------------------------------------------------------------------------
# Reglas por ruta
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "path",
    [
        "data/real/notas.txt",
        "data/real/sub/ine.pdf",
        "Data/Real/curp.pdf",
        "data\\real\\csf.pdf",
    ],
)
def test_bloquea_todo_lo_que_esta_en_data_real(path: str) -> None:
    assert check(path, b"texto") is not None


@pytest.mark.parametrize(
    "path",
    ["data/synthetic/samples/curp_0001.pdf", "docs/img/arquitectura.png", "./docs/img/fig.jpg"],
)
def test_permite_pdfs_e_imagenes_en_carpetas_permitidas(path: str) -> None:
    assert check(path, SIGNATURES["PDF"]) is None


@pytest.mark.parametrize(
    "path",
    ["ine.pdf", "src/docextract/FOTO.JPG", "docs/comprobante.png", "Data/Synthetic/curp.pdf"],
)
def test_bloquea_pdfs_e_imagenes_fuera_de_carpetas_permitidas(path: str) -> None:
    violation = check(path, None)
    assert violation is not None
    assert "fuera de data/synthetic/" in violation.reason


@pytest.mark.parametrize("kind", ["PDF", "PNG", "JPEG", "HEIF/AVIF"])
def test_bloquea_documentos_renombrados(kind: str) -> None:
    violation = check("tests/fixtures/ine.bin", SIGNATURES[kind] + PADDING)
    assert violation is not None
    assert kind in violation.reason


def test_permite_codigo_y_texto() -> None:
    assert check("src/docextract/schemas.py", b'"""Esquemas."""\n') is None


# ---------------------------------------------------------------------------
# Modo archivos (pre-commit) y salida del programa
# ---------------------------------------------------------------------------
def test_check_files_lee_el_contenido_real(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs" / "img").mkdir(parents=True)
    (tmp_path / "docs" / "img" / "figura.png").write_bytes(SIGNATURES["PNG"] + PADDING)
    (tmp_path / "datos.bin").write_bytes(SIGNATURES["PDF"] + PADDING)
    (tmp_path / "notas.md").write_text("# Notas\n", encoding="utf-8")

    violations = check_files(["docs/img/figura.png", "datos.bin", "notas.md"])

    assert [v.path for v in violations] == ["datos.bin"]


def test_check_files_aplica_reglas_de_ruta_aunque_el_archivo_no_exista() -> None:
    assert [v.path for v in check_files(["data/real/borrado.pdf"])] == ["data/real/borrado.pdf"]


def test_main_falla_y_explica_por_que(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["data/real/ine.pdf"]) == 1
    err = capsys.readouterr().err
    assert "Commit bloqueado" in err
    assert "data/real/ine.pdf" in err


def test_main_sin_archivos_pasa() -> None:
    assert main([]) == 0


def test_main_no_acepta_history_y_archivos_juntos() -> None:
    with pytest.raises(SystemExit):
        main(["--history", "a.pdf"])


# ---------------------------------------------------------------------------
# Modo historial (CI)
# ---------------------------------------------------------------------------
requires_git = pytest.mark.skipif(shutil.which("git") is None, reason="git no disponible")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=pruebas",
            "-c",
            "user.email=pruebas@example.com",
            "-c",
            "core.autocrlf=false",
            *args,
        ],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    (tmp_path / "README.md").write_text("# Repo de prueba\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "inicial")
    return tmp_path


@requires_git
def test_historial_limpio(repo: Path) -> None:
    samples = repo / "data" / "synthetic" / "samples"
    samples.mkdir(parents=True)
    (samples / "curp_0001.pdf").write_bytes(SIGNATURES["PDF"] + PADDING)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "muestra sintética")

    assert check_history(repo) == []


@requires_git
def test_historial_encuentra_documentos_ya_borrados(repo: Path) -> None:
    carpeta = repo / "carpeta con espacio"
    carpeta.mkdir()
    (carpeta / "credencial_año.bin").write_bytes(SIGNATURES["JPEG"] + PADDING)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "agrega por error")
    _git(repo, "rm", "-rq", "carpeta con espacio")
    _git(repo, "commit", "-qm", "lo borra, pero sigue en el historial")

    violations = check_history(repo)

    assert [v.path for v in violations] == ["carpeta con espacio/credencial_año.bin"]
    assert "JPEG" in violations[0].reason


@requires_git
def test_historial_revisa_todas_las_ramas(repo: Path) -> None:
    _git(repo, "switch", "-qc", "otra-rama")
    (repo / "data" / "real").mkdir(parents=True)
    (repo / "data" / "real" / "csf.txt").write_text("texto", encoding="utf-8")
    _git(repo, "add", "-f", "-A")
    _git(repo, "commit", "-qm", "en otra rama")
    _git(repo, "switch", "-q", "-")

    assert [v.path for v in check_history(repo)] == ["data/real/csf.txt"]
