"""Modalidades de un documento: PDF digital, escaneo y foto de celular.

El PDF digital se rasteriza con pypdfium2 y se degrada con Pillow y numpy. Escaneo y foto se
entregan como el usuario los subiría: un PDF **sin capa de texto** que contiene la imagen,
y además el JPG por separado (lo usan los extractores de imagen y el entrenamiento).
"""

import io

import numpy as np
import pypdfium2 as pdfium
from PIL import Image, ImageEnhance, ImageFilter
from reportlab.lib.utils import ImageReader

from synth.render.common import new_canvas

__all__ = ["foto", "image_pdf", "rasterize", "scan", "to_jpeg"]


def rasterize(pdf: bytes, dpi: int) -> Image.Image:
    """Primera página del PDF como imagen RGB."""
    document = pdfium.PdfDocument(pdf)
    try:
        return document[0].render(scale=dpi / 72).to_pil().convert("RGB")
    finally:
        document.close()


def to_jpeg(image: Image.Image, quality: int) -> bytes:
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=quality, optimize=True)
    return out.getvalue()


def image_pdf(jpeg: bytes, *, title: str) -> bytes:
    """PDF de una página que solo contiene la imagen: sin capa de texto, como un escaneo."""
    image = Image.open(io.BytesIO(jpeg))
    width, height = image.size
    # Página a 150 ppp para que el tamaño físico sea razonable.
    page = (width * 72 / 150, height * 72 / 150)
    buffer = io.BytesIO()
    canvas = new_canvas(buffer, title=title, pagesize=page)
    canvas.drawImage(ImageReader(io.BytesIO(jpeg)), 0, 0, page[0], page[1])
    canvas.showPage()
    canvas.save()
    return buffer.getvalue()


def _noise(image: Image.Image, sigma: float, rng: np.random.Generator) -> Image.Image:
    array = np.asarray(image, dtype=np.float32)
    array = array + sigma * rng.standard_normal(array.shape, dtype=np.float32)
    return Image.fromarray(np.clip(array, 0, 255).astype(np.uint8))


def scan(page: Image.Image, rng: np.random.Generator) -> tuple[Image.Image, dict[str, float]]:
    """Escáner de cama plana: casi recto, algo de ruido, contraste y a veces en grises."""
    params = {
        "rotation": float(rng.uniform(-1.2, 1.2)),
        "grayscale": float(rng.random() < 0.4),
        "brightness": float(rng.uniform(0.92, 1.06)),
        "contrast": float(rng.uniform(0.9, 1.15)),
        "blur": float(rng.uniform(0, 0.6)),
        "noise": float(rng.uniform(1.5, 5)),
        "scale": float(rng.uniform(0.75, 0.95)),
        "jpeg_quality": float(rng.integers(70, 93)),
    }
    image = page
    if params["grayscale"]:
        image = image.convert("L").convert("RGB")
    image = image.rotate(
        params["rotation"], resample=Image.Resampling.BICUBIC, expand=True, fillcolor="white"
    )
    image = ImageEnhance.Brightness(image).enhance(params["brightness"])
    image = ImageEnhance.Contrast(image).enhance(params["contrast"])
    if params["blur"] > 0.05:
        image = image.filter(ImageFilter.GaussianBlur(params["blur"]))
    size = (int(image.width * params["scale"]), int(image.height * params["scale"]))
    image = image.resize(size, Image.Resampling.LANCZOS)
    return _noise(image, params["noise"], rng), params


def _perspective_coeffs(
    destination: list[tuple[float, float]], source: list[tuple[float, float]]
) -> list[float]:
    """Coeficientes de ``Image.transform(PERSPECTIVE)``: llevan ``destination`` a ``source``."""
    rows = []
    for (x, y), (u, v) in zip(destination, source, strict=True):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y])
    a = np.array(rows, dtype=np.float64)
    b = np.array([c for point in source for c in point], dtype=np.float64)
    return np.linalg.solve(a, b).tolist()


