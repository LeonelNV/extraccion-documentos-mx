"""Validación de domicilios contra el Catálogo Nacional de Códigos Postales (SEPOMEX).

El catálogo lo publica Correos de México en
https://www.correosdemexico.gob.mx/SSLServicios/ConsultaCP/CodigoPostal_Exportar.aspx
"para uso particular", sin permitir su comercialización ni su distribución. Por eso **no se
versiona**: ``make sepomex`` lo descarga a ``data/sepomex/`` (ignorado por git).

Formato del TXT (verificado con la descarga del 2026-11-26): Latin-1, delimitado por ``|``;
la primera línea es el aviso de uso y la segunda los nombres de columna. Cada CP pertenece a
un solo estado y a un solo municipio; un CP puede tener cientos de asentamientos.
"""

import os
import zipfile
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict
from rapidfuzz import fuzz

from docextract.config import ValidationConfig
from docextract.entidades import find_entidad
from docextract.normalize import address_key, normalize_codigo_postal
from docextract.schemas import DocType, ExtractionWarning, WarningCode
from docextract.validators._common import make_warning

__all__ = [
    "DEFAULT_PATH",
    "ENV_VAR",
    "AddressValidation",
    "Asentamiento",
    "SepomexCatalog",
    "SepomexNotAvailableError",
    "read_sepomex",
    "validate_address",
]

ENV_VAR = "DOCEXTRACT_SEPOMEX"
"""Variable de entorno para usar un catálogo en otra ruta."""

DEFAULT_PATH = Path(__file__).resolve().parents[3] / "data" / "sepomex" / "CPdescargatxt.zip"

ENCODING = "latin-1"
COLUMNS = (
    "d_codigo",
    "d_asenta",
    "d_tipo_asenta",
    "D_mnpio",
    "d_estado",
    "d_ciudad",
    "d_CP",
    "c_estado",
    "c_oficina",
    "c_CP",
    "c_tipo_asenta",
    "c_mnpio",
    "id_asenta_cpcons",
    "d_zona",
    "c_cve_ciudad",
)


class SepomexNotAvailableError(FileNotFoundError):
    """No se encontró el catálogo de SEPOMEX."""


@dataclass(frozen=True)
class Asentamiento:
    codigo_postal: str
    nombre: str
    tipo: str
    municipio: str
    estado: str
    ciudad: str
    """Vacía en dos tercios de los registros (zonas rurales)."""
    clave_estado: str
    clave_municipio: str
    zona: str


def _parse_text(text: str) -> list[Asentamiento]:
    lines = text.splitlines()
    header_index = next(
        (i for i, line in enumerate(lines[:5]) if line.startswith("d_codigo|")), None
    )
    if header_index is None:
        raise ValueError("No parece el catálogo de SEPOMEX: falta la línea de encabezados.")
    header = lines[header_index].split("|")
    missing = set(COLUMNS) - set(header)
    if missing:
        raise ValueError(f"Al catálogo le faltan columnas: {sorted(missing)}")
    col = {name: header.index(name) for name in COLUMNS}

    result: list[Asentamiento] = []
    for line in lines[header_index + 1 :]:
        if not line.strip():
            continue
        row = line.split("|")
        if len(row) != len(header):
            raise ValueError("Fila con un número de columnas distinto al encabezado.")
        result.append(
            Asentamiento(
                codigo_postal=row[col["d_codigo"]],
                nombre=row[col["d_asenta"]],
                tipo=row[col["d_tipo_asenta"]],
                municipio=row[col["D_mnpio"]],
                estado=row[col["d_estado"]],
                ciudad=row[col["d_ciudad"]],
                clave_estado=row[col["c_estado"]],
                clave_municipio=row[col["c_mnpio"]],
                zona=row[col["d_zona"]],
            )
        )
    return result


