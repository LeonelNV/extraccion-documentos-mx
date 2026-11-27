"""Configuración del generador. Los valores por defecto están aquí; ``config.toml`` los
puede sobrescribir (y lo que no aparezca en el TOML conserva su valor por defecto)."""

import tomllib
from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from docextract.schemas import DocType

__all__ = ["DEFAULT_CONFIG_PATH", "ComprobanteConfig", "SynthConfig", "load_config"]

DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.toml")

Probability = float


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PersonasConfig(_Frozen):
    train: int = Field(default=500, ge=0)
    val: int = Field(default=75, ge=0)
    test: int = Field(default=75, ge=0)


class TasasConfig(_Frozen):
    """Probabilidad de cada caso límite por persona (independientes entre sí)."""

    nombre_compuesto: Probability = Field(default=0.25, ge=0, le=1)
    jose_maria: Probability = Field(default=0.10, ge=0, le=1)
    particula: Probability = Field(default=0.08, ge=0, le=1)
    sin_materno: Probability = Field(default=0.05, ge=0, le=1)
    enie: Probability = Field(default=0.08, ge=0, le=1)
    dieresis: Probability = Field(default=0.03, ge=0, le=1)
    sexo_x: Probability = Field(default=0.02, ge=0, le=1)
    nacido_extranjero: Probability = Field(default=0.03, ge=0, le=1)
    numero_interior: Probability = Field(default=0.25, ge=0, le=1)
    sin_numero: Probability = Field(default=0.04, ge=0, le=1)
    inconsistencia: Probability = Field(default=0.10, ge=0, le=1)
    domicilio_nayarit: Probability = Field(
        default=0.5,
        ge=0,
        le=1,
        description="Parte de los domicilios en Nayarit (la FEA es de ahí).",
    )
    nacido_nayarit: Probability = Field(default=0.4, ge=0, le=1)


class ComprobanteConfig(_Frozen):
    plantillas_train: tuple[str, ...] = ("luz", "agua", "banco")
    plantilla_no_vista: str = "telefono"
    fraccion_no_vista_test: Probability = Field(default=0.5, ge=0, le=1)
    dias_emision_max: int = Field(
        default=60, ge=0, description="Antigüedad máxima de un comprobante vigente, en días."
    )

    @model_validator(mode="after")
    def _no_vista_fuera_de_train(self) -> "ComprobanteConfig":
        if self.plantilla_no_vista in self.plantillas_train:
            raise ValueError("La plantilla no vista no puede estar en plantillas_train.")
        return self


# Probabilidades (digital, escaneo, foto) por tipo de documento.
_MODALIDADES_DEFAULT = {
    DocType.CURP: (0.7, 0.2, 0.1),
    DocType.CSF: (0.7, 0.2, 0.1),
    DocType.INE: (0.1, 0.4, 0.5),
    DocType.COMPROBANTE_DOMICILIO: (0.3, 0.3, 0.4),
}


class SynthConfig(_Frozen):
    seed: int = 20261126
    reference_date: date = Field(
        default=date(2026, 11, 1),
        description="'Hoy' para el generador; fija para que el dataset sea reproducible.",
    )
    dpi: int = Field(default=200, ge=50, le=400, description="Resolución al rasterizar.")
    personas: PersonasConfig = PersonasConfig()
    tasas: TasasConfig = TasasConfig()
    comprobante: ComprobanteConfig = ComprobanteConfig()
    modalidades: dict[DocType, tuple[Probability, Probability, Probability]] = Field(
        default_factory=lambda: dict(_MODALIDADES_DEFAULT)
    )

    @model_validator(mode="after")
    def _modalidades_validas(self) -> "SynthConfig":
        if set(self.modalidades) != set(DocType):
            raise ValueError("modalidades debe tener una entrada por tipo de documento.")
        for doc_type, probs in self.modalidades.items():
            if any(p < 0 for p in probs) or abs(sum(probs) - 1) > 1e-6:
                raise ValueError(f"Las probabilidades de {doc_type} deben sumar 1.")
        return self


def load_config(path: Path | None = DEFAULT_CONFIG_PATH, **overrides: object) -> SynthConfig:
    """Lee el TOML (si existe) y aplica ``overrides`` de primer nivel (p. ej. ``seed``)."""
    data: dict[str, object] = {}
    if path is not None:
        with path.open("rb") as f:
            data = tomllib.load(f)
    data.update({k: v for k, v in overrides.items() if v is not None})
    return SynthConfig.model_validate(data)
