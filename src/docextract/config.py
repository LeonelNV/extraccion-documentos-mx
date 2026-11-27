"""Parámetros configurables de la validación.

Los umbrales de similitud son **provisionales**: se calibran en la fase 5 con los datos de
evaluación, igual que el umbral de revisión de ``FieldResult.create`` (que por eso no tiene
valor por defecto).
"""

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["ValidationConfig"]


class ValidationConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    name_similarity_threshold: float = Field(
        default=0.90,
        ge=0.0,
        le=1.0,
        description="Similitud mínima (0-1) para considerar iguales dos nombres o apellidos.",
    )
    colonia_similarity_threshold: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Similitud mínima para aceptar una colonia del catálogo de SEPOMEX.",
    )
    municipio_similarity_threshold: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Similitud mínima entre la ciudad extraída y el municipio o ciudad del CP.",
    )
    comprobante_max_months: int = Field(
        default=3,
        ge=1,
        description="Antigüedad máxima del comprobante de domicilio, en meses.",
    )