def read_sepomex(path: str | Path) -> list[Asentamiento]:
    """Lee el catálogo tal como se descarga: el ``.zip`` o el ``.txt`` que trae dentro."""
    path = Path(path)
    if not path.exists():
        raise SepomexNotAvailableError(path)
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            members = [n for n in archive.namelist() if n.lower().endswith(".txt")]
            if len(members) != 1:
                raise ValueError("El zip de SEPOMEX debe traer exactamente un .txt.")
            raw = archive.read(members[0])
    else:
        raw = path.read_bytes()
    return _parse_text(raw.decode(ENCODING))


# Tipos de asentamiento que pueden anteponerse al nombre de la colonia en un comprobante.
_PREFIJOS_COLONIA = (
    "UNIDAD HABITACIONAL",
    "CONJUNTO HABITACIONAL",
    "ZONA INDUSTRIAL",
    "FRACCIONAMIENTO",
    "CONDOMINIO",
    "RANCHERIA",
    "COLONIA",
    "BARRIO",
    "PUEBLO",
    "EJIDO",
    "RANCHO",
    "UH",
)


def _colonia_key(text: str | None) -> str:
    key = address_key(text)
    stripped = True
    while stripped:
        stripped = False
        for prefix in _PREFIJOS_COLONIA:
            if key.startswith(prefix + " "):
                key = key[len(prefix) + 1 :]
                stripped = True
    return key


# Peso de una coincidencia por subconjunto de palabras ("CENTRO" dentro de "TEPIC CENTRO"):
# alcanza el umbral por defecto, pero queda por debajo de una coincidencia completa.
_SUBSET_WEIGHT = 0.9


def _similarity(a: str, b: str) -> float:
    """Similitud 0-1: edición, orden de palabras o un nombre contenido en el otro."""
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    full = max(fuzz.ratio(a, b), fuzz.token_sort_ratio(a, b)) / 100
    subset = _SUBSET_WEIGHT * fuzz.token_set_ratio(a, b) / 100
    return max(full, subset)


class SepomexCatalog:
    """Catálogo en memoria, indexado por código postal."""

    def __init__(self, asentamientos: Iterable[Asentamiento]) -> None:
        by_cp: dict[str, list[Asentamiento]] = defaultdict(list)
        for asentamiento in asentamientos:
            by_cp[asentamiento.codigo_postal].append(asentamiento)
        self._by_cp = {cp: tuple(rows) for cp, rows in by_cp.items()}

    @classmethod
    def from_file(cls, path: str | Path) -> "SepomexCatalog":
        return cls(read_sepomex(path))

    @staticmethod
    def default_path() -> Path:
        return Path(os.environ[ENV_VAR]) if os.environ.get(ENV_VAR) else DEFAULT_PATH

    @classmethod
    def load_default(cls) -> "SepomexCatalog":
        """Carga el catálogo de ``data/sepomex/`` (o de ``$DOCEXTRACT_SEPOMEX``), una vez."""
        return _load_cached(cls.default_path())

    def __len__(self) -> int:
        return len(self._by_cp)

    def __contains__(self, codigo_postal: object) -> bool:
        return codigo_postal in self._by_cp

    def lookup(self, codigo_postal: str) -> tuple[Asentamiento, ...]:
        return self._by_cp.get(codigo_postal, ())

    def codigos_postales(self, *, clave_estado: str | None = None) -> list[str]:
        """CPs en orden, opcionalmente solo los de un estado (clave de 2 dígitos de SEPOMEX).

        El orden es estable para que un muestreo con semilla sea reproducible.
        """
        return sorted(
            cp
            for cp, rows in self._by_cp.items()
            if clave_estado is None or rows[0].clave_estado == clave_estado
        )

    def suggest_colonias(
        self, codigo_postal: str, colonia: str, *, limit: int = 3
    ) -> list[tuple[Asentamiento, float]]:
        """Asentamientos del CP ordenados por similitud con ``colonia`` (0-1)."""
        key = _colonia_key(colonia)
        ranked = []
        for asentamiento in self.lookup(codigo_postal):
            other = _colonia_key(asentamiento.nombre)
            # Desempate: entre dos coincidencias parciales gana la más parecida en total.
            ranked.append((_similarity(key, other), fuzz.ratio(key, other), asentamiento))
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [(asentamiento, score) for score, _, asentamiento in ranked[:limit]]


