"""Validación y construcción del RFC de persona física (13 caracteres).

Estructura: 4 letras del nombre, fecha de nacimiento AAMMDD y 3 caracteres de homoclave
asignados por el SAT (2 para distinguir homonimias + 1 dígito verificador).

El SAT no publica en su sitio el algoritmo: circula un documento suyo entregado por
solicitud de acceso a la información, del que proviene la descripción de uso público que
se implementa aquí (ver ``docs/validaciones.md``). En consecuencia:

- **Validación:** se revisan la estructura, la fecha y el **dígito verificador**. Los dos
  primeros caracteres de la homoclave no se validan: el SAT puede asignar otros (homonimias,
  cambios de nombre), así que solo se exige que tengan el alfabeto correcto.
- **Construcción** (``build_rfc``): genera RFCs coherentes para los datos sintéticos. No
  promete reproducir el RFC que el SAT asignaría a una persona real.

El dígito verificador se puede comprobar contra RFCs reales, sin que salgan de la máquina,
con ``scripts/verificar_claves.py``.
"""

import re
from datetime import date

from pydantic import BaseModel, ConfigDict

from docextract.normalize import clean_identifier
from docextract.schemas import DocType, ExtractionWarning, WarningCode
from docextract.validators._common import (
    VOCALES,
    make_warning,
    palabras_para_clave,
    quitar_iniciales,
)

__all__ = [
    "RFC_GENERICOS",
    "RFC_PF_RE",
    "RfcValidation",
    "build_rfc",
    "check_rfc_against_curp",
    "rfc_check_digit",
    "validate_rfc",
]

RFC_PF_RE = re.compile(
    r"^(?P<letras>[A-ZÑ&]{4})(?P<anio>\d{2})(?P<mes>\d{2})(?P<dia>\d{2})"
    r"(?P<homonimia>[A-Z\d]{2})(?P<verificador>[A\d])$"
)

RFC_GENERICOS = frozenset({"XAXX010101000", "XEXX010101000"})
"""RFC genéricos del SAT: público en general (nacional) y residentes en el extranjero."""

PARTICULAS_RFC = frozenset({"DE", "DEL", "LA", "LOS", "LAS", "Y", "MC", "MAC", "VON", "VAN"})
NOMBRES_COMUNES_RFC = frozenset({"MARIA", "MA", "M", "JOSE", "J"})

# Palabras inconvenientes del SAT: la última letra se sustituye por "X".
_INCONVENIENTES_RFC = """
    BUEI BUEY CACA CACO CAGA CAGO CAKA CAKO COGE COJA COJE COJI COJO CULO FETO GUEY JOTO
    KACA KACO KAGA KAGO KOGE KOJO KAKA KULO MAME MAMO MEAR MEAS MEON MION MOCO MULA PEDA
    PEDO PENE PUTA PUTO QULO RATA RUIN
"""
PALABRAS_INCONVENIENTES_RFC = frozenset(_INCONVENIENTES_RFC.split())

# Valores para el dígito verificador.
_VALOR_VERIFICADOR = {
    **{str(d): d for d in range(10)},
    **{c: 10 + i for i, c in enumerate("ABCDEFGHIJKLMN")},
    "&": 24,
    **{c: 25 + i for i, c in enumerate("OPQRSTUVWXYZ")},
    " ": 37,
    "Ñ": 38,
}

# Valores para calcular los dos caracteres de homonimia.
_VALOR_HOMONIMIA = {
    " ": "00",
    **{str(d): f"{d:02d}" for d in range(10)},
    "&": "10",
    **{c: str(11 + i) for i, c in enumerate("ABCDEFGHI")},
    **{c: str(21 + i) for i, c in enumerate("JKLMNOPQR")},
    **{c: str(32 + i) for i, c in enumerate("STUVWXYZ")},
    "Ñ": "40",
}
_TABLA_HOMONIMIA = "123456789ABCDEFGHIJKLMNPQRSTUVWXYZ"  # 34 caracteres, sin 0 ni O


# ---------------------------------------------------------------------------
# Construcción
# ---------------------------------------------------------------------------
def _limpiar(words: list[str]) -> list[str]:
    """Deja solo letras (con Ñ) y &; quita palabras que quedan vacías."""
    cleaned = (re.sub(r"[^A-ZÑ&]", "", w) for w in words)
    return [w for w in cleaned if w]


def _sin_particulas(text: str | None) -> list[str]:
    words = _limpiar(palabras_para_clave(text))
    # Un apellido que solo tiene partículas (p. ej. "DE") se usa tal cual.
    return [w for w in words if w not in PARTICULAS_RFC] or words


def _letras(nombre: str, apellido_paterno: str, apellido_materno: str | None) -> str:
    paterno_words = _sin_particulas(apellido_paterno)
    materno_words = _sin_particulas(apellido_materno)
    nombre_words = quitar_iniciales(
        _limpiar(palabras_para_clave(nombre)),
        particulas=PARTICULAS_RFC,
        nombres_comunes=NOMBRES_COMUNES_RFC,
    )
    paterno = paterno_words[0] if paterno_words else ""
    materno = materno_words[0] if materno_words else ""
    nombre_ = nombre_words[0] if nombre_words else ""

    if not paterno and materno:  # un solo apellido, registrado como materno
        paterno, materno = materno, ""
    if not paterno:
        letras = "XX" + nombre_[:2]
    elif not materno:
        letras = paterno[:2] + nombre_[:2]
    elif len(paterno) <= 2:
        letras = paterno[0] + materno[0] + nombre_[:2]
    else:
        vocal = next((c for c in paterno[1:] if c in VOCALES), "X")
        letras = paterno[0] + vocal + materno[0] + nombre_[:1]
    letras = letras.ljust(4, "X")

    if letras in PALABRAS_INCONVENIENTES_RFC:
        letras = letras[:3] + "X"
    return letras


