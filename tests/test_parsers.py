"""Pruebas del router, el clasificador de texto y los parsers de CURP y CSF.

Las CURPs y RFCs las genera el código a partir de nombres inventados. Los formatos
"alternativos" (nombre en una línea, apellidos primero, etiquetas sin dos puntos) simulan
documentos reales que las plantillas sintéticas no producen.
"""

import random
from datetime import date
from pathlib import Path

import pytest
from faker import Faker

from docextract.classify import classify_text, verify_doc_type
from docextract.evaluation import field_matches
from docextract.parsers import PARSERS, extract_text_route
from docextract.parsers.base import Confianza, split_full_name
from docextract.parsers.csf import CsfParser
from docextract.parsers.curp import CurpParser
from docextract.router import InvalidPdfError, RouteKind, route
from docextract.schemas import DocType, WarningCode
from docextract.validators.curp import build_curp
from docextract.validators.rfc import build_rfc
from docextract.validators.sepomex import SepomexCatalog
from synth.config import SynthConfig
from synth.persona import generate_persona
from synth.render import csf, curp
from synth.render.common import DocContext
from test_layout import layout

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "synthetic" / "samples"
DIGITAL = SAMPLES / "train" / "train-00000"  # muestra con los 4 documentos digitales
FOTO = SAMPLES / "train" / "train-00001"  # muestra con los 4 documentos en foto


def _curp(nombre: str = "Juan Carlos", paterno: str = "Pérez", materno: str = "López") -> str:
    return build_curp(
        nombre=nombre,
        apellido_paterno=paterno,
        apellido_materno=materno,
        fecha_nacimiento=date(1990, 5, 17),
        sexo="H",
        clave_entidad="NT",
    )


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
def test_router_pdf_digital_va_por_texto() -> None:
    decision = route((DIGITAL / "curp.pdf").read_bytes())
    assert decision.kind is RouteKind.TEXT
    assert decision.alnum_chars > 100


def test_router_pdf_de_imagen_va_por_imagen() -> None:
    decision = route((FOTO / "ine.pdf").read_bytes())
    assert decision.kind is RouteKind.IMAGE
    assert decision.alnum_chars == 0


@pytest.mark.parametrize("data", [b"no soy un pdf", b"", b"%PDF-1.4\n%%EOF basura"])
def test_router_archivo_invalido(data: bytes) -> None:
    with pytest.raises(InvalidPdfError):
        route(data)


