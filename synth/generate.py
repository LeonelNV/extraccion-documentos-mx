"""Orquesta la generación: persona → 4 documentos → archivos y ground truth → manifiestos.

Reproducibilidad: cada persona tiene su propia semilla, derivada de (semilla global, split,
índice). El resultado no depende del orden ni del número de procesos.
"""

import hashlib
import json
import random
import shutil
from collections import Counter, defaultdict
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import timedelta
from functools import cache
from importlib.metadata import version
from pathlib import Path

import numpy as np
from faker import Faker

import synth
from docextract.dataset import (
    DatasetInfo,
    DocumentTruth,
    ExpectedWarning,
    Modality,
    PersonTruth,
    Split,
)
from docextract.entidades import NACIDO_EN_EXTRANJERO
from docextract.schemas import DocType, WarningCode
from docextract.validators.rfc import check_rfc_against_curp
from docextract.validators.sepomex import SepomexCatalog
from synth import modalities
from synth.config import SynthConfig
from synth.persona import Persona, generate_domicilio, generate_persona
from synth.render import comprobante, csf, curp, ine
from synth.render.common import DocContext, Rendered, fea

__all__ = [
    "PersonaPlan",
    "default_plan",
    "generate_dataset",
    "generate_person",
    "load_complete",
    "samples_plan",
]

SPLITS: tuple[Split, ...] = ("train", "val", "test")
DOC_ORDER = (DocType.CURP, DocType.INE, DocType.CSF, DocType.COMPROBANTE_DOMICILIO)
STEM = {
    DocType.CURP: "curp",
    DocType.INE: "ine",
    DocType.CSF: "csf",
    DocType.COMPROBANTE_DOMICILIO: "comprobante",
}
MODALITY_ORDER = (Modality.DIGITAL, Modality.ESCANEO, Modality.FOTO)
INCONSISTENCIAS = ("domicilio_ine_distinto", "comprobante_antiguo", "errata_nombre")
DOMICILIO_FIELDS = (
    "calle",
    "numero_exterior",
    "numero_interior",
    "colonia",
    "ciudad",
    "estado",
    "codigo_postal",
)


@dataclass(frozen=True)
class PersonaPlan:
    """Qué persona generar. Los campos opcionales fuerzan decisiones (muestras versionadas)."""

    split: Split
    index: int
    comprobante: str | None = None
    modalidades: dict[DocType, Modality] | None = None
    sin_inconsistencia: bool = False

    @property
    def persona_id(self) -> str:
        return f"{self.split}-{self.index:05d}"


def default_plan(config: SynthConfig) -> list[PersonaPlan]:
    counts = config.personas.model_dump()
    return [PersonaPlan(split, i) for split in SPLITS for i in range(counts[split])]


def samples_plan() -> list[PersonaPlan]:
    """Muestras versionadas: cada diseño de comprobante y cada modalidad al menos una vez."""
    todas = lambda m: dict.fromkeys(DOC_ORDER, m)  # noqa: E731
    mixtas = {
        DocType.CURP: Modality.DIGITAL,
        DocType.INE: Modality.FOTO,
        DocType.CSF: Modality.ESCANEO,
        DocType.COMPROBANTE_DOMICILIO: Modality.FOTO,
    }
    return [
        PersonaPlan("train", 0, "luz", todas(Modality.DIGITAL), sin_inconsistencia=True),
        PersonaPlan("train", 1, "agua", todas(Modality.FOTO), sin_inconsistencia=True),
        PersonaPlan("train", 2, "banco", todas(Modality.ESCANEO), sin_inconsistencia=True),
        PersonaPlan("test", 0, "telefono", mixtas, sin_inconsistencia=True),
    ]