def _background(size: tuple[int, int], rng: np.random.Generator) -> Image.Image:
    """Fondo tipo mesa o tela: color base con manchas suaves y grano."""
    base = rng.choice(
        np.array([[120, 90, 60], [170, 150, 120], [60, 60, 65], [200, 200, 195], [90, 110, 120]])
    ).astype(np.float32)
    w, h = size
    coarse = rng.normal(0, 18, (h // 64 + 2, w // 64 + 2, 1)).astype(np.float32)
    blotches = Image.fromarray(np.clip(coarse[..., 0] + 128, 0, 255).astype(np.uint8))
    blotches = blotches.resize((w, h), Image.Resampling.BICUBIC).filter(
        ImageFilter.GaussianBlur(30)
    )
    blotches = np.asarray(blotches, dtype=np.float32)[..., None] - 128
    array = base[None, None, :] + blotches + rng.normal(0, 4, (h, w, 1)).astype(np.float32)
    return Image.fromarray(np.clip(array, 0, 255).astype(np.uint8))


def _motion_blur(image: Image.Image, length: int, horizontal: bool) -> Image.Image:
    array = np.asarray(image, dtype=np.float32)
    axis = 1 if horizontal else 0
    kernel_sum = np.zeros_like(array)
    for shift in range(-(length // 2), length - length // 2):
        kernel_sum += np.roll(array, shift, axis=axis)
    return Image.fromarray(np.clip(kernel_sum / length, 0, 255).astype(np.uint8))


def foto(page: Image.Image, rng: np.random.Generator) -> tuple[Image.Image, dict[str, float]]:
    """Foto de celular: perspectiva, rotación, fondo, iluminación desigual, sombra,
    desenfoque, ruido y compresión JPEG."""
    params = {
        "rotation": float(rng.uniform(-10, 10)),
        "perspective": float(rng.uniform(0.0, 0.07)),
        "fill": float(rng.uniform(0.72, 0.92)),
        "light_min": float(rng.uniform(0.6, 0.95)),
        "shadow": float(rng.random() < 0.5),
        "shadow_strength": 0.0,
        "blur": float(rng.uniform(0, 1.6)),
        "motion_blur": float(rng.integers(0, 8) if rng.random() < 0.3 else 0),
        "noise": float(rng.uniform(2, 8)),
        "jpeg_quality": float(rng.integers(40, 86)),
    }
    out_w, out_h = (1200, 1600) if page.height >= page.width else (1600, 1200)

    # Esquinas del documento en la foto: centradas, rotadas y con perspectiva.
    scale = params["fill"] * min(out_w / page.width, out_h / page.height)
    half_w, half_h = page.width * scale / 2, page.height * scale / 2
    angle = np.radians(params["rotation"])
    cos, sin = np.cos(angle), np.sin(angle)
    cx = out_w / 2 + rng.uniform(-0.04, 0.04) * out_w
    cy = out_h / 2 + rng.uniform(-0.04, 0.04) * out_h
    corners = []
    for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        x, y = sx * half_w, sy * half_h
        x += rng.uniform(-1, 1) * params["perspective"] * half_w * 2
        y += rng.uniform(-1, 1) * params["perspective"] * half_h * 2
        corners.append((cx + x * cos - y * sin, cy + x * sin + y * cos))
    source = [(0, 0), (page.width, 0), (page.width, page.height), (0, page.height)]
    coeffs = _perspective_coeffs(corners, source)

    warped = page.transform(
        (out_w, out_h), Image.Transform.PERSPECTIVE, coeffs, Image.Resampling.BICUBIC
    )
    mask = Image.new("L", page.size, 255).transform(
        (out_w, out_h), Image.Transform.PERSPECTIVE, coeffs, Image.Resampling.BILINEAR
    )
    image = _background((out_w, out_h), rng)
    image.paste(warped, (0, 0), mask)

    # Iluminación: gradiente lineal en una dirección aleatoria.
    array = np.asarray(image, dtype=np.float32)
    yy, xx = np.mgrid[0:out_h, 0:out_w].astype(np.float32)
    direction = rng.uniform(0, 2 * np.pi)
    ramp = xx / out_w * np.cos(direction) + yy / out_h * np.sin(direction)
    ramp = (ramp - ramp.min()) / max(float(ramp.max() - ramp.min()), 1e-6)
    light = params["light_min"] + (1.05 - params["light_min"]) * ramp
    array *= light[..., None]

    # Sombra: un semiplano oscurecido con borde difuso (mano o celular).
    if params["shadow"]:
        params["shadow_strength"] = float(rng.uniform(0.15, 0.4))
        theta = rng.uniform(0, 2 * np.pi)
        offset = rng.uniform(0.55, 0.85)
        side = (xx / out_w - 0.5) * np.cos(theta) + (yy / out_h - 0.5) * np.sin(theta)
        shadow = Image.fromarray(((side > offset - 0.5) * 255).astype(np.uint8)).filter(
            ImageFilter.GaussianBlur(40)
        )
        array *= 1 - params["shadow_strength"] * (np.asarray(shadow, np.float32) / 255)[..., None]

    image = Image.fromarray(np.clip(array, 0, 255).astype(np.uint8))
    if params["blur"] > 0.1:
        image = image.filter(ImageFilter.GaussianBlur(params["blur"]))
    if params["motion_blur"] >= 2:
        image = _motion_blur(image, int(params["motion_blur"]), bool(rng.random() < 0.5))
    return _noise(image, params["noise"], rng), params
