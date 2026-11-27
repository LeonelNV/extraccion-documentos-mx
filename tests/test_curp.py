"""Pruebas de la CURP.

Todas las CURPs de este archivo las genera ``build_curp`` a partir de nombres y fechas
inventados; ninguna se copió de un documento, de internet ni de los ejemplos de RENAPO.
"""

from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from docextract.entidades import CLAVES_CURP
from docextract.schemas import WarningCode
from docextract.validators.curp import (
    CURP_RE,
    PALABRAS_ALTISONANTES_CURP,
    CurpInfo,
    build_curp,
    check_curp_consistency,
    curp_check_digit,
    curp_name_letters,
    validate_curp,
)

FECHA = date(1991, 4, 7)


def _curp(nombre: str, paterno: str, materno: str | None, **kwargs: object) -> str:
    datos: dict[str, object] = {
        "fecha_nacimiento": FECHA,
        "sexo": "M",
        "clave_entidad": "NT",
        **kwargs,
    }
    return build_curp(
        nombre=nombre,
        apellido_paterno=paterno,
        apellido_materno=materno,
        **datos,  # type: ignore[arg-type]
    )


def _codes(warnings: object) -> list[WarningCode]:
    return [w.code for w in warnings]  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Letras del nombre: casos especiales de las Reglas de RENAPO (cap. 5)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("nombre", "paterno", "materno", "iniciales", "consonantes"),
    [
        # Caso general: inicial y vocal interna del paterno, inicial del materno y del nombre.
        ("Laura", "Gómez", "Ruiz", "GORL", "MZR"),
        # 1.1 y 1.12: Ñ inicial -> X; Ñ como consonante interna -> X.
        ("Andrea", "Ñuñez", "Soto", "XUSA", "XTN"),
        ("Elena", "Iñiguez", "Cruz", "IICE", "XRL"),
        # 1.2: nombre compuesto -> primera palabra.
        ("Luis Alberto", "Ramos", "Vega", "RAVL", "MGS"),
        # 1.3 y 1.16: JOSE / MARIA y abreviaturas -> segunda palabra.
        ("José Luis", "Ramos", "Vega", "RAVL", "MGS"),
        ("María Fernanda", "Ramos", "Vega", "RAVF", "MGR"),
        ("Ma. Fernanda", "Ramos", "Vega", "RAVF", "MGR"),
        ("MA Fernanda", "Ramos", "Vega", "RAVF", "MGR"),
        ("J. Antonio", "Ramos", "Vega", "RAVA", "MGN"),
        ("M. Antonia", "Ramos", "Vega", "RAVA", "MGN"),
        ("María", "Ramos", "Vega", "RAVM", "MGR"),  # nombre simple: no se omite
        ("José", "Ramos", "Vega", "RAVJ", "MGS"),
        # 1.3 + 1.7: después de MARIA también se omiten las partículas.
        ("María del Carmen", "Ramos", "Vega", "RAVC", "MGR"),
        # 1.5: apellidos compuestos -> primera palabra; el guion separa.
        ("Sara", "Vidal-Ortega", "Luna", "VILS", "DNR"),
        ("Sara", "Vidal Ortega", "Luna", "VILS", "DNR"),
        # 1.7: partículas al inicio (también varias seguidas).
        ("Pablo", "de la Fuente", "Mc Allen", "FUAP", "NLB"),
        # DYKE: la Y es consonante, la primera vocal interna es la E. RIO no tiene consonante.
        ("Pablo", "Van Dyke", "Del Río", "DERP", "YXB"),
        # 1.4 y 1.18: caracteres especiales en la posición -> X.
        ("Liam", "O'Brian", "Paz", "OXPL", "XZM"),
        ("Liam", "Paz", "D/Arcy", "PADL", "ZXM"),
        # 1.6: diéresis en la U -> U.
        ("Rocío", "Agüero", "Lara", "AULR", "GRC"),
        # 1.9: sin vocal interna en el primer apellido -> X.
        ("Iván", "Krs", "Mora", "KXMI", "RRV"),
        # 1.10 y 1.14: un solo apellido -> X en las posiciones 3 y 15.
        ("Hugo", "Barrera", "", "BAXH", "RXG"),
        ("Hugo", "Barrera", None, "BAXH", "RXG"),
        # 1.13: sin consonante interna -> X.
        ("Ana", "Pea", "Oia", "PEOA", "XXN"),
        # Una sola letra.
        ("E", "U", "I", "UXIE", "XXX"),
    ],
)
def test_letras_del_nombre(
    nombre: str, paterno: str, materno: str | None, iniciales: str, consonantes: str
) -> None:
    assert curp_name_letters(nombre, paterno, materno) == (iniciales, consonantes)


