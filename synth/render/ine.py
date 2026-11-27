"""Credencial para votar sintética: frente y reverso en una página, como una fotocopia.

Sin logotipos, hologramas ni elementos de seguridad; el rostro es una silueta. El domicilio
usa las abreviaturas típicas de la credencial ("C", "AV", "COL", "NAY.").
"""

import io

from reportlab.lib.colors import HexColor

from docextract.entidades import ENTIDADES, find_entidad
from synth.persona import Domicilio
from synth.render.common import (
    PAGE_H,
    PAGE_W,
    DocContext,
    Rendered,
    draw_fitted,
    draw_qr,
    draw_silhouette,
    fea,
    fecha_dmy,
    finish,
    new_canvas,
)

TEMPLATE = "ine_credencial"

ABREVIATURAS_VIALIDAD = {
    "CALLE": "C",
    "AVENIDA": "AV",
    "PRIVADA": "PRIV",
    "CERRADA": "CDA",
    "BOULEVARD": "BLVD",
    "CALZADA": "CALZ",
    "CIRCUITO": "CTO",
    "PROLONGACION": "PROL",
    "ANDADOR": "AND",
}
PREFIJOS_ASENTAMIENTO = {
    "Colonia": "COL",
    "Fraccionamiento": "FRACC",
    "Barrio": "BO",
    "Unidad habitacional": "U HAB",
}


def estado_abreviado(estado: str) -> str:
    entidad = find_entidad(estado)
    if entidad is None:
        return fea(estado)
    if entidad.clave_curp == "DF":
        return "CDMX"
    return f"{entidad.variantes[0]}." if entidad.variantes else fea(entidad.nombre)


def domicilio_ine(d: Domicilio) -> dict[str, str]:
    """Campos del domicilio como los imprime la credencial."""
    tipo = fea(d.tipo_vialidad)
    calle = f"{ABREVIATURAS_VIALIDAD.get(tipo, tipo)} {fea(d.nombre_vialidad)}"
    return {
        "calle": calle,
        "numero_exterior": fea(d.numero_exterior),
        "numero_interior": fea(d.numero_interior),
        "colonia": fea(d.colonia),
        "codigo_postal": d.codigo_postal,
        "ciudad": fea(d.municipio),
        "estado": estado_abreviado(d.estado),
    }


def _clave_elector(ctx: DocContext, campos: dict[str, str]) -> str:
    letras = "".join(
        (campos[k].replace(" ", "") + "XX")[:2]
        for k in ("apellido_paterno", "apellido_materno", "nombre")
    )
    letras = "".join(c if "A" <= c <= "Z" else "X" for c in letras)
    p = ctx.persona
    clave_inegi = next(
        (e.clave_inegi for e in ENTIDADES if e.clave_curp == p.clave_entidad_nacimiento), "87"
    )
    digitos = "".join(ctx.rng.choice("0123456789") for _ in range(3))
    return f"{letras}{p.fecha_nacimiento:%y%m%d}{clave_inegi}{p.sexo}{digitos}"


