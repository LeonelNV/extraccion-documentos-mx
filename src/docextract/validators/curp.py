"""Validación y construcción de la CURP.

Fuentes:

- Estructura de los 18 caracteres: *Instructivo Normativo para la asignación de la CURP*
  (DOF, 18/06/2018, artículo tercero) y su modificación (DOF, 18/10/2021).
- Casos especiales de las posiciones 1-4 y 14-16 (Ñ, nombres compuestos, partículas,
  caracteres especiales, palabras altisonantes, sin vocal o consonante interna, un solo
  apellido) y el significado del carácter 17: *Reglas para la ejecución de los
  procedimientos para la asignación de la CURP*, RENAPO, capítulo 5.
  https://www.gob.mx/cms/uploads/attachment/file/681698/reglas_para_la_ejecucion_de_los_procedimientos_asignacion_de_la_curp.pdf

Lo que **no** está publicado y por eso se tomó del conocimiento público (ver
``docs/validaciones.md``):

- El algoritmo del dígito verificador (las Reglas solo dicen que lo asigna "la aplicación
  de un algoritmo"). Se puede comprobar contra CURPs reales, sin que salgan de la máquina,
  con ``scripts/verificar_claves.py``.
- El Anexo 01 de las Reglas (catálogo de palabras altisonantes). Dos de sus palabras están
  confirmadas por los ejemplos de las Reglas; el resto es la lista de uso público. Para que
  una palabra faltante no genere advertencias falsas, la comparación contra el nombre acepta
  la "X" de la posición 2 aunque la palabra no esté en la lista.
- El sexo "X" (personas no binarias): lo emite RENAPO y se valida igual que H y M.
"""

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict

from docextract.entidades import CLAVES_CURP, NACIDO_EN_EXTRANJERO
from docextract.normalize import clean_identifier
from docextract.schemas import DocType, ExtractionWarning, WarningCode
from docextract.validators._common import (
    LETRAS,
    VOCALES,
    make_warning,
    palabras_para_clave,
    quitar_iniciales,
)

__all__ = [
    "CURP_RE",
    "CurpInfo",
    "CurpValidation",
    "Sexo",
    "build_curp",
    "check_curp_consistency",
    "curp_check_digit",
    "curp_name_letters",
    "validate_curp",
]

Sexo = Literal["H", "M", "X"]

_ENTIDADES_RE = "|".join(sorted(CLAVES_CURP))
CURP_RE = re.compile(
    r"^(?P<iniciales>[A-Z][AEIOUX][A-Z]{2})"
    r"(?P<anio>\d{2})(?P<mes>0[1-9]|1[0-2])(?P<dia>0[1-9]|[12]\d|3[01])"
    r"(?P<sexo>[HMX])"
    rf"(?P<entidad>{_ENTIDADES_RE})"
    r"(?P<consonantes>[B-DF-HJ-NP-TV-Z]{3})"
    # Las Reglas dicen 0-9 hasta 1999 y A-J desde 2000. Se acepta cualquier letra para no
    # rechazar claves válidas si RENAPO llega a usar más letras; el siglo sale igual.
    r"(?P<diferenciador>[0-9A-Z])"
    r"(?P<verificador>\d)$"
)

# Reglas, punto 1.7: partículas que no se consideran si son la primera palabra.
PARTICULAS_CURP = frozenset(
    {
        "DA",
        "DAS",
        "DE",
        "DEL",
        "DER",
        "DI",
        "DIE",
        "DD",
        "Y",
        "EL",
        "LA",
        "LOS",
        "LAS",
        "LE",
        "LES",
        "MAC",
        "MC",
        "VAN",
        "VON",
    }
)
# Reglas, puntos 1.3 y 1.16 (sin el punto final, que se quita antes de comparar).
NOMBRES_COMUNES_CURP = frozenset({"MARIA", "MA", "M", "JOSE", "J"})
# Reglas, puntos 1.4 y 1.18: caracteres especiales que generan una "X" en su posición.
# El guion no está porque separa apellidos compuestos (punto 1.5).
# Diagonal, punto, apóstrofo recto y acento grave, más (por código Unicode) los apóstrofos
# tipográficos U+2019 y U+2018, el acento agudo suelto U+00B4 y la diéresis suelta U+00A8.
_ESPECIALES = frozenset("/.'`" + "".join(map(chr, (0x2019, 0x2018, 0x00B4, 0x00A8))))

