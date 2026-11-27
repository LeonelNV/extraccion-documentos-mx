"""Esquemas de dominio: lo que producen los extractores y lo que devuelve la fusión.

Flujo de datos::

    Extractor.extract() -> ExtractionResult (un documento, valores en crudo)
    normalizar + validar + fusionar -> PrefilledForm (una persona, un FieldResult por campo)

Convención de nombres:

- Los metadatos van en inglés, como pide el contrato de la API: ``value``, ``confidence``,
  ``source_doc``, ``needs_review`` y ``warnings``.
- Los campos del formulario van en español y se llaman igual que en la FEA: ``curp``,
  ``rfc``, ``nombre``, etc.

Privacidad: los mensajes de advertencia **nunca** incluyen valores extraídos (CURP, RFC,
nombres, domicilios), para poder registrarlos en logs sin exponer datos personales.
"""

from collections.abc import Iterable
from datetime import date
from enum import StrEnum
from typing import Annotated, Any, Generic, Self, TypeVar

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

Confidence = Annotated[float, Field(ge=0.0, le=1.0, description="Confianza entre 0 y 1.")]


class DocType(StrEnum):
    """Tipos de documento que acepta el sistema."""

    CURP = "curp"
    INE = "ine"
    CSF = "csf"
    COMPROBANTE_DOMICILIO = "comprobante_domicilio"


class WarningCode(StrEnum):
    """Códigos estables de advertencia, para que el front de la FEA reaccione a cada uno.

    Agregar códigos es compatible hacia atrás; renombrarlos o quitarlos rompe el contrato.
    """

    # Extracción
    CAMPO_NO_ENCONTRADO = "CAMPO_NO_ENCONTRADO"
    CONFIANZA_BAJA = "CONFIANZA_BAJA"
    DOCUMENTO_FALTANTE = "DOCUMENTO_FALTANTE"
    DOCUMENTO_NO_RECONOCIDO = "DOCUMENTO_NO_RECONOCIDO"
    # CURP
    CURP_FORMATO_INVALIDO = "CURP_FORMATO_INVALIDO"
    CURP_DIGITO_VERIFICADOR_INVALIDO = "CURP_DIGITO_VERIFICADOR_INVALIDO"
    CURP_DATOS_NO_COINCIDEN = "CURP_DATOS_NO_COINCIDEN"  # fecha, sexo o entidad derivados
    CURP_NACIDO_EN_EXTRANJERO = "CURP_NACIDO_EN_EXTRANJERO"  # entidad NE: revisar nacionalidad
    # RFC
    RFC_FORMATO_INVALIDO = "RFC_FORMATO_INVALIDO"
    RFC_HOMOCLAVE_INVALIDA = "RFC_HOMOCLAVE_INVALIDA"
    RFC_NO_COINCIDE_CON_CURP = "RFC_NO_COINCIDE_CON_CURP"
    # Cruce entre documentos
    NOMBRE_NO_COINCIDE = "NOMBRE_NO_COINCIDE"
    DOMICILIO_NO_COINCIDE = "DOMICILIO_NO_COINCIDE"
    # Domicilio
    CP_NO_EXISTE = "CP_NO_EXISTE"
    CP_NO_COINCIDE_CON_ESTADO = "CP_NO_COINCIDE_CON_ESTADO"
    COLONIA_NO_ENCONTRADA = "COLONIA_NO_ENCONTRADA"
    COMPROBANTE_ANTIGUO = "COMPROBANTE_ANTIGUO"


class ExtractionWarning(BaseModel):
    """Advertencia sobre un campo o sobre la consistencia entre documentos."""

    model_config = ConfigDict(frozen=True)

    code: WarningCode
    message: str = Field(
        min_length=1,
        description="Mensaje para quien revisa. Nunca incluye valores extraídos.",
    )
    fields: tuple[str, ...] = Field(default=(), description="Campos del formulario afectados.")
    docs: tuple[DocType, ...] = Field(default=(), description="Documentos involucrados.")


# ---------------------------------------------------------------------------
# Salida de un extractor (un documento)
# ---------------------------------------------------------------------------
class ExtractedField(BaseModel):
    """Un valor tal como lo produjo un extractor, antes de normalizar, validar y fusionar.

    No tiene ``needs_review``: eso se decide en la fusión, con el umbral configurable.
    """

    model_config = ConfigDict(frozen=True)

    value: str | None = Field(default=None, description="Texto extraído; None si no se encontró.")
    confidence: Confidence = 0.0
    warnings: tuple[ExtractionWarning, ...] = ()


class ModelUsage(BaseModel):
    """Consumo de un modelo remoto (p. ej. Bedrock), para estimar el costo por documento."""

    model_config = ConfigDict(frozen=True)

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    estimated_cost_usd: float = Field(ge=0)


class ExtractionResult(BaseModel):
    """Lo que devuelve ``Extractor.extract`` para un documento."""

    model_config = ConfigDict(frozen=True)

    doc_type: DocType
    extractor: str = Field(min_length=1, description="Nombre del extractor, p. ej. 'ocr_rules'.")
    fields: dict[str, ExtractedField] = Field(
        default_factory=dict,
        description=(
            "Campos por nombre. Puede incluir campos auxiliares que no son del formulario, "
            "como la fecha de emisión del comprobante."
        ),
    )
    warnings: tuple[ExtractionWarning, ...] = ()
    latency_ms: float | None = Field(default=None, ge=0)
    usage: ModelUsage | None = None


