"""Pruebas del generador sintético.

Usan el catálogo ficticio de SEPOMEX (``conftest.py``) y una resolución baja para que sean
rápidas. Todas las CURPs y RFCs las genera el código a partir de nombres inventados.
"""

import random
import re
from datetime import date
from pathlib import Path

import pypdfium2 as pdfium
import pytest
from faker import Faker

from docextract.dataset import DatasetInfo, Modality, PersonTruth
from docextract.normalize import parse_date
from docextract.schemas import DocType, WarningCode
from docextract.validators import (
    check_comprobante_age,
    check_curp_consistency,
    validate_address,
    validate_curp,
    validate_rfc,
)
from docextract.validators.sepomex import SepomexCatalog
from synth import __main__ as cli
from synth.config import DEFAULT_CONFIG_PATH, SynthConfig, load_config
from synth.generate import (
    DOC_ORDER,
    PersonaPlan,
    expected_form,
    generate_dataset,
    generate_person,
    samples_plan,
)
from synth.persona import generate_persona
from synth.render import comprobante, csf, curp, ine
from synth.render.common import DocContext

# Rápido: resolución baja y todas las modalidades posibles.
CONFIG = SynthConfig(dpi=60)


def _pdf_text(pdf: bytes) -> str:
    document = pdfium.PdfDocument(pdf)
    try:
        text = document[0].get_textpage().get_text_range()
    finally:
        document.close()
    return re.sub(r"\s+", " ", text)


def _personas(catalogo: SepomexCatalog, n: int, config: SynthConfig = CONFIG) -> list:
    personas = []
    for seed in range(n):
        faker = Faker("es_MX")
        faker.seed_instance(seed)
        personas.append(generate_persona(f"p{seed}", random.Random(seed), faker, catalogo, config))
    return personas


# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------
def test_config_toml_coincide_con_los_valores_por_defecto() -> None:
    assert load_config(DEFAULT_CONFIG_PATH) == SynthConfig()


def test_overrides_de_config() -> None:
    assert load_config(DEFAULT_CONFIG_PATH, seed=7).seed == 7


@pytest.mark.parametrize(
    "datos",
    [
        {"modalidades": {"curp": [0.5, 0.5, 0.5]}},
        {"comprobante": {"plantillas_train": ["luz"], "plantilla_no_vista": "luz"}},
        {"tasas": {"sin_materno": 1.5}},
        {"campo_desconocido": 1},
    ],
)
def test_config_invalida(datos: dict) -> None:
    with pytest.raises(ValueError):
        SynthConfig.model_validate(datos)


# ---------------------------------------------------------------------------
# Personas
# ---------------------------------------------------------------------------
def test_personas_coherentes(catalogo: SepomexCatalog) -> None:
    for p in _personas(catalogo, 150):
        result = validate_curp(p.curp)
        assert result.valid, p
        info = result.info
        assert info is not None
        assert info.fecha_nacimiento == p.fecha_nacimiento
        assert info.sexo == p.sexo
        assert info.clave_entidad == p.clave_entidad_nacimiento
        assert (
            check_curp_consistency(
                info,
                nombre=p.nombre,
                apellido_paterno=p.apellido_paterno,
                apellido_materno=p.apellido_materno,
                fecha_nacimiento=p.fecha_nacimiento,
                sexo=p.sexo,
            )
            == []
        )
        assert validate_rfc(p.rfc).valid
        d = p.domicilio
        address = validate_address(
            catalogo,
            codigo_postal=d.codigo_postal,
            estado=d.estado,
            ciudad=d.ciudad,
            colonia=d.colonia,
        )
        assert address.warnings == (), p
        edad = (CONFIG.reference_date - p.fecha_nacimiento).days / 365.25
        assert 18 <= edad <= 70.1


def test_casos_limite_con_tasa_1(catalogo: SepomexCatalog) -> None:
    tasas = CONFIG.tasas.model_copy(
        update={
            "sin_materno": 1.0,
            "sexo_x": 1.0,
            "nacido_extranjero": 1.0,
            "nombre_compuesto": 1.0,
        }
    )
    config = CONFIG.model_copy(update={"tasas": tasas})
    for p in _personas(catalogo, 10, config):
        assert p.apellido_materno == ""
        assert p.sexo == "X"
        assert p.clave_entidad_nacimiento == "NE"
        assert " " in p.nombre
        assert {"sin_materno", "sexo_x", "nacido_extranjero", "nombre_compuesto"} <= set(p.tags)


