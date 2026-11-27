"""Pruebas de los esquemas de dominio y del contrato de la API."""

from collections.abc import Sequence
from datetime import date

import pytest
from pydantic import ValidationError

from docextract.api.schemas import ExtractResponse, HealthResponse
from docextract.extractors import Extractor
from docextract.schemas import (
    FORM_FIELDS,
    DocType,
    ExtractedField,
    ExtractionResult,
    ExtractionWarning,
    FieldResult,
    ModelUsage,
    PrefilledForm,
    WarningCode,
)

# Contrato de la sección 7 del plan: mismos nombres y mismo orden que el formulario de la FEA.
CONTRACT_FIELDS = (
    "curp",
    "rfc",
    "nombre",
    "apellido_paterno",
    "apellido_materno",
    "fecha_nacimiento",
    "nacionalidad",
    "calle",
    "numero_exterior",
    "numero_interior",
    "colonia",
    "ciudad",
    "estado",
    "codigo_postal",
)
# Identificadores de prueba que no corresponden a ninguna persona.
RFC_GENERICO = "XAXX010101000"  # RFC genérico del SAT para público en general
CURP_FICTICIA = "XXXX000101HNTXXX00"  # solo tiene el formato de una CURP
FIELD_KEYS = {"value", "confidence", "source_doc", "needs_review", "warnings"}


def _codes(field: FieldResult) -> list[WarningCode]:
    return [w.code for w in field.warnings]


# ---------------------------------------------------------------------------
# FieldResult y needs_review
# ---------------------------------------------------------------------------
def test_campo_vacio_requiere_revision_y_dice_por_que() -> None:
    field = FieldResult[str]()

    assert field.needs_review
    assert _codes(field) == [WarningCode.CAMPO_NO_ENCONTRADO]


def test_campo_con_valor_y_sin_advertencias_no_requiere_revision() -> None:
    field = FieldResult[str](value=RFC_GENERICO, confidence=0.99, source_doc=DocType.CSF)

    assert not field.needs_review


def test_cadena_vacia_significa_que_el_dato_no_existe() -> None:
    # Persona sin apellido materno: el documento lo indica, no es un dato faltante.
    field = FieldResult[str](value="", confidence=0.95, source_doc=DocType.CURP)

    assert not field.needs_review


def test_no_duplica_campo_no_encontrado() -> None:
    warning = ExtractionWarning(code=WarningCode.CAMPO_NO_ENCONTRADO, message="Sin dato.")

    field = FieldResult[str](warnings=(warning,))

    assert _codes(field) == [WarningCode.CAMPO_NO_ENCONTRADO]


def test_cualquier_advertencia_marca_revision() -> None:
    warning = ExtractionWarning(
        code=WarningCode.NOMBRE_NO_COINCIDE,
        message="El nombre de la INE no coincide con el de la CURP.",
        fields=("nombre",),
        docs=(DocType.CURP, DocType.INE),
    )

    field = FieldResult[str](value="MARIA", confidence=0.99, warnings=(warning,))

    assert field.needs_review


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_confianza_fuera_de_rango(confidence: float) -> None:
    with pytest.raises(ValidationError):
        FieldResult[str](value="X", confidence=confidence)


def test_es_inmutable() -> None:
    field = FieldResult[str](value="X", confidence=1.0)

    with pytest.raises(ValidationError):
        field.value = "Y"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# FieldResult.create y el umbral
# ---------------------------------------------------------------------------
def test_create_bajo_el_umbral_agrega_confianza_baja() -> None:
    field = FieldResult[str].create(
        "JUAN", confidence=0.6, source_doc=DocType.INE, review_threshold=0.8
    )

    assert field.needs_review
    assert _codes(field) == [WarningCode.CONFIANZA_BAJA]
    assert "JUAN" not in field.warnings[0].message  # privacidad: sin valores en mensajes


def test_create_en_el_umbral_no_requiere_revision() -> None:
    field = FieldResult[str].create(
        "JUAN", confidence=0.8, source_doc=DocType.INE, review_threshold=0.8
    )

    assert not field.needs_review


def test_create_sin_valor_solo_reporta_no_encontrado() -> None:
    field = FieldResult[str].create(None, confidence=0.0, source_doc=None, review_threshold=0.8)

    assert _codes(field) == [WarningCode.CAMPO_NO_ENCONTRADO]


def test_create_conserva_advertencias_previas() -> None:
    previa = ExtractionWarning(code=WarningCode.RFC_NO_COINCIDE_CON_CURP, message="No coincide.")

    field = FieldResult[str].create(
        RFC_GENERICO,
        confidence=0.5,
        source_doc=DocType.CSF,
        review_threshold=0.8,
        warnings=[previa],
    )

    assert _codes(field) == [WarningCode.RFC_NO_COINCIDE_CON_CURP, WarningCode.CONFIANZA_BAJA]