def test_palabra_altisonante_cambia_la_segunda_letra_por_x() -> None:
    # PEÑA -> P,E; DIAZ -> D; OMAR -> O: "PEDO" está en el catálogo.
    assert curp_name_letters("Omar", "Peña", "Díaz") == ("PXDO", "XZM")
    assert curp_name_letters("Omar", "Peña", "Díaz", aplicar_altisonantes=False)[0] == "PEDO"


def test_catalogo_de_altisonantes_tiene_las_palabras_confirmadas_por_las_reglas() -> None:
    # Los ejemplos del punto 1.8 de las Reglas confirman estas dos.
    assert {"PEDO", "JOTO"} <= PALABRAS_ALTISONANTES_CURP
    assert all(len(p) == 4 and p.isalpha() for p in PALABRAS_ALTISONANTES_CURP)


@pytest.mark.parametrize("apostrofo", ["'", chr(0x2019), chr(0x2018), chr(0x00B4)])
def test_apostrofo_recto_o_tipografico_da_x(apostrofo: str) -> None:
    assert curp_name_letters("Liam", f"O{apostrofo}Brian", "Paz") == ("OXPL", "XZM")


def test_las_mayusculas_y_acentos_no_cambian_la_clave() -> None:
    assert _curp("maría josé", "pérez", "lópez") == _curp("MARIA JOSE", "PEREZ", "LOPEZ")


# ---------------------------------------------------------------------------
# Construcción
# ---------------------------------------------------------------------------
def test_build_curp_estructura() -> None:
    curp = _curp("Laura", "Gómez", "Ruiz", sexo="M", clave_entidad="NT")
    assert len(curp) == 18
    assert curp[:4] == "GORL"
    assert curp[4:10] == "910407"
    assert curp[10] == "M"
    assert curp[11:13] == "NT"
    assert curp[13:16] == "MZR"
    assert curp[16] == "0"  # diferenciador por defecto hasta 1999
    assert CURP_RE.match(curp)