def test_formulario_esperado_en_formato_fea(catalogo: SepomexCatalog) -> None:
    for p in _personas(catalogo, 30):
        form = expected_form(p)
        for campo in (
            "nombre",
            "apellido_paterno",
            "apellido_materno",
            "calle",
            "colonia",
            "ciudad",
            "estado",
        ):
            valor = form[campo]
            assert valor == valor.upper()
            assert not set("ÁÉÍÓÚÜáéíóúü") & set(valor), valor
        assert form["fecha_nacimiento"] == p.fecha_nacimiento.isoformat()


# ---------------------------------------------------------------------------
# Plantillas
# ---------------------------------------------------------------------------
# Campos que la plantilla no imprime como una sola cadena.
_COMPUESTOS = {csf.TEMPLATE: {"calle"}}


def _renders(catalogo: SepomexCatalog):
    for p in _personas(catalogo, 6):
        ctx = DocContext(
            p, p.nombre, p.apellido_paterno, p.apellido_materno, p.domicilio,
            CONFIG.reference_date, date(2026, 10, 5), random.Random(1),
        )  # fmt: skip
        yield curp.TEMPLATE, curp.render(ctx)
        yield ine.TEMPLATE, ine.render(ctx)
        yield csf.TEMPLATE, csf.render(ctx)
        for diseno in comprobante.DISENOS:
            yield comprobante.template_name(diseno), comprobante.render(ctx, diseno)


def test_cada_campo_esta_impreso_en_la_capa_de_texto(catalogo: SepomexCatalog) -> None:
    for template, rendered in _renders(catalogo):
        text = _pdf_text(rendered.pdf)
        for campo, valor in rendered.fields.items():
            if valor and campo not in _COMPUESTOS.get(template, set()):
                assert valor in text, (template, campo, valor)


def test_la_marca_de_agua_no_contamina_la_capa_de_texto(catalogo: SepomexCatalog) -> None:
    for _, rendered in _renders(catalogo):
        assert "SPECIMEN" not in _pdf_text(rendered.pdf)
        document = pdfium.PdfDocument(rendered.pdf)
        assert "MUESTRA" in document.get_metadata_dict()["Title"]
        document.close()


def test_curp_con_la_estructura_de_la_constancia_real(catalogo: SepomexCatalog) -> None:
    """Como la real: el título es imagen, el nombre va completo en un renglón y no imprime
    sexo, fecha ni entidad de nacimiento ni nacionalidad. El parser divide el nombre y
    deduce el resto de la CURP."""
    from docextract.parsers import extract_text_route
    from docextract.parsers.base import Confianza

    for template, rendered in _renders(catalogo):
        if template != curp.TEMPLATE:
            continue
        text = _pdf_text(rendered.pdf)
        assert "CONSTANCIA DE LA CLAVE" not in text.upper()
        for etiqueta in ("Sexo", "Fecha de nacimiento", "Nacionalidad", "Primer apellido"):
            assert etiqueta.upper() not in text.upper(), etiqueta
        assert not {"sexo", "fecha_nacimiento", "nacionalidad"} & set(rendered.fields)
        campos = extract_text_route(rendered.pdf, DocType.CURP).result.fields
        for nombre in ("curp", "nombre", "apellido_paterno", "apellido_materno"):
            assert (campos[nombre].value or "") == rendered.fields[nombre], nombre
        for nombre in ("sexo", "fecha_nacimiento", "entidad_nacimiento"):
            assert campos[nombre].confidence == Confianza.DERIVADO, nombre


def test_las_fechas_impresas_se_pueden_leer(catalogo: SepomexCatalog) -> None:
    for template, rendered in _renders(catalogo):
        for campo in ("fecha_nacimiento", "fecha_emision"):
            if campo in rendered.fields:
                assert parse_date(rendered.fields[campo]) is not None, (template, campo)
        if template.startswith("comprobante_"):
            assert parse_date(rendered.fields["fecha_emision"]) == date(2026, 10, 5)


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------
def _plan_mixto() -> list[PersonaPlan]:
    foto = dict.fromkeys(DOC_ORDER, Modality.FOTO)
    escaneo = dict.fromkeys(DOC_ORDER, Modality.ESCANEO)
    digital = dict.fromkeys(DOC_ORDER, Modality.DIGITAL)
    return [
        PersonaPlan("train", 0, modalidades=digital),
        PersonaPlan("train", 1, modalidades=digital),
        PersonaPlan("val", 0, modalidades=escaneo),
        PersonaPlan("test", 0, modalidades=foto),
    ]