@cache
def _load_cached(path: Path) -> SepomexCatalog:
    if not path.exists():
        raise SepomexNotAvailableError(
            f"No está el catálogo de SEPOMEX en {path}. Descárgalo con `make sepomex`."
        )
    return SepomexCatalog.from_file(path)


class AddressValidation(BaseModel):
    """Resultado de validar un domicilio. Los datos ``*_catalogo`` salen de SEPOMEX."""

    model_config = ConfigDict(frozen=True)

    codigo_postal: str | None
    """CP normalizado a 5 dígitos; ``None`` si no tiene forma de CP."""
    estado_catalogo: str | None = None
    municipio_catalogo: str | None = None
    colonia_catalogo: str | None = None
    """Nombre oficial de la colonia, si la extraída coincide con una del CP."""
    sugerencias_colonia: tuple[str, ...] = ()
    """Colonias más parecidas del CP, si la extraída no coincide con ninguna."""
    warnings: tuple[ExtractionWarning, ...] = ()


def validate_address(
    catalog: SepomexCatalog,
    *,
    codigo_postal: str | None,
    estado: str | None = None,
    ciudad: str | None = None,
    colonia: str | None = None,
    config: ValidationConfig | None = None,
    docs: tuple[DocType, ...] = (),
) -> AddressValidation:
    """Valida CP, estado, ciudad o municipio y colonia contra SEPOMEX.

    ``None`` en un campo = no se extrajo y no se valida.
    """
    config = config or ValidationConfig()
    cp = normalize_codigo_postal(codigo_postal)
    if cp is None or cp not in catalog:
        message = (
            "El código postal no tiene 5 dígitos."
            if cp is None
            else "El código postal no existe en el catálogo de SEPOMEX."
        )
        warning = make_warning(
            WarningCode.CP_NO_EXISTE, message, fields=("codigo_postal",), docs=docs
        )
        return AddressValidation(codigo_postal=cp, warnings=(warning,))

    asentamientos = catalog.lookup(cp)
    first = asentamientos[0]
    warnings: list[ExtractionWarning] = []

    if estado is not None:
        entidad = find_entidad(estado)
        if entidad is None or entidad.clave_inegi != first.clave_estado:
            warnings.append(
                make_warning(
                    WarningCode.CP_NO_COINCIDE_CON_ESTADO,
                    "El estado no corresponde al código postal.",
                    fields=("codigo_postal", "estado"),
                    docs=docs,
                )
            )

    if ciudad is not None:
        ciudad_key = address_key(ciudad)
        candidatos = {address_key(first.municipio)} | {
            address_key(a.ciudad) for a in asentamientos if a.ciudad
        }
        best = max(_similarity(ciudad_key, c) for c in candidatos)
        if best < config.municipio_similarity_threshold:
            warnings.append(
                make_warning(
                    WarningCode.CP_NO_COINCIDE_CON_MUNICIPIO,
                    "La ciudad o municipio no corresponde al código postal.",
                    fields=("codigo_postal", "ciudad"),
                    docs=docs,
                )
            )

    colonia_catalogo: str | None = None
    sugerencias: tuple[str, ...] = ()
    if colonia is not None:
        ranked = catalog.suggest_colonias(cp, colonia)
        if ranked and ranked[0][1] >= config.colonia_similarity_threshold:
            colonia_catalogo = ranked[0][0].nombre
        else:
            sugerencias = tuple(a.nombre for a, _ in ranked)
            warnings.append(
                make_warning(
                    WarningCode.COLONIA_NO_ENCONTRADA,
                    "La colonia no se encontró entre los asentamientos del código postal.",
                    fields=("colonia",),
                    docs=docs,
                )
            )

    return AddressValidation(
        codigo_postal=cp,
        estado_catalogo=first.estado,
        municipio_catalogo=first.municipio,
        colonia_catalogo=colonia_catalogo,
        sugerencias_colonia=sugerencias,
        warnings=tuple(warnings),
    )
