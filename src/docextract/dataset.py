"""Esquema del dataset sintético: lo escribe el generador (``synth/``) y lo lee la evaluación.

Estructura en disco::

    data/synthetic/
      dataset.json                  DatasetInfo: semilla, configuración, conteos, versiones
      <split>/manifest.jsonl        un DocumentTruth por línea (con persona_id), para iterar
      <split>/<persona_id>/
        ground_truth.json           PersonTruth
        curp.pdf, ine.pdf, ...      el documento como lo subiría la persona
        ine.jpg, ...                la imagen, en las modalidades escaneo y foto

Dos niveles de verdad:

- ``PersonTruth.form``: el formulario esperado, en el formato de la FEA (mayúsculas, sin
  acentos, con Ñ). Es contra lo que se evalúa la salida fusionada.
- ``DocumentTruth.fields``: cada campo **tal como está impreso** en ese documento (puede
  tener acentos, abreviaturas o una inconsistencia inyectada). Es contra lo que se evalúa
  cada extractor.
"""

from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from docextract.schemas import FORM_FIELDS, DocType, WarningCode

__all__ = [
    "DatasetInfo",
    "DocumentTruth",
    "ExpectedWarning",
    "Modality",
    "PersonTruth",
    "Split",
]

Split = Literal["train", "val", "test"]


class Modality(StrEnum):
    DIGITAL = "digital"
    """PDF con capa de texto, como lo descarga la persona de RENAPO o del SAT."""
    ESCANEO = "escaneo"
    """Imagen recta y limpia dentro de un PDF sin texto, como de un escáner de cama plana."""
    FOTO = "foto"
    """Foto de celular (perspectiva, sombras, desenfoque) dentro de un PDF sin texto."""


class DocumentTruth(BaseModel):
    model_config = ConfigDict(frozen=True)

    persona_id: str
    doc_type: DocType
    template: str = Field(description="Diseño de la plantilla, p. ej. 'comprobante_luz'.")
    template_seen_in_train: bool = Field(
        description="Falso solo para la plantilla de comprobante reservada para test."
    )
    modality: Modality
    pdf: str = Field(description="Ruta del PDF relativa a la raíz del dataset.")
    image: str | None = Field(default=None, description="Ruta del JPG (escaneo y foto).")
    fields: dict[str, str] = Field(
        description=(
            "Cada campo tal como está impreso. Usa los nombres del formulario y campos "
            "auxiliares (sexo, fecha_emision, clave_elector...). '' = el documento indica que "
            "no existe; un campo ausente = el documento no lo trae."
        )
    )
    augmentation: dict[str, float] = Field(
        default_factory=dict, description="Parámetros de la degradación aplicada (escaneo y foto)."
    )


class ExpectedWarning(BaseModel):
    """Una inconsistencia inyectada a propósito y la advertencia que debería producir."""

    model_config = ConfigDict(frozen=True)

    code: WarningCode
    kind: str = Field(description="Tipo de inconsistencia, p. ej. 'domicilio_ine_distinto'.")
    docs: tuple[DocType, ...]
    fields: tuple[str, ...]


class PersonTruth(BaseModel):
    model_config = ConfigDict(frozen=True)

    persona_id: str
    split: Split
    form: dict[str, str] = Field(
        description="Formulario esperado, formato FEA. Fecha en ISO; '' = no existe."
    )
    documents: tuple[DocumentTruth, ...]
    expected_warnings: tuple[ExpectedWarning, ...] = ()
    tags: tuple[str, ...] = Field(
        default=(), description="Casos límite presentes: 'nombre_compuesto', 'sin_materno'..."
    )

    @model_validator(mode="after")
    def _form_is_complete(self) -> "PersonTruth":
        missing = set(FORM_FIELDS) - set(self.form)
        if missing:
            raise ValueError(f"Al formulario esperado le faltan campos: {sorted(missing)}")
        return self


class DatasetInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    generator_version: str
    seed: int
    reference_date: date = Field(description="'Hoy' para el generador: fechas de emisión.")
    config: dict[str, object]
    counts: dict[str, dict[str, int]] = Field(
        description="Por split: personas y documentos por tipo, plantilla y modalidad."
    )
    sepomex_sha256: str | None
    library_versions: dict[str, str]
