"""Pruebas del esquema del dataset sintético."""

import pytest
from pydantic import ValidationError

from docextract.dataset import DocumentTruth, Modality, PersonTruth
from docextract.schemas import FORM_FIELDS, DocType


def _doc() -> DocumentTruth:
    return DocumentTruth(
        persona_id="train-00000",
        doc_type=DocType.CURP,
        template="curp_constancia",
        template_seen_in_train=True,
        modality=Modality.DIGITAL,
        pdf="train/train-00000/curp.pdf",
        fields={"curp": "X"},
    )


def test_persona_completa() -> None:
    truth = PersonTruth(
        persona_id="train-00000",
        split="train",
        form=dict.fromkeys(FORM_FIELDS, ""),
        documents=(_doc(),),
    )
    assert PersonTruth.model_validate_json(truth.model_dump_json()) == truth


def test_formulario_incompleto_es_invalido() -> None:
    form = dict.fromkeys(FORM_FIELDS, "")
    del form["curp"]
    with pytest.raises(ValidationError, match="curp"):
        PersonTruth(persona_id="p", split="train", form=form, documents=(_doc(),))


def test_split_invalido() -> None:
    with pytest.raises(ValidationError):
        PersonTruth(persona_id="p", split="dev", form=dict.fromkeys(FORM_FIELDS, ""), documents=())