@pytest.fixture(scope="module")
def dataset(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, DatasetInfo]:
    # Catálogo ficticio construido aquí porque la fixture `catalogo` es por función.
    from conftest import sepomex_text

    folder = tmp_path_factory.mktemp("sepomex")
    (folder / "c.txt").write_bytes(sepomex_text().encode("latin-1"))
    catalog = SepomexCatalog.from_file(folder / "c.txt")
    root = tmp_path_factory.mktemp("synthetic")
    return root, generate_dataset(CONFIG, catalog, root, plan=_plan_mixto())


def test_estructura_del_dataset(dataset: tuple[Path, DatasetInfo]) -> None:
    root, info = dataset
    assert info.counts["train"]["personas"] == 2
    assert info.counts["test"]["documentos"] == 4
    assert (
        DatasetInfo.model_validate_json((root / "dataset.json").read_text(encoding="utf-8")) == info
    )
    for split, personas in (("train", 2), ("val", 1), ("test", 1)):
        lines = (root / split / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(lines) == personas * 4
    for path in root.rglob("ground_truth.json"):
        truth = PersonTruth.model_validate_json(path.read_text(encoding="utf-8"))
        for doc in truth.documents:
            assert (root / doc.pdf).exists()
            assert (doc.image is None) == (doc.modality is Modality.DIGITAL)
            if doc.image:
                assert (root / doc.image).exists()


def test_modalidades_y_capa_de_texto(dataset: tuple[Path, DatasetInfo]) -> None:
    root, _ = dataset
    for path in root.rglob("ground_truth.json"):
        truth = PersonTruth.model_validate_json(path.read_text(encoding="utf-8"))
        for doc in truth.documents:
            text = _pdf_text((root / doc.pdf).read_bytes())
            if doc.modality is Modality.DIGITAL:
                if doc.doc_type is DocType.CURP:
                    assert truth.form["curp"] in text
            else:
                assert text.strip() == "", "escaneo y foto no deben tener capa de texto"
                assert doc.augmentation


def test_misma_semilla_mismos_archivos(
    dataset: tuple[Path, DatasetInfo], tmp_path: Path, catalogo: SepomexCatalog
) -> None:
    root, _ = dataset
    otra = tmp_path / "otra"
    for plan in _plan_mixto():
        generate_person(plan, CONFIG, catalogo, otra)
    archivos = sorted(p.relative_to(otra) for p in otra.rglob("*") if p.is_file())
    assert archivos
    for rel in archivos:
        assert (otra / rel).read_bytes() == (root / rel).read_bytes(), rel


def test_otra_semilla_otros_datos(catalogo: SepomexCatalog, tmp_path: Path) -> None:
    a = generate_person(
        PersonaPlan("train", 0, modalidades=dict.fromkeys(DOC_ORDER, Modality.DIGITAL)),
        CONFIG,
        catalogo,
        tmp_path / "a",
    )
    otra = CONFIG.model_copy(update={"seed": CONFIG.seed + 1})
    b = generate_person(
        PersonaPlan("train", 0, modalidades=dict.fromkeys(DOC_ORDER, Modality.DIGITAL)),
        otra,
        catalogo,
        tmp_path / "b",
    )
    assert a.form["curp"] != b.form["curp"]


def test_plantilla_no_vista_solo_en_test(catalogo: SepomexCatalog, tmp_path: Path) -> None:
    comp = CONFIG.comprobante.model_copy(update={"fraccion_no_vista_test": 1.0})
    config = CONFIG.model_copy(update={"comprobante": comp})
    digital = dict.fromkeys(DOC_ORDER, Modality.DIGITAL)
    for split in ("train", "val", "test"):
        for i in range(4):
            truth = generate_person(
                PersonaPlan(split, i, modalidades=digital), config, catalogo, tmp_path
            )
            recibo = truth.documents[-1]
            assert recibo.doc_type is DocType.COMPROBANTE_DOMICILIO
            if split == "test":
                assert recibo.template == "comprobante_telefono"
                assert not recibo.template_seen_in_train
            else:
                assert recibo.template != "comprobante_telefono"
                assert recibo.template_seen_in_train


def test_inconsistencias_inyectadas(catalogo: SepomexCatalog, tmp_path: Path) -> None:
    tasas = CONFIG.tasas.model_copy(update={"inconsistencia": 1.0})
    config = CONFIG.model_copy(update={"tasas": tasas})
    digital = dict.fromkeys(DOC_ORDER, Modality.DIGITAL)
    vistas = set()
    for i in range(24):
        truth = generate_person(
            PersonaPlan("train", i, modalidades=digital), config, catalogo, tmp_path
        )
        inyectadas = [
            w
            for w in truth.expected_warnings
            if w.kind not in ("nacido_extranjero", "reglas_sat_renapo")
        ]
        assert len(inyectadas) == 1
        warning = inyectadas[0]
        vistas.add(warning.kind)
        docs = {d.doc_type: d for d in truth.documents}
        if warning.kind == "domicilio_ine_distinto":
            ine_doc = docs[DocType.INE].fields
            assert (ine_doc["calle"], ine_doc["numero_exterior"]) != (
                truth.form["calle"], truth.form["numero_exterior"]
            )  # fmt: skip
        elif warning.kind == "comprobante_antiguo":
            emision = parse_date(docs[DocType.COMPROBANTE_DOMICILIO].fields["fecha_emision"])
            codes = [w.code for w in check_comprobante_age(emision, today=config.reference_date)]
            assert codes == [WarningCode.COMPROBANTE_ANTIGUO]
        else:
            (doc_type,) = set(warning.docs) - {DocType.CURP}
            assert (
                docs[doc_type].fields["apellido_paterno"].upper() != truth.form["apellido_paterno"]
            )
    assert vistas == {"domicilio_ine_distinto", "comprobante_antiguo", "errata_nombre"}


def test_muestras_cubren_disenos_y_modalidades() -> None:
    plan = samples_plan()
    assert {p.comprobante for p in plan} == set(comprobante.DISENOS)
    modalidades = {m for p in plan for m in (p.modalidades or {}).values()}
    assert modalidades == set(Modality)


# ---------------------------------------------------------------------------
# Línea de comandos
# ---------------------------------------------------------------------------
def test_no_sobrescribe_sin_force(tmp_path: Path) -> None:
    (tmp_path / "train").mkdir()
    with pytest.raises(SystemExit, match="--force"):
        cli._prepare_output(tmp_path, force=False)


def test_force_solo_borra_lo_generado(tmp_path: Path) -> None:
    for name in ("train", "val", "test", "samples"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "x.txt").write_text("x")
    (tmp_path / "dataset.json").write_text("{}")
    cli._prepare_output(tmp_path, force=True)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["samples"]


# ---------------------------------------------------------------------------
# Reanudar una generación interrumpida
# ---------------------------------------------------------------------------
def test_reanudar_conserva_lo_completo_y_rehace_lo_danado(
    catalogo: SepomexCatalog, tmp_path: Path
) -> None:
    from synth.generate import load_complete

    foto = dict.fromkeys(DOC_ORDER, Modality.FOTO)
    plans = [PersonaPlan("train", i, modalidades=foto) for i in range(3)]
    generate_dataset(CONFIG, catalogo, tmp_path, plan=plans)
    originales = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.suffix in (".pdf", ".jpg")}

    # Simula un apagado inesperado: un JPG truncado, un PDF en ceros y una persona sin
    # ground_truth (se interrumpió a la mitad).
    persona0, persona1, persona2 = (tmp_path / "train" / p.persona_id for p in plans)
    jpg = persona0 / "ine.jpg"
    jpg.write_bytes(jpg.read_bytes()[:1000])
    pdf = persona1 / "curp.pdf"
    pdf.write_bytes(b"\x00" * pdf.stat().st_size)
    (persona2 / "ground_truth.json").unlink()
    intacto = persona2.parent / plans[0].persona_id / "curp.pdf"
    assert load_complete(plans[0], tmp_path) is None
    assert load_complete(plans[1], tmp_path) is None
    assert load_complete(plans[2], tmp_path) is None

    generate_dataset(CONFIG, catalogo, tmp_path, plan=plans, resume=True)
    for path, contenido in originales.items():
        assert path.read_bytes() == contenido, path  # determinista: mismos bytes
    assert all(load_complete(p, tmp_path) is not None for p in plans)
    assert intacto.exists()


def test_reanudar_exige_la_misma_configuracion(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="No hay una generación"):
        cli._check_resume(tmp_path, CONFIG.model_dump_json())
    (tmp_path / cli.RUN_FILE).write_text(CONFIG.model_dump_json(), encoding="utf-8")
    cli._check_resume(tmp_path, CONFIG.model_dump_json())
    otra = CONFIG.model_copy(update={"seed": 1})
    with pytest.raises(SystemExit, match="no coincide"):
        cli._check_resume(tmp_path, otra.model_dump_json())