def test_build_curp_siglo_xxi_usa_letra_en_la_posicion_17() -> None:
    curp = _curp("Laura", "Gómez", "Ruiz", fecha_nacimiento=date(2003, 1, 9))
    assert curp[16] == "A"
    info = validate_curp(curp).info
    assert info is not None
    assert info.fecha_nacimiento == date(2003, 1, 9)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sexo": "F"},
        {"clave_entidad": "ZZ"},
        {"fecha_nacimiento": date(1899, 12, 31)},
        {"fecha_nacimiento": date(1999, 1, 1), "diferenciador": "A"},
        {"fecha_nacimiento": date(2001, 1, 1), "diferenciador": "1"},
        {"diferenciador": "12"},
    ],
)
def test_build_curp_rechaza_datos_invalidos(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _curp("Laura", "Gómez", "Ruiz", **kwargs)


def test_digito_verificador_calculado_a_mano() -> None:
    # Cálculo independiente: valor del carácter (índice en el diccionario) por su peso
    # (18 para la posición 1, 17 para la 2, ...), suma, y 10 menos el residuo módulo 10.
    first17 = "GORL910407MNTMZR0"
    diccionario = {c: i for i, c in enumerate("0123456789ABCDEFGHIJKLMNÑOPQRSTUVWXYZ")}
    suma = sum(diccionario[c] * peso for c, peso in zip(first17, range(18, 1, -1), strict=True))
    assert curp_check_digit(first17) == str((10 - suma % 10) % 10)


def test_digito_verificador_rechaza_longitud_o_caracteres_invalidos() -> None:
    with pytest.raises(ValueError):
        curp_check_digit("GORL")
    with pytest.raises(ValueError):
        curp_check_digit("GORL910407MNTMZR*")


# ---------------------------------------------------------------------------
# Validación
# ---------------------------------------------------------------------------
def test_curp_valida_sin_advertencias() -> None:
    curp = _curp("Laura", "Gómez", "Ruiz", sexo="M", clave_entidad="NT")
    result = validate_curp(curp)
    assert result.valid
    assert result.warnings == ()
    assert result.info is not None
    assert result.info.fecha_nacimiento == FECHA
    assert result.info.sexo == "M"
    assert result.info.clave_entidad == "NT"
    assert not result.info.nacido_en_extranjero


def test_validate_curp_limpia_espacios_y_minusculas() -> None:
    curp = _curp("Laura", "Gómez", "Ruiz")
    spaced = f" {curp[:4].lower()} {curp[4:10]}-{curp[10:]} "
    result = validate_curp(spaced)
    assert result.curp == curp
    assert result.valid


@pytest.mark.parametrize("sexo", ["H", "M", "X"])
def test_sexo_h_m_y_x_son_validos_sin_advertencia(sexo: str) -> None:
    result = validate_curp(_curp("Laura", "Gómez", "Ruiz", sexo=sexo))
    assert result.valid
    assert result.warnings == ()
    assert result.info is not None
    assert result.info.sexo == sexo


def test_nacido_en_el_extranjero_advierte_sobre_la_nacionalidad() -> None:
    result = validate_curp(_curp("Laura", "Gómez", "Ruiz", clave_entidad="NE"))
    assert result.valid
    assert _codes(result.warnings) == [WarningCode.CURP_NACIDO_EN_EXTRANJERO]
    assert result.warnings[0].fields == ("nacionalidad",)


def test_digito_verificador_incorrecto() -> None:
    curp = _curp("Laura", "Gómez", "Ruiz")
    otro = str((int(curp[17]) + 1) % 10)
    result = validate_curp(curp[:17] + otro)
    assert not result.valid
    assert result.info is not None  # los datos derivados siguen disponibles
    assert _codes(result.warnings) == [WarningCode.CURP_DIGITO_VERIFICADOR_INVALIDO]


def _reemplaza(curp: str, posicion: int, caracter: str) -> str:
    return curp[:posicion] + caracter + curp[posicion + 1 :]


@pytest.mark.parametrize(
    ("posicion", "caracter"),
    [
        (1, "B"),  # posición 2 debe ser vocal o X
        (4, "A"),  # año numérico
        (6, "2"),  # mes 2x
        (8, "4"),  # día 4x
        (10, "F"),  # sexo
        (11, "Z"),  # entidad ZZ/ZT
        (13, "A"),  # consonante interna
        (17, "A"),  # verificador numérico
    ],
)
def test_formato_invalido(posicion: int, caracter: str) -> None:
    curp = _reemplaza(_curp("Laura", "Gómez", "Ruiz"), posicion, caracter)
    result = validate_curp(curp)
    assert result.info is None
    assert _codes(result.warnings) == [WarningCode.CURP_FORMATO_INVALIDO]


@pytest.mark.parametrize("texto", ["", None, "GORL910407", "GORL910407MNTMZR0" + "12"])
def test_longitud_invalida(texto: str | None) -> None:
    assert _codes(validate_curp(texto).warnings) == [WarningCode.CURP_FORMATO_INVALIDO]


def test_fecha_inexistente_es_formato_invalido() -> None:
    first17 = "GORL910230MNTMZR0"  # 30 de febrero
    result = validate_curp(first17 + curp_check_digit(first17))
    assert result.info is None


def test_el_mensaje_no_incluye_la_curp() -> None:
    curp = _curp("Laura", "Gómez", "Ruiz")
    for texto in (curp[:17] + "X", _reemplaza(curp, 17, str((int(curp[17]) + 1) % 10))):
        for warning in validate_curp(texto).warnings:
            assert curp[:10] not in warning.message


# ---------------------------------------------------------------------------
# Consistencia con los datos extraídos
# ---------------------------------------------------------------------------
def _info(curp: str) -> CurpInfo:
    info = validate_curp(curp).info
    assert info is not None
    return info


def test_consistencia_completa_sin_advertencias() -> None:
    info = _info(_curp("María Fernanda", "Gómez", "Ruiz", sexo="M"))
    warnings = check_curp_consistency(
        info,
        nombre="MARÍA FERNANDA",
        apellido_paterno="gómez",
        apellido_materno="Ruíz",
        fecha_nacimiento=FECHA,
        sexo="Mujer",
    )
    assert warnings == []


def test_fecha_distinta() -> None:
    info = _info(_curp("Laura", "Gómez", "Ruiz"))
    warnings = check_curp_consistency(info, fecha_nacimiento=date(1991, 4, 8))
    assert _codes(warnings) == [WarningCode.CURP_DATOS_NO_COINCIDEN]
    assert "fecha_nacimiento" in warnings[0].fields


def test_sexo_distinto() -> None:
    info = _info(_curp("Laura", "Gómez", "Ruiz", sexo="M"))
    assert _codes(check_curp_consistency(info, sexo="H")) == [WarningCode.CURP_DATOS_NO_COINCIDEN]


def test_nombre_distinto() -> None:
    info = _info(_curp("Laura", "Gómez", "Ruiz"))
    warnings = check_curp_consistency(
        info, nombre="Laura", apellido_paterno="Gámez", apellido_materno="Ruiz"
    )
    assert _codes(warnings) == [WarningCode.CURP_DATOS_NO_COINCIDEN]
    assert "apellido_paterno" in warnings[0].fields


def test_sin_apellido_materno_coincide_con_cadena_vacia() -> None:
    info = _info(_curp("Hugo", "Barrera", ""))
    assert (
        check_curp_consistency(info, nombre="Hugo", apellido_paterno="Barrera", apellido_materno="")
        == []
    )
    # Si otro documento sí trae materno, las iniciales ya no corresponden.
    assert check_curp_consistency(
        info, nombre="Hugo", apellido_paterno="Barrera", apellido_materno="Soto"
    )


def test_materno_no_extraido_no_se_compara() -> None:
    info = _info(_curp("Laura", "Gómez", "Ruiz"))
    assert check_curp_consistency(info, nombre="Laura", apellido_paterno="Gómez") == []


def test_altisonante_fuera_de_nuestra_lista_no_genera_advertencia() -> None:
    # Simula que RENAPO puso una X en la posición 2 por una palabra que no está en la lista.
    curp = _curp("Laura", "Gómez", "Ruiz")
    first17 = _reemplaza(curp, 1, "X")[:17]
    info = _info(first17 + curp_check_digit(first17))
    assert (
        check_curp_consistency(
            info, nombre="Laura", apellido_paterno="Gómez", apellido_materno="Ruiz"
        )
        == []
    )


# ---------------------------------------------------------------------------
# Propiedades
# ---------------------------------------------------------------------------
_letras = "ABCDEFGHIJKLMNÑOPQRSTUVWXYZÁÉÍÓÚÜabcdefghijklmnñopqrstuvwxyzáéíóúü"
_nombres = st.text(alphabet=_letras + " -.'/", min_size=1, max_size=30)


@given(
    nombre=_nombres,
    paterno=_nombres,
    materno=st.one_of(st.none(), st.just(""), _nombres),
    fecha=st.dates(min_value=date(1900, 1, 1), max_value=date(2099, 12, 31)),
    sexo=st.sampled_from(["H", "M", "X"]),
    entidad=st.sampled_from(sorted(CLAVES_CURP)),
)
def test_toda_curp_construida_es_valida_y_consistente(
    nombre: str,
    paterno: str,
    materno: str | None,
    fecha: date,
    sexo: str,
    entidad: str,
) -> None:
    curp = build_curp(
        nombre=nombre,
        apellido_paterno=paterno,
        apellido_materno=materno,
        fecha_nacimiento=fecha,
        sexo=sexo,  # type: ignore[arg-type]
        clave_entidad=entidad,
    )
    result = validate_curp(curp)
    assert result.valid
    assert result.info is not None
    assert (result.info.fecha_nacimiento, result.info.sexo, result.info.clave_entidad) == (
        fecha,
        sexo,
        entidad,
    )
    assert (
        check_curp_consistency(
            result.info,
            nombre=nombre,
            apellido_paterno=paterno,
            apellido_materno=materno,
            fecha_nacimiento=fecha,
            sexo=sexo,
        )
        == []
    )


@given(posicion=st.integers(min_value=0, max_value=16), data=st.data())
def test_un_caracter_cambiado_casi_siempre_se_detecta(posicion: int, data: st.DataObject) -> None:
    # El dígito verificador módulo 10 no detecta todos los cambios (p. ej. cuando el peso
    # por la diferencia es múltiplo de 10); se comprueba que, si no lo detecta, es por eso.
    curp = _curp("Laura", "Gómez", "Ruiz")
    original = curp[posicion]
    nuevo = data.draw(
        st.sampled_from([c for c in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ" if c != original])
    )
    cambiada = _reemplaza(curp, posicion, nuevo)
    diccionario = "0123456789ABCDEFGHIJKLMNÑOPQRSTUVWXYZ"
    delta = (diccionario.index(nuevo) - diccionario.index(original)) * (18 - posicion)
    detectado = curp_check_digit(cambiada[:17]) != cambiada[17]
    assert detectado == (delta % 10 != 0)