def persona_seed(seed: int, split: str, index: int) -> int:
    digest = hashlib.sha256(f"{seed}:{split}:{index}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


@cache
def _faker() -> Faker:
    return Faker("es_MX")


# ---------------------------------------------------------------------------
# Formulario esperado y advertencias esperadas
# ---------------------------------------------------------------------------
def expected_form(p: Persona) -> dict[str, str]:
    """El formulario como debe quedar en la FEA: mayúsculas, sin acentos, con Ñ."""
    d = p.domicilio
    return {
        "curp": p.curp,
        "rfc": p.rfc,
        "nombre": fea(p.nombre),
        "apellido_paterno": fea(p.apellido_paterno),
        "apellido_materno": fea(p.apellido_materno),
        "fecha_nacimiento": p.fecha_nacimiento.isoformat(),
        # Los nacidos en el extranjero del dataset son mexicanos; la fusión debe pedir revisión.
        "nacionalidad": "MX",
        "calle": fea(d.calle),
        "numero_exterior": fea(d.numero_exterior),
        "numero_interior": fea(d.numero_interior),
        "colonia": fea(d.colonia),
        "ciudad": fea(d.ciudad),
        "estado": fea(d.estado),
        "codigo_postal": d.codigo_postal,
    }


def _natural_warnings(p: Persona) -> list[ExpectedWarning]:
    """Advertencias que la persona produce sin inconsistencias inyectadas."""
    warnings = []
    if p.clave_entidad_nacimiento == NACIDO_EN_EXTRANJERO:
        warnings.append(
            ExpectedWarning(
                code=WarningCode.CURP_NACIDO_EN_EXTRANJERO,
                kind="nacido_extranjero",
                docs=(DocType.CURP,),
                fields=("nacionalidad",),
            )
        )
    if check_rfc_against_curp(p.rfc, p.curp):
        # SAT y RENAPO resuelven distinto algunos casos (p. ej. un solo apellido).
        warnings.append(
            ExpectedWarning(
                code=WarningCode.RFC_NO_COINCIDE_CON_CURP,
                kind="reglas_sat_renapo",
                docs=(DocType.CSF, DocType.CURP),
                fields=("rfc", "curp"),
            )
        )
    return warnings


def _errata(text: str, rng: random.Random) -> str:
    """Cambia una letra interna por otra (error de captura en un documento)."""
    positions = [i for i, c in enumerate(text) if i > 0 and c.isalpha()]
    if not positions:
        return text + "Z"
    i = rng.choice(positions)
    nueva = rng.choice([c for c in "ABCDEFGHIJKLMNOPRSTUVZ" if c != text[i].upper()])
    nueva = nueva if text[i].isupper() else nueva.lower()
    return text[:i] + nueva + text[i + 1 :]


# ---------------------------------------------------------------------------
# Una persona
# ---------------------------------------------------------------------------
def _render(doc_type: DocType, ctx: DocContext, diseno: str) -> tuple[str, Rendered]:
    if doc_type is DocType.CURP:
        return curp.TEMPLATE, curp.render(ctx)
    if doc_type is DocType.INE:
        return ine.TEMPLATE, ine.render(ctx)
    if doc_type is DocType.CSF:
        return csf.TEMPLATE, csf.render(ctx)
    return comprobante.template_name(diseno), comprobante.render(ctx, diseno)


def generate_person(
    plan: PersonaPlan, config: SynthConfig, catalog: SepomexCatalog, root: Path
) -> PersonTruth:
    """Genera la persona, escribe sus documentos en ``root/<split>/<persona_id>/`` y devuelve
    su ground truth (que también queda en ``ground_truth.json``)."""
    seed = persona_seed(config.seed, plan.split, plan.index)
    rng = random.Random(seed)
    faker = _faker()
    faker.seed_instance(seed)
    persona = generate_persona(plan.persona_id, rng, faker, catalog, config)

    # Decisiones por documento
    diseno = plan.comprobante or (
        config.comprobante.plantilla_no_vista
        if plan.split == "test" and rng.random() < config.comprobante.fraccion_no_vista_test
        else rng.choice(config.comprobante.plantillas_train)
    )
    modalidades = plan.modalidades or {
        doc: rng.choices(MODALITY_ORDER, weights=config.modalidades[doc])[0] for doc in DOC_ORDER
    }
    dias = int(rng.random() * config.comprobante.dias_emision_max)
    fecha_comprobante = config.reference_date - timedelta(days=dias)

    # Contextos base (todos los documentos con los datos de la persona)
    base = DocContext(
        persona=persona,
        nombre=persona.nombre,
        apellido_paterno=persona.apellido_paterno,
        apellido_materno=persona.apellido_materno,
        domicilio=persona.domicilio,
        reference_date=config.reference_date,
        fecha_emision=config.reference_date - timedelta(days=rng.randint(0, 30)),
        rng=rng,
    )
    contextos = {doc: base for doc in DOC_ORDER}
    contextos[DocType.COMPROBANTE_DOMICILIO] = replace(base, fecha_emision=fecha_comprobante)

    # Inconsistencia inyectada (a lo sumo una por persona)
    expected = _natural_warnings(persona)
    tags = list(persona.tags)
    if not plan.sin_inconsistencia and rng.random() < config.tasas.inconsistencia:
        kind = rng.choice(INCONSISTENCIAS)
        tags.append(f"inconsistencia:{kind}")
        if kind == "domicilio_ine_distinto":
            otro = generate_domicilio(rng, faker, catalog, config)
            contextos[DocType.INE] = replace(contextos[DocType.INE], domicilio=otro)
            expected.append(
                ExpectedWarning(
                    code=WarningCode.DOMICILIO_NO_COINCIDE,
                    kind=kind,
                    docs=(DocType.INE, DocType.COMPROBANTE_DOMICILIO),
                    fields=DOMICILIO_FIELDS,
                )
            )
        elif kind == "comprobante_antiguo":
            antigua = config.reference_date - timedelta(days=rng.randint(100, 365))
            contextos[DocType.COMPROBANTE_DOMICILIO] = replace(
                contextos[DocType.COMPROBANTE_DOMICILIO], fecha_emision=antigua
            )
            expected.append(
                ExpectedWarning(
                    code=WarningCode.COMPROBANTE_ANTIGUO,
                    kind=kind,
                    docs=(DocType.COMPROBANTE_DOMICILIO,),
                    fields=("fecha_emision",),
                )
            )
        else:  # errata_nombre
            doc = rng.choice((DocType.INE, DocType.CSF))
            contextos[doc] = replace(
                contextos[doc], apellido_paterno=_errata(persona.apellido_paterno, rng)
            )
            expected.append(
                ExpectedWarning(
                    code=WarningCode.NOMBRE_NO_COINCIDE,
                    kind=kind,
                    docs=(DocType.CURP, doc),
                    fields=("apellido_paterno",),
                )
            )

    # Documentos
    folder = root / plan.split / plan.persona_id
    folder.mkdir(parents=True, exist_ok=True)
    documents = []
    for doc in DOC_ORDER:
        ctx = replace(contextos[doc], rng=random.Random(rng.getrandbits(64)))
        template, rendered = _render(doc, ctx, diseno)
        modality = modalidades[doc]
        stem = STEM[doc]
        rel = f"{plan.split}/{plan.persona_id}"
        image_rel = None
        params: dict[str, float] = {}
        if modality is Modality.DIGITAL:
            pdf = rendered.pdf
        else:
            page = modalities.rasterize(rendered.pdf, config.dpi)
            np_rng = np.random.default_rng(rng.getrandbits(64))
            degrade = modalities.scan if modality is Modality.ESCANEO else modalities.foto
            image, params = degrade(page, np_rng)
            jpeg = modalities.to_jpeg(image, int(params["jpeg_quality"]))
            (folder / f"{stem}.jpg").write_bytes(jpeg)
            image_rel = f"{rel}/{stem}.jpg"
            pdf = modalities.image_pdf(jpeg, title=stem)
        (folder / f"{stem}.pdf").write_bytes(pdf)
        documents.append(
            DocumentTruth(
                persona_id=plan.persona_id,
                doc_type=doc,
                template=template,
                template_seen_in_train=diseno != config.comprobante.plantilla_no_vista
                or doc is not DocType.COMPROBANTE_DOMICILIO,
                modality=modality,
                pdf=f"{rel}/{stem}.pdf",
                image=image_rel,
                fields=rendered.fields,
                augmentation=params,
            )
        )

    truth = PersonTruth(
        persona_id=plan.persona_id,
        split=plan.split,
        form=expected_form(persona),
        documents=tuple(documents),
        expected_warnings=tuple(expected),
        tags=tuple(sorted(set(tags))),
    )
    # ground_truth.json se escribe al final y de forma atómica: marca a la persona como
    # terminada (ver load_complete).
    tmp = folder / "ground_truth.json.tmp"
    tmp.write_text(truth.model_dump_json(indent=2) + "\n", encoding="utf-8")
    tmp.replace(folder / "ground_truth.json")
    return truth


# ---------------------------------------------------------------------------
# Reanudar
# ---------------------------------------------------------------------------
def _file_is_complete(path: Path) -> bool:
    """El archivo existe y termina como debe. Tras un apagado inesperado, los últimos
    archivos escritos pueden quedar truncados o llenos de ceros aunque existan."""
    try:
        size = path.stat().st_size
        if size == 0:
            return False
        with path.open("rb") as f:
            f.seek(max(0, size - 64))
            tail = f.read()
    except OSError:
        return False
    if path.suffix == ".pdf":
        return b"%%EOF" in tail
    if path.suffix == ".jpg":
        return tail.rstrip(b"\x00\r\n").endswith(b"\xff\xd9")
    return True


def load_complete(plan: PersonaPlan, root: Path) -> PersonTruth | None:
    """El ground truth de una persona ya generada, o ``None`` si está incompleta o dañada."""
    path = root / plan.split / plan.persona_id / "ground_truth.json"
    try:
        truth = PersonTruth.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    files = [root / rel for doc in truth.documents for rel in (doc.pdf, doc.image) if rel]
    return truth if all(_file_is_complete(f) for f in files) else None


def _generate_or_load(
    plan: PersonaPlan, config: SynthConfig, catalog: SepomexCatalog, root: Path, resume: bool
) -> PersonTruth:
    if resume:
        if (done := load_complete(plan, root)) is not None:
            return done
        shutil.rmtree(root / plan.split / plan.persona_id, ignore_errors=True)
    return generate_person(plan, config, catalog, root)


# ---------------------------------------------------------------------------
# Dataset completo
# ---------------------------------------------------------------------------
_WORKER: dict[str, object] = {}


def _init_worker(config_json: str, catalog_path: str, root: str, resume: bool) -> None:
    _WORKER["config"] = SynthConfig.model_validate_json(config_json)
    _WORKER["catalog"] = SepomexCatalog.from_file(catalog_path)
    _WORKER["root"] = Path(root)
    _WORKER["resume"] = resume


def _work(plan: PersonaPlan) -> PersonTruth:
    return _generate_or_load(
        plan,
        _WORKER["config"],  # type: ignore[arg-type]
        _WORKER["catalog"],  # type: ignore[arg-type]
        _WORKER["root"],  # type: ignore[arg-type]
        _WORKER["resume"],  # type: ignore[arg-type]
    )


@dataclass
class _Counts:
    per_split: dict[str, Counter[str]] = field(default_factory=lambda: defaultdict(Counter))

    def add(self, truth: PersonTruth) -> None:
        counter = self.per_split[truth.split]
        counter["personas"] += 1
        for doc in truth.documents:
            counter["documentos"] += 1
            counter[f"tipo:{doc.doc_type}"] += 1
            counter[f"plantilla:{doc.template}"] += 1
            counter[f"modalidad:{doc.modality}"] += 1
        for warning in truth.expected_warnings:
            counter[f"advertencia:{warning.kind}"] += 1


def _library_versions() -> dict[str, str]:
    names = ("reportlab", "pypdfium2", "pillow", "numpy", "faker", "pydantic")
    return {name: version(name) for name in names}


def generate_dataset(
    config: SynthConfig,
    catalog: SepomexCatalog,
    root: Path,
    *,
    plan: Iterable[PersonaPlan] | None = None,
    workers: int = 1,
    catalog_path: Path | None = None,
    sepomex_sha256: str | None = None,
    resume: bool = False,
) -> DatasetInfo:
    """Genera todas las personas del plan y escribe manifiestos y ``dataset.json``.

    Con ``workers > 1`` cada proceso carga el catálogo desde ``catalog_path``. Con
    ``resume`` se conservan las personas ya completas (misma semilla = mismos archivos) y se
    regeneran las incompletas o dañadas.
    """
    plans = list(plan if plan is not None else default_plan(config))
    root.mkdir(parents=True, exist_ok=True)
    if workers > 1:
        if catalog_path is None:
            raise ValueError("Con varios procesos hace falta catalog_path.")
        with ProcessPoolExecutor(
            max_workers=workers,
            initializer=_init_worker,
            initargs=(config.model_dump_json(), str(catalog_path), str(root), resume),
        ) as pool:
            truths = list(pool.map(_work, plans, chunksize=4))
    else:
        truths = [_generate_or_load(p, config, catalog, root, resume) for p in plans]

    counts = _Counts()
    by_split: dict[str, list[PersonTruth]] = defaultdict(list)
    for truth in truths:
        counts.add(truth)
        by_split[truth.split].append(truth)
    for split, items in by_split.items():
        lines = [
            doc.model_dump_json()
            for truth in sorted(items, key=lambda t: t.persona_id)
            for doc in truth.documents
        ]
        (root / split / "manifest.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    info = DatasetInfo(
        generator_version=synth.__version__,
        seed=config.seed,
        reference_date=config.reference_date,
        config=json.loads(config.model_dump_json()),
        counts={split: dict(sorted(c.items())) for split, c in counts.per_split.items()},
        sepomex_sha256=sepomex_sha256,
        library_versions=_library_versions(),
    )
    (root / "dataset.json").write_text(info.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return info