# Anexo 01 de las Reglas (no publicado): lista de uso público. PEDO y JOTO están
# confirmadas por los ejemplos del punto 1.8.
_ALTISONANTES_CURP = """
    BACA BAKA BUEI BUEY CACA CACO CAGA CAGO CAKA CAKO COGE COGI COJA COJE COJI COJO COLA
    CULO FALO FETO GETA GUEI GUEY JETA JOTO KACA KACO KAGA KAGO KAKA KAKO KOGE KOGI KOJA
    KOJE KOJI KOJO KOLA KULO LILO LOCA LOCO LOKA LOKO MAME MAMO MEAR MEAS MEON MIAR MION
    MOCO MOKO MULA MULO NACA NACO PEDA PEDO PENE PIPI PITO POPO PUTA PUTO QULO RATA ROBA
    ROBE ROBO RUIN SENO TETA VACA VAGA VAGO VAKA VUEI VUEY WUEI WUEY
"""
PALABRAS_ALTISONANTES_CURP = frozenset(_ALTISONANTES_CURP.split())

# Diccionario del dígito verificador: el valor de cada carácter es su índice.
_DICCIONARIO_VERIFICADOR = "0123456789ABCDEFGHIJKLMNÑOPQRSTUVWXYZ"


# ---------------------------------------------------------------------------
# Construcción
# ---------------------------------------------------------------------------
def _palabra(text: str | None, *, es_nombre: bool) -> str:
    words = palabras_para_clave(text)
    words = quitar_iniciales(
        words,
        particulas=PARTICULAS_CURP,
        nombres_comunes=NOMBRES_COMUNES_CURP if es_nombre else frozenset(),
    )
    return words[0] if words else ""


def _inicial(word: str) -> str:
    if not word:
        return "X"
    first = word[0]
    return first if first in LETRAS else "X"  # Ñ y caracteres especiales -> X


def _vocal_interna(word: str) -> str:
    for char in word[1:]:
        if char in _ESPECIALES:
            return "X"
        if char in VOCALES:
            return char
    return "X"


def _consonante_interna(word: str) -> str:
    for char in word[1:]:
        if char in _ESPECIALES or char == "Ñ":
            return "X"
        if char in LETRAS and char not in VOCALES:
            return char
    return "X"


def curp_name_letters(
    nombre: str | None,
    apellido_paterno: str | None,
    apellido_materno: str | None,
    *,
    aplicar_altisonantes: bool = True,
) -> tuple[str, str]:
    """Las letras de la CURP que salen del nombre: posiciones 1-4 y 14-16.

    Un apellido vacío o ``None`` se trata como inexistente (se asigna "X").
    """
    paterno = _palabra(apellido_paterno, es_nombre=False)
    materno = _palabra(apellido_materno, es_nombre=False)
    nombre_ = _palabra(nombre, es_nombre=True)

    iniciales = _inicial(paterno) + (_vocal_interna(paterno) if paterno else "X")
    iniciales += _inicial(materno) + _inicial(nombre_)
    if aplicar_altisonantes and iniciales in PALABRAS_ALTISONANTES_CURP:
        iniciales = iniciales[0] + "X" + iniciales[2:]

    consonantes = "".join(_consonante_interna(w) for w in (paterno, materno, nombre_))
    return iniciales, consonantes