def test_error_del_router_no_incluye_el_contenido() -> None:
    pdf = (DIGITAL / "curp.pdf").read_bytes()
    with pytest.raises(InvalidPdfError) as info:
        route(pdf[: len(pdf) // 3])
    assert "CONSTANCIA" not in str(info.value)


# ---------------------------------------------------------------------------
# Clasificador de texto
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("archivo", "esperado"),
    [
        ("curp.pdf", DocType.CURP),
        ("csf.pdf", DocType.CSF),
        ("ine.pdf", DocType.INE),
        ("comprobante.pdf", DocType.COMPROBANTE_DOMICILIO),
    ],
)
def test_clasifica_las_muestras_digitales(archivo: str, esperado: DocType) -> None:
    result = classify_text(route((DIGITAL / archivo).read_bytes()).layout)
    assert result.doc_type is esperado
    assert result.confidence > 0.5


def test_texto_sin_palabras_clave_no_se_reconoce() -> None:
    result = classify_text(layout("Lista del supermercado", "Leche, pan y huevos"))
    assert result.doc_type is None
    warnings = verify_doc_type(DocType.CURP, result)
    assert [w.code for w in warnings] == [WarningCode.DOCUMENTO_NO_RECONOCIDO]


def test_documento_en_el_campo_equivocado() -> None:
    out = extract_text_route((DIGITAL / "csf.pdf").read_bytes(), DocType.CURP)
    assert out.result is not None
    assert WarningCode.DOCUMENTO_NO_RECONOCIDO in [w.code for w in out.result.warnings]


def test_sin_parser_o_por_imagen_no_hay_resultado() -> None:
    assert extract_text_route((DIGITAL / "ine.pdf").read_bytes(), DocType.INE).result is None
    assert extract_text_route((FOTO / "curp.pdf").read_bytes(), DocType.CURP).result is None


# ---------------------------------------------------------------------------
# Parsers sobre las plantillas sintéticas
# ---------------------------------------------------------------------------
def _documentos(catalogo: SepomexCatalog, n: int):
    config = SynthConfig(dpi=60)
    for seed in range(n):
        faker = Faker("es_MX")
        faker.seed_instance(seed)
        p = generate_persona(f"p{seed}", random.Random(seed), faker, catalogo, config)
        ctx = DocContext(
            p, p.nombre, p.apellido_paterno, p.apellido_materno, p.domicilio,
            config.reference_date, config.reference_date, random.Random(seed),
        )  # fmt: skip
        yield DocType.CURP, curp.render(ctx)
        yield DocType.CSF, csf.render(ctx)


def test_parsers_leen_todos_los_campos_de_las_plantillas(catalogo: SepomexCatalog) -> None:
    for doc_type, rendered in _documentos(catalogo, 25):
        out = extract_text_route(rendered.pdf, doc_type)
        assert out.result is not None
        assert out.result.warnings == ()
        for name in PARSERS[doc_type].fields:
            if name in rendered.fields:
                value = out.result.fields[name].value
                assert field_matches(name, value, rendered.fields[name]), (doc_type, name, value)


def test_solo_curp_y_csf_tienen_parser_de_texto() -> None:
    # INE y comprobante van por la ruta de imagen en esta fase, aunque tengan texto.
    assert set(PARSERS) == {DocType.CURP, DocType.CSF}


# ---------------------------------------------------------------------------
# CURP: formatos alternativos
# ---------------------------------------------------------------------------
def test_nombre_completo_en_una_linea_se_divide_con_la_curp() -> None:
    clave = _curp()
    result = CurpParser().parse(layout(f"CURP: {clave}", "Nombre: JUAN CARLOS PEREZ LOPEZ"))
    f = result.fields
    assert (f["nombre"].value, f["apellido_paterno"].value, f["apellido_materno"].value) == (
        "JUAN CARLOS",
        "PEREZ",
        "LOPEZ",
    )
    assert f["nombre"].confidence == Confianza.VALIDADO


def test_nombre_con_apellidos_primero() -> None:
    clave = _curp()
    result = CurpParser().parse(layout(clave, "Nombre: PEREZ LOPEZ JUAN CARLOS"))
    assert result.fields["nombre"].value == "JUAN CARLOS"
    assert result.fields["apellido_paterno"].value == "PEREZ"


def test_division_ambigua_baja_la_confianza() -> None:
    # Las 4 iniciales y 3 consonantes de la CURP casi siempre desambiguan; con palabras
    # repetidas, varias divisiones producen las mismas letras.
    clave = _curp("Juan Juan", "Juan", "Juan")
    split, ambiguo = split_full_name("JUAN JUAN JUAN JUAN", clave)
    assert split is not None and ambiguo
    result = CurpParser().parse(layout(clave, "Nombre: JUAN JUAN JUAN JUAN"))
    assert result.fields["nombre"].confidence == Confianza.DUDOSO


def test_nombre_que_no_concuerda_con_la_curp_no_se_divide() -> None:
    split, _ = split_full_name("SOFIA RAMOS VEGA", _curp())
    assert split is None


def test_datos_no_impresos_se_derivan_de_la_curp() -> None:
    clave = _curp()
    f = CurpParser().parse(layout(f"Clave: {clave}")).fields
    assert f["fecha_nacimiento"].value == "1990-05-17"
    assert f["fecha_nacimiento"].confidence == Confianza.DERIVADO
    assert f["sexo"].value == "H"
    assert f["entidad_nacimiento"].value == "Nayarit"
    assert f["nombre"].value is None


def test_etiquetas_sin_dos_puntos() -> None:
    clave = _curp()
    f = (
        CurpParser()
        .parse(
            layout(
                clave, "Nombre(s) JUAN CARLOS", "Primer apellido PEREZ", "Segundo apellido LOPEZ"
            )
        )
        .fields
    )
    assert f["apellido_paterno"].value == "PEREZ"
    assert f["nombre"].confidence == Confianza.VALIDADO


def test_nombre_que_no_corresponde_a_la_curp() -> None:
    clave = _curp()
    f = (
        CurpParser()
        .parse(
            layout(
                clave, "Nombre(s): JUAN CARLOS", "Primer apellido: RAMOS", "Segundo apellido: LOPEZ"
            )
        )
        .fields
    )
    assert f["apellido_paterno"].confidence == Confianza.INCONSISTENTE
    assert WarningCode.CURP_DATOS_NO_COINCIDEN in [w.code for w in f["apellido_paterno"].warnings]


def test_fecha_impresa_distinta_de_la_curp() -> None:
    f = CurpParser().parse(layout(_curp(), "Fecha de nacimiento: 18/05/1990")).fields
    assert f["fecha_nacimiento"].confidence == Confianza.INCONSISTENTE


def test_curp_con_digito_verificador_incorrecto() -> None:
    clave = _curp()
    mala = clave[:17] + str((int(clave[17]) + 1) % 10)
    f = CurpParser().parse(layout(f"CURP: {mala}")).fields
    assert f["curp"].value == mala
    assert f["curp"].confidence == Confianza.INVALIDO
    assert f["curp"].warnings[0].code is WarningCode.CURP_DIGITO_VERIFICADOR_INVALIDO


def test_prefiere_la_curp_valida_si_hay_varias() -> None:
    clave = _curp()
    mala = clave[:17] + str((int(clave[17]) + 1) % 10)
    assert CurpParser().parse(layout(mala, clave)).fields["curp"].value == clave


def test_sin_curp() -> None:
    f = CurpParser().parse(layout("Nombre(s): JUAN", "Primer apellido: PEREZ")).fields
    assert f["curp"].value is None
    assert f["nombre"].value == "JUAN"
    assert f["nombre"].confidence == Confianza.ETIQUETADO


# ---------------------------------------------------------------------------
# CSF
# ---------------------------------------------------------------------------
def _csf(rfc: str, clave: str, cp: str = "63000") -> list:
    return [
        f"RFC: {rfc}",
        f"CURP: {clave}",
        "Nombre (s): JUAN CARLOS",
        "Primer Apellido: PEREZ",
        "Segundo Apellido: LOPEZ",
        [(50, f"Código Postal: {cp}"), (300, "Tipo de Vialidad: CALLE")],
        [(50, "Nombre de Vialidad: JUAREZ"), (300, "Número Exterior: 12")],
        [(50, "Número Interior:"), (300, "Nombre de la Colonia: CENTRO")],
        [(50, "Nombre de la Localidad: TEPIC"), (300, "Nombre de la Entidad Federativa: NAYARIT")],
    ]


def test_csf_formato_basico() -> None:
    clave = _curp()
    rfc = build_rfc(
        nombre="Juan Carlos",
        apellido_paterno="Pérez",
        apellido_materno="López",
        fecha_nacimiento=date(1990, 5, 17),
    )
    f = CsfParser().parse(layout(*_csf(rfc, clave))).fields
    assert f["rfc"].value == rfc and f["rfc"].confidence == Confianza.VALIDADO
    assert f["curp"].value == clave
    assert f["calle"].value == "CALLE JUAREZ"
    assert f["numero_interior"].value == ""
    assert f["colonia"].value == "CENTRO"
    assert f["nombre"].confidence == Confianza.VALIDADO


def test_csf_rfc_invalido_y_cp_mal_formado() -> None:
    clave = _curp()
    valido = build_rfc(
        nombre="Juan Carlos",
        apellido_paterno="Pérez",
        apellido_materno="López",
        fecha_nacimiento=date(1990, 5, 17),
    )
    malo = valido[:12] + ("1" if valido[12] != "1" else "2")
    f = CsfParser().parse(layout(*_csf(malo, clave, cp="63A00"))).fields
    assert f["rfc"].value == malo
    assert f["rfc"].confidence == Confianza.INVALIDO
    assert f["codigo_postal"].confidence == Confianza.INVALIDO