@pytest.mark.parametrize("threshold", [-0.1, 1.1])
def test_create_rechaza_umbral_invalido(threshold: float) -> None:
    with pytest.raises(ValueError, match="review_threshold"):
        FieldResult[str].create("X", confidence=1.0, source_doc=None, review_threshold=threshold)


# ---------------------------------------------------------------------------
# PrefilledForm
# ---------------------------------------------------------------------------
def test_form_fields_es_el_contrato() -> None:
    assert FORM_FIELDS == CONTRACT_FIELDS


def test_formulario_vacio_marca_todo_para_revision() -> None:
    form = PrefilledForm()

    assert all(getattr(form, name).needs_review for name in FORM_FIELDS)


def test_fecha_se_valida_y_se_serializa_en_iso() -> None:
    form = PrefilledForm(fecha_nacimiento={"value": "1990-05-17", "confidence": 1.0})

    assert form.fecha_nacimiento.value == date(1990, 5, 17)
    assert form.model_dump(mode="json")["fecha_nacimiento"]["value"] == "1990-05-17"


def test_fecha_invalida_falla() -> None:
    with pytest.raises(ValidationError):
        PrefilledForm(fecha_nacimiento={"value": "1990-02-30", "confidence": 1.0})


def test_ida_y_vuelta_por_json() -> None:
    form = PrefilledForm(
        curp=FieldResult[str](value=CURP_FICTICIA, confidence=0.99, source_doc=DocType.CURP),
        warnings=(
            ExtractionWarning(
                code=WarningCode.DOMICILIO_NO_COINCIDE,
                message="El domicilio del comprobante no coincide con el de la INE.",
                fields=("calle", "colonia"),
                docs=(DocType.COMPROBANTE_DOMICILIO, DocType.INE),
            ),
        ),
    )

    assert PrefilledForm.model_validate_json(form.model_dump_json()) == form


# ---------------------------------------------------------------------------
# Salida de los extractores
# ---------------------------------------------------------------------------
def test_extraction_result_valido() -> None:
    result = ExtractionResult(
        doc_type=DocType.INE,
        extractor="ocr_rules",
        fields={"curp": ExtractedField(value=CURP_FICTICIA, confidence=0.9)},
        latency_ms=120.5,
        usage=ModelUsage(input_tokens=1000, output_tokens=200, estimated_cost_usd=0.004),
    )

    assert result.fields["curp"].confidence == 0.9


@pytest.mark.parametrize(
    "kwargs",
    [
        {"extractor": ""},
        {"latency_ms": -1},
        {"doc_type": "pasaporte"},
    ],
)
def test_extraction_result_invalido(kwargs: dict) -> None:
    base = {"doc_type": DocType.CURP, "extractor": "ocr_rules"}
    with pytest.raises(ValidationError):
        ExtractionResult(**{**base, **kwargs})


def test_costo_negativo_falla() -> None:
    with pytest.raises(ValidationError):
        ModelUsage(input_tokens=1, output_tokens=1, estimated_cost_usd=-0.1)


def test_advertencia_sin_mensaje_falla() -> None:
    with pytest.raises(ValidationError):
        ExtractionWarning(code=WarningCode.CP_NO_EXISTE, message="")


def test_codigos_de_advertencia_son_estables() -> None:
    # El valor es el nombre: así el código no cambia si se reordena o se reescribe el enum.
    assert all(code.value == code.name for code in WarningCode)


def test_un_extractor_cumple_la_interfaz() -> None:
    class Dummy:
        name = "dummy"

        def extract(self, images: Sequence[object], doc_type: DocType) -> ExtractionResult:
            return ExtractionResult(doc_type=doc_type, extractor=self.name)

    assert isinstance(Dummy(), Extractor)
    assert Dummy().extract([], DocType.CSF).doc_type is DocType.CSF


# ---------------------------------------------------------------------------
# Contrato OpenAPI (lo que verá el equipo de la FEA)
# ---------------------------------------------------------------------------
def test_esquema_de_respuesta_tiene_el_contrato() -> None:
    schema = ExtractResponse.model_json_schema(mode="serialization")
    properties = schema["properties"]

    assert tuple(properties) == (*CONTRACT_FIELDS, "warnings")
    for name in CONTRACT_FIELDS:
        ref = properties[name]["$ref"].removeprefix("#/$defs/")
        field_schema = schema["$defs"][ref]
        assert set(field_schema["properties"]) == FIELD_KEYS, name
        assert "needs_review" in field_schema["required"], name


def test_health_response() -> None:
    assert HealthResponse(version="0.1.0").model_dump() == {"status": "ok", "version": "0.1.0"}