def curp_check_digit(first17: str) -> str:
    """Dígito verificador (posición 18) para los primeros 17 caracteres."""
    if len(first17) != 17:
        raise ValueError("Se esperaban 17 caracteres.")
    try:
        total = sum(
            _DICCIONARIO_VERIFICADOR.index(char) * (18 - position)
            for position, char in enumerate(first17)
        )
    except ValueError:
        raise ValueError("Carácter fuera del diccionario de la CURP.") from None
    return str((10 - total % 10) % 10)


def build_curp(
    *,
    nombre: str,
    apellido_paterno: str,
    apellido_materno: str | None,
    fecha_nacimiento: date,
    sexo: Sexo,
    clave_entidad: str,
    diferenciador: str | None = None,
) -> str:
    """Construye una CURP con su dígito verificador. Uso: datos sintéticos y pruebas.

    ``diferenciador`` es el carácter 17, que en la realidad asigna RENAPO para distinguir
    homonimias. Por defecto es "0" para nacimientos hasta 1999 y "A" desde 2000.
    """
    if sexo not in ("H", "M", "X"):
        raise ValueError("El sexo debe ser H, M o X.")
    if clave_entidad not in CLAVES_CURP:
        raise ValueError("Clave de entidad desconocida.")
    if not 1900 <= fecha_nacimiento.year <= 2099:
        raise ValueError("La CURP solo representa años de 1900 a 2099.")
    siglo_xxi = fecha_nacimiento.year >= 2000
    if diferenciador is None:
        diferenciador = "A" if siglo_xxi else "0"
    if siglo_xxi != diferenciador.isalpha() or len(diferenciador) != 1:
        raise ValueError("El diferenciador debe ser un dígito hasta 1999 y una letra desde 2000.")

    iniciales, consonantes = curp_name_letters(nombre, apellido_paterno, apellido_materno)
    first17 = (
        f"{iniciales}{fecha_nacimiento:%y%m%d}{sexo}{clave_entidad}{consonantes}{diferenciador}"
    )
    return first17 + curp_check_digit(first17)


# ---------------------------------------------------------------------------
# Validación
# ---------------------------------------------------------------------------
class CurpInfo(BaseModel):
    """Datos que se derivan de una CURP con formato válido."""

    model_config = ConfigDict(frozen=True)

    curp: str
    iniciales: str
    fecha_nacimiento: date
    sexo: Sexo
    clave_entidad: str
    nacido_en_extranjero: bool
    digito_verificador_valido: bool


class CurpValidation(BaseModel):
    model_config = ConfigDict(frozen=True)

    curp: str
    """La CURP en forma canónica (mayúsculas, sin espacios)."""
    info: CurpInfo | None
    """``None`` si el formato no es válido."""
    warnings: tuple[ExtractionWarning, ...] = ()

    @property
    def valid(self) -> bool:
        """Formato y dígito verificador correctos."""
        return self.info is not None and self.info.digito_verificador_valido


def _parse(curp: str) -> CurpInfo | None:
    match = CURP_RE.match(curp)
    if not match:
        return None
    siglo = 2000 if match["diferenciador"].isalpha() else 1900
    try:
        fecha = date(siglo + int(match["anio"]), int(match["mes"]), int(match["dia"]))
    except ValueError:  # 30 de febrero, 29 de febrero en año no bisiesto
        return None
    return CurpInfo(
        curp=curp,
        iniciales=match["iniciales"],
        fecha_nacimiento=fecha,
        sexo=match["sexo"],  # type: ignore[arg-type]
        clave_entidad=match["entidad"],
        nacido_en_extranjero=match["entidad"] == NACIDO_EN_EXTRANJERO,
        digito_verificador_valido=curp_check_digit(curp[:17]) == match["verificador"],
    )