def render(ctx: DocContext) -> Rendered:
    p, rng = ctx.persona, ctx.rng
    fields = {
        "nombre": fea(ctx.nombre),
        "apellido_paterno": fea(ctx.apellido_paterno),
        "apellido_materno": fea(ctx.apellido_materno),
        "fecha_nacimiento": fecha_dmy(p.fecha_nacimiento),
        "sexo": p.sexo,
        "curp": p.curp,
        **domicilio_ine(ctx.domicilio),
    }
    fields["clave_elector"] = _clave_elector(ctx, fields)
    registro = max(p.fecha_nacimiento.year + 18, 1991) + rng.randint(0, 8)
    registro = min(registro, ctx.reference_date.year - 1)
    vigencia_inicio = rng.randint(ctx.reference_date.year - 6, ctx.reference_date.year - 1)
    seccion = f"{rng.randint(1, 3999):04d}"

    buffer = io.BytesIO()
    c = new_canvas(buffer, title="Credencial para votar")
    cw, ch = 376.0, 237.0  # 85.6 x 54 mm a escala 1.55
    x0 = (PAGE_W - cw) / 2 + rng.uniform(-25, 25)
    front_y = PAGE_H - 70 - ch + rng.uniform(-15, 10)
    back_y = front_y - ch - 50 + rng.uniform(-15, 10)
    fondo = HexColor(rng.choice(("#E9F1EE", "#EEF0F6", "#F4EFE6")))
    acento = HexColor(rng.choice(("#7A1E48", "#1E4E7A", "#2E6B4F")))
    gris = HexColor("#555555")

    for y in (front_y, back_y):
        c.setFillColor(fondo)
        c.setStrokeColor(HexColor("#999999"))
        c.roundRect(x0, y, cw, ch, 10, stroke=1, fill=1)

    # ----- Frente
    fy = front_y
    draw_fitted(
        c,
        x0 + 12,
        fy + ch - 22,
        "CREDENCIAL PARA VOTAR",
        font="Helvetica-Bold",
        size=12,
        color=acento,
    )
    draw_fitted(c, x0 + 12, fy + ch - 33, "MUESTRA - DOCUMENTO SINTÉTICO", size=6, color=gris)
    draw_fitted(c, x0 + cw - 70, fy + ch - 48, "SEXO", size=5.5, color=gris)
    draw_fitted(c, x0 + cw - 45, fy + ch - 48, fields["sexo"], font="Helvetica-Bold", size=8)
    draw_silhouette(c, x0 + 12, fy + 58, 88, 118)

    tx = x0 + 110
    ty = fy + ch - 48
    draw_fitted(c, tx, ty, "NOMBRE", size=5.5, color=gris)
    for key in ("apellido_paterno", "apellido_materno", "nombre"):
        ty -= 10
        draw_fitted(c, tx, ty, fields[key], font="Helvetica-Bold", size=8, max_width=150)
    ty -= 14
    draw_fitted(c, tx, ty, "DOMICILIO", size=5.5, color=gris)
    linea1 = f"{fields['calle']} {fields['numero_exterior']}"
    if fields["numero_interior"]:
        linea1 += f" INT {fields['numero_interior']}"
    prefijo = PREFIJOS_ASENTAMIENTO.get(ctx.domicilio.tipo_asentamiento, "")
    linea2 = f"{prefijo} {fields['colonia']} {fields['codigo_postal']}".strip()
    linea3 = f"{fields['ciudad']}, {fields['estado']}"
    for linea in (linea1, linea2, linea3):
        ty -= 10
        draw_fitted(c, tx, ty, linea, font="Helvetica-Bold", size=7.5, max_width=cw - 125)

    ty -= 14
    datos = (
        ("CLAVE DE ELECTOR", fields["clave_elector"]),
        ("CURP", fields["curp"]),
        ("FECHA DE NACIMIENTO", fields["fecha_nacimiento"]),
    )
    for etiqueta, valor in datos:
        draw_fitted(c, tx, ty, etiqueta, size=5.5, color=gris)
        draw_fitted(c, tx + 78, ty, valor, font="Helvetica-Bold", size=7.5)
        ty -= 10
    vigencia = f"{vigencia_inicio} - {vigencia_inicio + 10}"
    extra = (
        f"AÑO DE REGISTRO {registro} {rng.randint(0, 9):02d}   SECCIÓN {seccion}   "
        f"VIGENCIA {vigencia}"
    )
    draw_fitted(c, x0 + 12, fy + 14, extra, size=6, max_width=cw - 24)

    # ----- Reverso: QR y líneas tipo zona de lectura (datos sintéticos)
    by = back_y
    draw_qr(c, f"MUESTRA|{fields['clave_elector']}|{p.curp}|{seccion}", x0 + 14, by + 70, 110)
    draw_fitted(
        c,
        x0 + 140,
        by + ch - 30,
        "MUESTRA - SIN VALIDEZ",
        font="Helvetica-Bold",
        size=9,
        color=acento,
    )
    nombre_zona = (
        "<".join(fields[k].replace(" ", "<") for k in ("apellido_paterno", "apellido_materno"))
        + "<<"
        + fields["nombre"].replace(" ", "<")
    )
    lineas = (
        f"IDMUE{rng.randint(10**8, 10**9 - 1)}<<{seccion}".ljust(30, "<")[:30],
        (
            f"{p.fecha_nacimiento:%y%m%d}{rng.randint(0, 9)}{p.sexo}"
            f"{vigencia_inicio + 10 - 2000:02d}1231{rng.randint(0, 9)}MUE"
        ).ljust(30, "<")[:30],
        nombre_zona.ljust(30, "<")[:30],
    )
    for i, linea in enumerate(lineas):
        draw_fitted(c, x0 + 14, by + 50 - i * 14, linea, font="Courier-Bold", size=10.5)

    return Rendered(pdf=finish(c, buffer), fields=fields)