def _homonimia(nombre: str, apellido_paterno: str, apellido_materno: str | None) -> str:
    completo = " ".join(
        " ".join(_limpiar(palabras_para_clave(parte)))
        for parte in (apellido_paterno, apellido_materno or "", nombre)
        if parte
    )
    digitos = "0" + "".join(_VALOR_HOMONIMIA[c] for c in completo)
    total = sum(int(digitos[i : i + 2]) * int(digitos[i + 1]) for i in range(len(digitos) - 1))
    cociente, residuo = divmod(total % 1000, 34)
    return _TABLA_HOMONIMIA[cociente] + _TABLA_HOMONIMIA[residuo]


def rfc_check_digit(first12: str) -> str:
    """Dígito verificador (carácter 13) para los primeros 12 caracteres del RFC."""
    if len(first12) != 12:
        raise ValueError("Se esperaban 12 caracteres.")
    try:
        total = sum(
            _VALOR_VERIFICADOR[char] * (13 - position) for position, char in enumerate(first12)
        )
    except KeyError:
        raise ValueError("Carácter fuera del diccionario del RFC.") from None
    residuo = total % 11
    if residuo == 0:
        return "0"
    digito = 11 - residuo
    return "A" if digito == 10 else str(digito)


def build_rfc(
    *,
    nombre: str,
    apellido_paterno: str,
    apellido_materno: str | None,
    fecha_nacimiento: date,
) -> str:
    """Construye un RFC de persona física con homoclave. Uso: datos sintéticos y pruebas."""
    first10 = _letras(nombre, apellido_paterno, apellido_materno) + f"{fecha_nacimiento:%y%m%d}"
    first12 = first10 + _homonimia(nombre, apellido_paterno, apellido_materno)
    return first12 + rfc_check_digit(first12)


# ---------------------------------------------------------------------------
# Validación
# ---------------------------------------------------------------------------
class RfcValidation(BaseModel):
    model_config = ConfigDict(frozen=True)

    rfc: str
    """El RFC en forma canónica (mayúsculas, sin espacios ni guiones)."""
    formato_valido: bool
    digito_verificador_valido: bool
    generico: bool
    warnings: tuple[ExtractionWarning, ...] = ()

    @property
    def valid(self) -> bool:
        return self.formato_valido and self.digito_verificador_valido and not self.generico


def _fecha_valida(anio: str, mes: str, dia: str) -> bool:
    # El RFC no codifica el siglo: basta con que la fecha exista en alguno de los dos.
    for siglo in (1900, 2000):
        try:
            date(siglo + int(anio), int(mes), int(dia))
        except ValueError:
            continue
        return True
    return False


def validate_rfc(text: str | None, *, docs: tuple[DocType, ...] = ()) -> RfcValidation:
    """Valida estructura, fecha y dígito verificador de un RFC de persona física."""
    rfc = clean_identifier(text)
    if rfc in RFC_GENERICOS:
        warning = make_warning(
            WarningCode.RFC_GENERICO,
            "Es un RFC genérico del SAT, no el RFC de la persona.",
            fields=("rfc",),
            docs=docs,
        )
        return RfcValidation(
            rfc=rfc,
            formato_valido=True,
            digito_verificador_valido=True,
            generico=True,
            warnings=(warning,),
        )

    match = RFC_PF_RE.match(rfc)
    if not match or not _fecha_valida(match["anio"], match["mes"], match["dia"]):
        warning = make_warning(
            WarningCode.RFC_FORMATO_INVALIDO,
            "El RFC no tiene el formato de persona física (13 caracteres).",
            fields=("rfc",),
            docs=docs,
        )
        return RfcValidation(
            rfc=rfc,
            formato_valido=False,
            digito_verificador_valido=False,
            generico=False,
            warnings=(warning,),
        )

    check_ok = rfc_check_digit(rfc[:12]) == match["verificador"]
    warnings = ()
    if not check_ok:
        warnings = (
            make_warning(
                WarningCode.RFC_HOMOCLAVE_INVALIDA,
                "El dígito verificador de la homoclave no corresponde: puede haber un carácter "
                "mal leído.",
                fields=("rfc",),
                docs=docs,
            ),
        )
    return RfcValidation(
        rfc=rfc,
        formato_valido=True,
        digito_verificador_valido=check_ok,
        generico=False,
        warnings=warnings,
    )


def check_rfc_against_curp(
    rfc: str, curp: str, *, docs: tuple[DocType, ...] = ()
) -> list[ExtractionWarning]:
    """Compara los primeros 10 caracteres del RFC con los de la CURP.

    Normalmente coinciden, pero SAT y RENAPO aplican reglas distintas (Ñ, palabras
    inconvenientes, nombres con partículas), por eso una diferencia es advertencia y no
    error. En las letras, una "X" de cualquiera de las dos claves (sustitución por Ñ,
    carácter especial o palabra inconveniente) se acepta contra cualquier letra, y la Ñ del
    RFC contra la "X" de la CURP.
    """
    rfc, curp = clean_identifier(rfc), clean_identifier(curp)
    if len(rfc) < 10 or len(curp) < 10 or rfc in RFC_GENERICOS:
        return []
    letras_ok = all(c == r or "X" in (c, r) for c, r in zip(curp[:4], rfc[:4], strict=True))
    if letras_ok and rfc[4:10] == curp[4:10]:
        return []
    return [
        make_warning(
            WarningCode.RFC_NO_COINCIDE_CON_CURP,
            "Los primeros 10 caracteres del RFC no coinciden con los de la CURP.",
            fields=("rfc", "curp"),
            docs=docs,
        )
    ]