def validate_curp(text: str | None, *, docs: tuple[DocType, ...] = ()) -> CurpValidation:
    """Valida formato y dígito verificador, y deriva fecha, sexo y entidad de nacimiento."""
    curp = clean_identifier(text)
    info = _parse(curp)
    warnings: list[ExtractionWarning] = []
    if info is None:
        warnings.append(
            make_warning(
                WarningCode.CURP_FORMATO_INVALIDO,
                "La CURP no tiene el formato oficial de 18 caracteres.",
                fields=("curp",),
                docs=docs,
            )
        )
    else:
        if not info.digito_verificador_valido:
            warnings.append(
                make_warning(
                    WarningCode.CURP_DIGITO_VERIFICADOR_INVALIDO,
                    "El dígito verificador de la CURP no corresponde: puede haber un carácter "
                    "mal leído.",
                    fields=("curp",),
                    docs=docs,
                )
            )
        if info.nacido_en_extranjero:
            warnings.append(
                make_warning(
                    WarningCode.CURP_NACIDO_EN_EXTRANJERO,
                    "La CURP indica nacimiento en el extranjero: confirma la nacionalidad.",
                    fields=("nacionalidad",),
                    docs=docs,
                )
            )
    return CurpValidation(curp=curp, info=info, warnings=tuple(warnings))


def _iniciales_coinciden(curp_iniciales: str, esperadas: str, esperadas_sin_filtro: str) -> bool:
    if curp_iniciales == esperadas:
        return True
    # Lista de altisonantes incompleta: RENAPO puso "X" en la posición 2 por una palabra que
    # no tenemos. Las otras tres letras deben coincidir.
    return curp_iniciales[1] == "X" and (
        curp_iniciales[0] + curp_iniciales[2:] == esperadas_sin_filtro[0] + esperadas_sin_filtro[2:]
    )


def check_curp_consistency(
    info: CurpInfo,
    *,
    nombre: str | None = None,
    apellido_paterno: str | None = None,
    apellido_materno: str | None = None,
    fecha_nacimiento: date | None = None,
    sexo: str | None = None,
    docs: tuple[DocType, ...] = (),
) -> list[ExtractionWarning]:
    """Compara lo que codifica la CURP contra los datos extraídos de los documentos.

    Se comparan las posiciones que las Reglas de RENAPO declaran verificables: las cuatro
    primeras letras, la fecha de nacimiento y el sexo. Las consonantes internas (14-16) no se
    comparan para no generar advertencias falsas en casos que las Reglas resuelven a mano.
    ``None`` significa "no se extrajo" y no se compara; para el apellido materno, ``""``
    significa "no tiene".
    """
    warnings: list[ExtractionWarning] = []
    if fecha_nacimiento is not None and fecha_nacimiento != info.fecha_nacimiento:
        warnings.append(
            make_warning(
                WarningCode.CURP_DATOS_NO_COINCIDEN,
                "La fecha de nacimiento no coincide con la que codifica la CURP.",
                fields=("curp", "fecha_nacimiento"),
                docs=docs,
            )
        )
    if sexo is not None and sexo.strip().upper()[:1] != info.sexo:
        warnings.append(
            make_warning(
                WarningCode.CURP_DATOS_NO_COINCIDEN,
                "El sexo no coincide con el que codifica la CURP.",
                fields=("curp",),
                docs=docs,
            )
        )
    if nombre and apellido_paterno and apellido_materno is not None:
        esperadas, _ = curp_name_letters(nombre, apellido_paterno, apellido_materno)
        sin_filtro, _ = curp_name_letters(
            nombre, apellido_paterno, apellido_materno, aplicar_altisonantes=False
        )
        if not _iniciales_coinciden(info.iniciales, esperadas, sin_filtro):
            warnings.append(
                make_warning(
                    WarningCode.CURP_DATOS_NO_COINCIDEN,
                    "Las primeras cuatro letras de la CURP no corresponden al nombre y los "
                    "apellidos.",
                    fields=("curp", "nombre", "apellido_paterno", "apellido_materno"),
                    docs=docs,
                )
            )
    return warnings
