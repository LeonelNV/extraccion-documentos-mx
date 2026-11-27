"""Personas ficticias coherentes: nombre, fecha, sexo, CURP, RFC y domicilio de SEPOMEX.

Los nombres de pila salen de listas propias por género: los de Faker ``es_MX`` no respetan el
género (``first_name_male`` devuelve nombres de mujer), y el sexo de la CURP debe ser
coherente con el nombre. Apellidos y calles salen de Faker.
"""

import random
from dataclasses import dataclass, field
from datetime import date, timedelta

from faker import Faker

from docextract.entidades import ENTIDADES, NACIDO_EN_EXTRANJERO
from docextract.validators.curp import Sexo, build_curp, curp_name_letters
from docextract.validators.rfc import build_rfc
from docextract.validators.sepomex import SepomexCatalog
from synth.config import SynthConfig

__all__ = ["Domicilio", "Persona", "generate_domicilio", "generate_persona"]

NOMBRES_H = (
    "Juan", "Luis", "Carlos", "Jorge", "Miguel", "Pedro", "Francisco", "Alejandro", "Ricardo",
    "Fernando", "Roberto", "Eduardo", "Javier", "Sergio", "Arturo", "Raúl", "Óscar", "Héctor",
    "Manuel", "Antonio", "Andrés", "Rubén", "Iván", "Martín", "Adrián", "Rodrigo", "Daniel",
    "Gerardo", "Alberto", "Ángel", "Jesús", "Hugo", "Tomás", "Joaquín", "Ramón", "Efraín",
    "Gustavo", "Emilio", "Salvador", "Ulises", "Ignacio", "Rogelio", "Saúl", "Benjamín",
)  # fmt: skip
NOMBRES_M = (
    "Ana", "Laura", "Patricia", "Gabriela", "Verónica", "Adriana", "Claudia", "Mónica",
    "Leticia", "Rosa", "Alejandra", "Daniela", "Fernanda", "Sofía", "Valeria", "Mariana",
    "Lucía", "Andrea", "Beatriz", "Carmen", "Elena", "Isabel", "Lourdes", "Guadalupe",
    "Silvia", "Teresa", "Yolanda", "Araceli", "Itzel", "Ximena", "Paola", "Karla", "Brenda",
    "Raquel", "Irma", "Norma", "Rocío", "Inés", "Dolores", "Esperanza", "Jimena", "Belén",
)  # fmt: skip
# Primer nombre de un nombre compuesto que la CURP y el RFC omiten.
JOSE_MARIA = {"H": ("José",), "M": ("María", "Ma.")}
APELLIDOS_PARTICULA = (
    "de la Cruz", "del Río", "de los Santos", "de León", "de la Torre", "del Valle",
    "de la Rosa", "de la Fuente", "del Ángel", "de Alba",
)  # fmt: skip
APELLIDOS_ENIE = (
    "Muñoz", "Núñez", "Ordóñez", "Peña", "Ibáñez", "Patiño", "Treviño", "Zúñiga", "Montaño",
    "Yáñez", "Cañedo", "Ñeco",
)  # fmt: skip
APELLIDOS_DIERESIS = ("Argüelles", "Agüero", "Güemes", "Sigüenza", "Argüello")

# Tipos de vialidad: el nombre de la calle siempre empieza con uno (la CSF los separa).
TIPOS_VIALIDAD = (
    "Calle", "Avenida", "Privada", "Cerrada", "Andador", "Boulevard", "Calzada", "Circuito",
    "Diagonal", "Viaducto", "Prolongación", "Callejón", "Retorno", "Periférico", "Corredor",
    "Pasaje", "Ampliación", "Eje",
)  # fmt: skip
NUMEROS_INTERIORES = ("A", "B", "C", "1", "2", "3", "4", "101", "202", "Depto. 3", "Local 2")


@dataclass(frozen=True)
class Domicilio:
    calle: str
    numero_exterior: str
    numero_interior: str
    """Cadena vacía si no hay número interior."""
    colonia: str
    tipo_asentamiento: str
    ciudad: str
    """La ciudad de SEPOMEX; si el CP no tiene, el municipio (así lo pide la FEA)."""
    municipio: str
    estado: str
    clave_estado: str
    codigo_postal: str

    @property
    def tipo_vialidad(self) -> str:
        return self.calle.split(" ", 1)[0]

    @property
    def nombre_vialidad(self) -> str:
        return self.calle.split(" ", 1)[1] if " " in self.calle else self.calle


@dataclass(frozen=True)
class Persona:
    persona_id: str
    nombre: str
    apellido_paterno: str
    apellido_materno: str
    """Cadena vacía si la persona no tiene segundo apellido."""
    fecha_nacimiento: date
    sexo: Sexo
    clave_entidad_nacimiento: str
    curp: str
    rfc: str
    domicilio: Domicilio
    tags: tuple[str, ...] = field(default=())

    @property
    def nombre_completo(self) -> str:
        return " ".join(p for p in (self.nombre, self.apellido_paterno, self.apellido_materno) if p)


def _calle(faker: Faker) -> str:
    calle = faker.street_name()
    if calle.split(" ", 1)[0] not in TIPOS_VIALIDAD:
        calle = f"Calle {calle}"
    return calle