# ---------------------------------------------------------------------------
# Resultado fusionado (una persona)
# ---------------------------------------------------------------------------
T = TypeVar("T")

_NOT_FOUND_MESSAGE = "No se encontró el dato en los documentos."


def _warning_code(warning: Any) -> Any:
    return warning.get("code") if isinstance(warning, dict) else getattr(warning, "code", None)


class FieldResult(BaseModel, Generic[T]):
    """Un campo del formulario prellenado, ya normalizado, validado y fusionado.

    ``needs_review`` se calcula: es verdadero **si y solo si** el campo tiene advertencias,
    y cada advertencia explica por qué hay que revisarlo. Un valor faltante agrega
    ``CAMPO_NO_ENCONTRADO`` automáticamente; una confianza menor al umbral agrega
    ``CONFIANZA_BAJA`` (ver :meth:`create`).

    ``value`` distingue dos casos:

    - ``None``: no se encontró el dato.
    - ``""``: el documento indica que no existe (p. ej. sin apellido materno o sin
      número interior). No requiere revisión por sí solo.
    """

    model_config = ConfigDict(frozen=True)

    value: T | None = None
    confidence: Confidence = 0.0
    source_doc: DocType | None = Field(
        default=None,
        description="Documento del que salió el valor; None si es un valor por defecto o falta.",
    )
    warnings: tuple[ExtractionWarning, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def _missing_value_is_a_warning(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("value") is None:
            warnings = list(data.get("warnings") or ())
            if not any(_warning_code(w) == WarningCode.CAMPO_NO_ENCONTRADO for w in warnings):
                warnings.append(
                    ExtractionWarning(
                        code=WarningCode.CAMPO_NO_ENCONTRADO, message=_NOT_FOUND_MESSAGE
                    )
                )
            data = {**data, "warnings": warnings}
        return data

    @computed_field(  # type: ignore[prop-decorator]
        description="Verdadero si el campo tiene advertencias y alguien debe revisarlo."
    )
    @property
    def needs_review(self) -> bool:
        return bool(self.warnings)

    @classmethod
    def create(
        cls,
        value: T | None,
        *,
        confidence: float,
        source_doc: DocType | None,
        review_threshold: float,
        warnings: Iterable[ExtractionWarning] = (),
    ) -> Self:
        """Construye el campo y agrega ``CONFIANZA_BAJA`` si la confianza está bajo el umbral."""
        if not 0.0 <= review_threshold <= 1.0:
            raise ValueError("review_threshold debe estar entre 0 y 1")
        all_warnings = list(warnings)
        if value is not None and confidence < review_threshold:
            all_warnings.append(
                ExtractionWarning(
                    code=WarningCode.CONFIANZA_BAJA,
                    message=(
                        f"La confianza ({confidence:.2f}) está por debajo del umbral "
                        f"de revisión ({review_threshold:.2f})."
                    ),
                )
            )
        return cls(
            value=value,
            confidence=confidence,
            source_doc=source_doc,
            warnings=tuple(all_warnings),
        )


def _text_field(description: str) -> Any:
    return Field(default_factory=FieldResult[str], description=description)


class PrefilledForm(BaseModel):
    """Formulario de alta prellenado: un campo por cada dato que se obtiene de los documentos.

    Correo y teléfono los captura la persona; fotografía y huella están fuera de alcance.
    """

    model_config = ConfigDict(frozen=True)

    curp: FieldResult[str] = _text_field("CURP de 18 caracteres.")
    rfc: FieldResult[str] = _text_field("RFC de persona física con homoclave (13 caracteres).")
    nombre: FieldResult[str] = _text_field("Nombre o nombres de pila.")
    apellido_paterno: FieldResult[str] = _text_field("Primer apellido.")
    apellido_materno: FieldResult[str] = _text_field(
        "Segundo apellido; cadena vacía si la persona no tiene."
    )
    fecha_nacimiento: FieldResult[date] = Field(
        default_factory=FieldResult[date], description="Fecha de nacimiento (ISO 8601)."
    )
    nacionalidad: FieldResult[str] = _text_field("Código ISO 3166-1 alfa-2; MX por defecto.")
    calle: FieldResult[str] = _text_field("Calle del domicilio.")
    numero_exterior: FieldResult[str] = _text_field("Número exterior.")
    numero_interior: FieldResult[str] = _text_field("Número interior; cadena vacía si no hay.")
    colonia: FieldResult[str] = _text_field("Colonia o asentamiento.")
    ciudad: FieldResult[str] = _text_field("Ciudad o municipio.")
    estado: FieldResult[str] = _text_field("Entidad federativa.")
    codigo_postal: FieldResult[str] = _text_field("Código postal de 5 dígitos.")
    warnings: tuple[ExtractionWarning, ...] = Field(
        default=(),
        description="Advertencias globales, como inconsistencias entre documentos.",
    )


FORM_FIELDS: tuple[str, ...] = tuple(
    name for name in PrefilledForm.model_fields if name != "warnings"
)
"""Nombres de los campos del formulario, en el orden del contrato de la API."""
