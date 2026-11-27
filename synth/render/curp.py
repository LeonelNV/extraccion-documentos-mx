"""Constancia de CURP sintética: campos etiquetados, CURP destacada y QR con datos sintéticos."""

import io

from reportlab.lib.colors import HexColor, white

from docextract.entidades import por_clave_curp
from synth.render.common import (
    PAGE_H,
    PAGE_W,
    DocContext,
    Rendered,
    draw_fitted,
    draw_qr,
    fea,
    fecha_dmy,
    finish,
    new_canvas,
)

TEMPLATE = "curp_constancia"
SEXO = {"H": "HOMBRE", "M": "MUJER", "X": "NO BINARIO"}


def entidad_texto(clave: str) -> str:
    entidad = por_clave_curp(clave)
    return fea(entidad.nombre) if entidad else "NACIDO EN EL EXTRANJERO"


def render(ctx: DocContext) -> Rendered:
    p, rng = ctx.persona, ctx.rng
    fields = {
        "curp": p.curp,
        "nombre": fea(ctx.nombre),
        "apellido_paterno": fea(ctx.apellido_paterno),
        "apellido_materno": fea(ctx.apellido_materno),
        "sexo": SEXO[p.sexo],
        "fecha_nacimiento": fecha_dmy(p.fecha_nacimiento),
        "entidad_nacimiento": entidad_texto(p.clave_entidad_nacimiento),
        "nacionalidad": "MEXICANA",
    }

    buffer = io.BytesIO()
    c = new_canvas(buffer, title="Constancia de CURP")
    dx, dy = rng.uniform(-6, 6), rng.uniform(-8, 8)
    accent = HexColor(rng.choice(("#6B2C3E", "#3C4A63", "#2F5D50")))

    # Encabezado
    c.setFillColor(accent)
    c.rect(36, PAGE_H - 92 + dy, PAGE_W - 72, 46, stroke=0, fill=1)
    draw_fitted(
        c, 50 + dx, PAGE_H - 66 + dy, "CONSTANCIA DE LA CLAVE ÚNICA DE REGISTRO DE POBLACIÓN",
        font="Helvetica-Bold", size=14, max_width=PAGE_W - 110, color=white,
    )  # fmt: skip
    draw_fitted(
        c, 50 + dx, PAGE_H - 84 + dy, "Documento sintético de muestra - sin validez oficial",
        size=8, color=white,
    )  # fmt: skip

    # Clave
    y = PAGE_H - 140 + dy
    draw_fitted(c, 60 + dx, y, "Clave:", font="Helvetica-Bold", size=10)
    draw_fitted(c, 60 + dx, y - 28, fields["curp"], font="Courier-Bold", size=24)

    # Datos
    etiquetas = (
        ("Nombre(s):", "nombre"),
        ("Primer apellido:", "apellido_paterno"),
        ("Segundo apellido:", "apellido_materno"),
        ("Sexo:", "sexo"),
        ("Fecha de nacimiento:", "fecha_nacimiento"),
        ("Entidad de nacimiento:", "entidad_nacimiento"),
        ("Nacionalidad:", "nacionalidad"),
    )
    y -= 80
    size = rng.choice((10, 10.5, 11))
    for etiqueta, campo in etiquetas:
        draw_fitted(c, 60 + dx, y, etiqueta, font="Helvetica-Bold", size=size)
        draw_fitted(c, 210 + dx, y, fields[campo], size=size, max_width=230)
        y -= size * 2.2

    # QR con los mismos datos (fuente extra para la fase 4)
    payload = "|".join(
        (
            "CURP",
            p.curp,
            fields["apellido_paterno"],
            fields["apellido_materno"],
            fields["nombre"],
            p.sexo,
            fields["fecha_nacimiento"],
            p.clave_entidad_nacimiento,
            "MUESTRA",
        )
    )
    draw_qr(c, payload, PAGE_W - 200 + dx, PAGE_H - 330 + dy, 130)

    # Pie
    folio = "".join(rng.choice("0123456789") for _ in range(10))
    c.setStrokeColor(accent)
    c.line(60, 150 + dy, PAGE_W - 60, 150 + dy)
    draw_fitted(c, 60 + dx, 130 + dy, f"Folio: {folio}", size=8)
    draw_fitted(c, 60 + dx, 116 + dy, f"Fecha de emisión: {fecha_dmy(ctx.fecha_emision)}", size=8)
    draw_fitted(
        c, 60 + dx, 96 + dy,
        "Este documento fue generado automáticamente con datos ficticios para pruebas de software.",
        size=7, max_width=PAGE_W - 120,
    )  # fmt: skip
    return Rendered(pdf=finish(c, buffer), fields=fields)