def generate_domicilio(
    rng: random.Random, faker: Faker, catalog: SepomexCatalog, config: SynthConfig
) -> Domicilio:
    cps: list[str] = []
    if rng.random() < config.tasas.domicilio_nayarit:
        cps = catalog.codigos_postales(clave_estado="18")
    if not cps:
        cps = catalog.codigos_postales()
    if not cps:
        raise ValueError("El catálogo de SEPOMEX está vacío.")
    asentamiento = rng.choice(catalog.lookup(rng.choice(cps)))

    if rng.random() < config.tasas.sin_numero:
        numero_exterior = "S/N"
    else:
        numero_exterior = str(rng.randint(1, 3999))
        if rng.random() < 0.08:
            numero_exterior += rng.choice(("-A", "-B", " A", " Bis"))
    numero_interior = (
        rng.choice(NUMEROS_INTERIORES) if rng.random() < config.tasas.numero_interior else ""
    )
    return Domicilio(
        calle=_calle(faker),
        numero_exterior=numero_exterior,
        numero_interior=numero_interior,
        colonia=asentamiento.nombre,
        tipo_asentamiento=asentamiento.tipo,
        ciudad=asentamiento.ciudad or asentamiento.municipio,
        municipio=asentamiento.municipio,
        estado=asentamiento.estado,
        clave_estado=asentamiento.clave_estado,
        codigo_postal=asentamiento.codigo_postal,
    )


def _fecha_nacimiento(rng: random.Random, referencia: date) -> date:
    # Servidores públicos: entre 18 y 70 años.
    inicio = referencia.replace(year=referencia.year - 70)
    fin = referencia.replace(year=referencia.year - 18)
    return inicio + timedelta(days=rng.randint(0, (fin - inicio).days))


def _diferenciador(rng: random.Random, fecha: date) -> str:
    # Casi siempre la primera opción; a veces una homonimia.
    if fecha.year < 2000:
        return "0" if rng.random() < 0.85 else str(rng.randint(1, 9))
    return "A" if rng.random() < 0.85 else rng.choice("BCDEFGHIJ")


def generate_persona(
    persona_id: str,
    rng: random.Random,
    faker: Faker,
    catalog: SepomexCatalog,
    config: SynthConfig,
) -> Persona:
    tasas = config.tasas
    tags: list[str] = []

    genero = rng.choice("HM")
    sexo: Sexo = genero  # type: ignore[assignment]
    if rng.random() < tasas.sexo_x:
        sexo = "X"
        tags.append("sexo_x")

    nombres = NOMBRES_H if genero == "H" else NOMBRES_M
    nombre = rng.choice(nombres)
    if rng.random() < tasas.nombre_compuesto:
        segundo = rng.choice([n for n in nombres if n != nombre])
        if rng.random() < tasas.jose_maria / max(tasas.nombre_compuesto, 1e-9):
            nombre = rng.choice(JOSE_MARIA[genero])
            tags.append("jose_maria")
        nombre = f"{nombre} {segundo}"
        tags.append("nombre_compuesto")

    paterno = faker.last_name()
    materno = faker.last_name()
    if rng.random() < tasas.particula:
        paterno = rng.choice(APELLIDOS_PARTICULA)
        tags.append("particula")
    if rng.random() < tasas.enie:
        if rng.random() < 0.5:
            paterno = rng.choice(APELLIDOS_ENIE)
        else:
            materno = rng.choice(APELLIDOS_ENIE)
    if rng.random() < tasas.dieresis:
        paterno = rng.choice(APELLIDOS_DIERESIS)
    if rng.random() < tasas.sin_materno:
        materno = ""
        tags.append("sin_materno")
    if "Ñ" in (paterno + materno).upper():
        tags.append("enie")
    if "Ü" in (paterno + materno).upper():
        tags.append("dieresis")

    fecha = _fecha_nacimiento(rng, config.reference_date)
    if rng.random() < tasas.nacido_extranjero:
        entidad = NACIDO_EN_EXTRANJERO
        tags.append("nacido_extranjero")
    elif rng.random() < tasas.nacido_nayarit:
        entidad = "NT"
    else:
        entidad = rng.choice(ENTIDADES).clave_curp
    if fecha.year >= 2000:
        tags.append("siglo_xxi")

    curp = build_curp(
        nombre=nombre,
        apellido_paterno=paterno,
        apellido_materno=materno,
        fecha_nacimiento=fecha,
        sexo=sexo,
        clave_entidad=entidad,
        diferenciador=_diferenciador(rng, fecha),
    )
    sin_filtro, _ = curp_name_letters(nombre, paterno, materno, aplicar_altisonantes=False)
    if sin_filtro != curp[:4]:  # solo difieren si se aplicó una palabra altisonante
        tags.append("altisonante")
    rfc = build_rfc(
        nombre=nombre, apellido_paterno=paterno, apellido_materno=materno, fecha_nacimiento=fecha
    )

    domicilio = generate_domicilio(rng, faker, catalog, config)
    if domicilio.numero_interior:
        tags.append("numero_interior")
    if domicilio.numero_exterior == "S/N":
        tags.append("sin_numero")

    return Persona(
        persona_id=persona_id,
        nombre=nombre,
        apellido_paterno=paterno,
        apellido_materno=materno,
        fecha_nacimiento=fecha,
        sexo=sexo,
        clave_entidad_nacimiento=entidad,
        curp=curp,
        rfc=rfc,
        domicilio=domicilio,
        tags=tuple(sorted(set(tags))),
    )
