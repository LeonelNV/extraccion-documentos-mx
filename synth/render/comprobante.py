"""Comprobantes de domicilio sintéticos: cuatro diseños de empresas ficticias.

Cada diseño escribe el domicilio y la fecha con un estilo distinto, para medir si los
extractores generalizan. ``telefono`` se reserva para test (no aparece en train).

| Diseño   | Texto                     | Domicilio                 | Fecha de emisión     |
|----------|---------------------------|---------------------------|----------------------|
| luz      | mayúsculas sin acentos    | 3 líneas, "COL." y "C.P." | 05 OCT 2026          |
| agua     | como se escribe           | una línea con comas       | 5 de octubre de 2026 |
| banco    | mayúsculas con acentos    | bloque de 5 líneas        | 05/10/2026           |
| telefono | mayúsculas sin acentos    | campos etiquetados        | 2026-10-05           |
"""

import io
from collections.abc import Callable
from datetime import timedelta

from reportlab.lib.colors import HexColor, white
from reportlab.pdfgen.canvas import Canvas

from synth.render.common import (
    PAGE_H,
    PAGE_W,
    DocContext,
    Rendered,
    draw_fitted,
    fea,
    fecha_dmy,
    fecha_larga,
    fecha_mes_abr,
    finish,
    new_canvas,
)

GRIS = HexColor("#555555")


def _campos(ctx: DocContext, estilo: Callable[[str], str], fecha: str) -> dict[str, str]:
    d = ctx.domicilio
    titular = " ".join(x for x in (ctx.nombre, ctx.apellido_paterno, ctx.apellido_materno) if x)
    return {
        "titular": estilo(titular),
        "calle": estilo(d.calle),
        "numero_exterior": estilo(d.numero_exterior),
        "numero_interior": estilo(d.numero_interior),
        "colonia": estilo(d.colonia),
        "codigo_postal": d.codigo_postal,
        "ciudad": estilo(d.ciudad),
        "estado": estilo(d.estado),
        "fecha_emision": fecha,
    }


def _monto(ctx: DocContext, low: int, high: int) -> str:
    return f"$ {ctx.rng.randint(low, high):,}.{ctx.rng.randint(0, 99):02d}"


def _encabezado(c: Canvas, nombre: str, subtitulo: str, color: str, dy: float) -> None:
    c.setFillColor(HexColor(color))
    c.rect(0, PAGE_H - 80 + dy, PAGE_W, 80 - dy, stroke=0, fill=1)
    draw_fitted(c, 40, PAGE_H - 45 + dy, nombre, font="Helvetica-Bold", size=20, color=white)
    draw_fitted(c, 40, PAGE_H - 62 + dy, subtitulo, size=8, color=white)


def _pie(c: Canvas) -> None:
    draw_fitted(
        c, 40, 40, "Empresa y documento ficticios, generados para pruebas de software. MUESTRA.",
        size=7, color=GRIS,
    )  # fmt: skip


# ---------------------------------------------------------------------------
# Luz
# ---------------------------------------------------------------------------
def render_luz(ctx: DocContext) -> Rendered:
    rng = ctx.rng
    f = _campos(ctx, fea, fecha_mes_abr(ctx.fecha_emision))
    buffer = io.BytesIO()
    c = new_canvas(buffer, title="Aviso-recibo de luz")
    dy = rng.uniform(-6, 4)
    _encabezado(
        c, "ENERGÍA DEL PACÍFICO", "Empresa ficticia de suministro eléctrico", "#1B5E20", dy
    )

    y = PAGE_H - 120 + dy
    draw_fitted(c, 40, y, f["titular"], font="Helvetica-Bold", size=11, max_width=300)
    linea1 = f"{f['calle']} {f['numero_exterior']}"
    if f["numero_interior"]:
        linea1 += f" INT {f['numero_interior']}"
    for i, linea in enumerate(
        (linea1, f"COL. {f['colonia']}", f"C.P. {f['codigo_postal']} {f['ciudad']}, {f['estado']}")
    ):
        draw_fitted(c, 40, y - 16 - i * 13, linea, size=9.5, max_width=320)

    servicio = "".join(rng.choice("0123456789") for _ in range(12))
    inicio = ctx.fecha_emision - timedelta(days=rng.randint(58, 64))
    datos = (
        ("NO. DE SERVICIO", servicio),
        ("FECHA DE EMISIÓN", f["fecha_emision"]),
        ("PERIODO FACTURADO", f"{fecha_mes_abr(inicio)} - {fecha_mes_abr(ctx.fecha_emision)}"),
        ("FECHA LÍMITE DE PAGO", fecha_mes_abr(ctx.fecha_emision + timedelta(days=15))),
    )
    for i, (etiqueta, valor) in enumerate(datos):
        draw_fitted(c, 390, y - i * 28, etiqueta, size=7, color=GRIS)
        draw_fitted(c, 390, y - 12 - i * 28, valor, font="Helvetica-Bold", size=10)

    c.setFillColor(HexColor("#E8F5E9"))
    c.rect(40, y - 170, PAGE_W - 80, 50, stroke=0, fill=1)
    draw_fitted(c, 55, y - 150, "TOTAL A PAGAR", font="Helvetica-Bold", size=12)
    draw_fitted(c, 400, y - 150, _monto(ctx, 120, 2400), font="Helvetica-Bold", size=16)

    # Historial de consumo (barras)
    base = y - 330
    draw_fitted(c, 40, base + 135, "CONSUMO HISTÓRICO (kWh)", font="Helvetica-Bold", size=9)
    for i in range(6):
        h = rng.uniform(25, 120)
        c.setFillColor(HexColor("#66BB6A"))  # draw_fitted cambia el color de relleno
        c.rect(60 + i * 75, base, 40, h, stroke=0, fill=1)
        draw_fitted(c, 62 + i * 75, base - 12, f"{int(h * 3)}", size=7)
    _pie(c)
    return Rendered(pdf=finish(c, buffer), fields=f)


# ---------------------------------------------------------------------------
# Agua
# ---------------------------------------------------------------------------
def render_agua(ctx: DocContext) -> Rendered:
    rng = ctx.rng
    f = _campos(ctx, lambda s: s, fecha_larga(ctx.fecha_emision))
    buffer = io.BytesIO()
    c = new_canvas(buffer, title="Recibo de agua")
    dy = rng.uniform(-6, 4)
    _encabezado(c, "Agua y Saneamiento del Valle", "Organismo operador ficticio", "#0D47A1", dy)

    y = PAGE_H - 115 + dy
    draw_fitted(c, 40, y, f"Fecha de emisión: {f['fecha_emision']}", size=9)
    draw_fitted(c, 360, y, f"Cuenta: {rng.randint(100000, 999999)}-{rng.randint(1, 9)}", size=9)
    y -= 30
    draw_fitted(c, 40, y, "Usuario:", font="Helvetica-Bold", size=9)
    draw_fitted(c, 100, y, f["titular"], size=9, max_width=420)
    partes = [f"{f['calle']} No. {f['numero_exterior']}"]
    if f["numero_interior"]:
        partes.append(f"Int. {f['numero_interior']}")
    partes += [f"Col. {f['colonia']}", f"C.P. {f['codigo_postal']}", f["ciudad"], f["estado"]]
    draw_fitted(c, 40, y - 16, "Domicilio:", font="Helvetica-Bold", size=9)
    draw_fitted(c, 100, y - 16, ", ".join(partes), size=9, max_width=PAGE_W - 140)

    y -= 60
    c.setStrokeColor(HexColor("#90CAF9"))
    c.rect(40, y - 80, PAGE_W - 80, 90, stroke=1, fill=0)
    anterior = rng.randint(100, 9000)
    consumo = rng.randint(8, 45)
    for i, (etiqueta, valor) in enumerate(
        (
            ("Lectura anterior", f"{anterior} m³"),
            ("Lectura actual", f"{anterior + consumo} m³"),
            ("Consumo del periodo", f"{consumo} m³"),
            ("Importe", _monto(ctx, 90, 900)),
        )
    ):
        draw_fitted(c, 55 + (i % 2) * 260, y - 15 - (i // 2) * 35, etiqueta, size=8, color=GRIS)
        draw_fitted(
            c, 55 + (i % 2) * 260, y - 28 - (i // 2) * 35, valor, font="Helvetica-Bold", size=11
        )
    draw_fitted(
        c, 40, y - 120, "Pague antes de la fecha límite para evitar recargos.", size=8, color=GRIS
    )
    _pie(c)
    return Rendered(pdf=finish(c, buffer), fields=f)


# ---------------------------------------------------------------------------
# Estado de cuenta bancario
# ---------------------------------------------------------------------------
def render_banco(ctx: DocContext) -> Rendered:
    rng = ctx.rng
    f = _campos(ctx, lambda s: s.upper(), fecha_dmy(ctx.fecha_emision))
    buffer = io.BytesIO()
    c = new_canvas(buffer, title="Estado de cuenta")
    dy = rng.uniform(-6, 4)
    draw_fitted(
        c,
        40,
        PAGE_H - 50 + dy,
        "Banco Ejemplo del Norte",
        font="Times-Bold",
        size=20,
        color=HexColor("#4A148C"),
    )
    draw_fitted(
        c,
        40,
        PAGE_H - 64 + dy,
        "Institución ficticia - Estado de cuenta de muestra",
        size=8,
        color=GRIS,
    )

    y = PAGE_H - 110 + dy
    lineas = [f["titular"], f"{f['calle']} {f['numero_exterior']}"]
    if f["numero_interior"]:
        lineas[-1] += f" INT. {f['numero_interior']}"
    lineas += [f["colonia"], f"{f['ciudad']}, {f['estado']}", f"C.P. {f['codigo_postal']}"]
    for i, linea in enumerate(lineas):
        draw_fitted(
            c,
            40,
            y - i * 13,
            linea,
            font="Times-Roman" if i else "Times-Bold",
            size=10,
            max_width=300,
        )

    inicio = ctx.fecha_emision - timedelta(days=30)
    resumen = (
        ("Periodo", f"{fecha_dmy(inicio)} al {fecha_dmy(ctx.fecha_emision)}"),
        ("Fecha de corte", f["fecha_emision"]),
        ("Número de cuenta", f"****{rng.randint(1000, 9999)}"),
        ("Saldo al corte", _monto(ctx, 500, 90000)),
    )
    for i, (etiqueta, valor) in enumerate(resumen):
        draw_fitted(c, 360, y - i * 16, f"{etiqueta}:", font="Times-Bold", size=9)
        draw_fitted(c, 450, y - i * 16, valor, font="Times-Roman", size=9, max_width=130)

    # Movimientos
    y -= 110
    c.setFillColor(HexColor("#EDE7F6"))
    c.rect(40, y - 4, PAGE_W - 80, 16, stroke=0, fill=1)
    for x, titulo in ((45, "Fecha"), (120, "Concepto"), (420, "Cargo"), (500, "Abono")):
        draw_fitted(c, x, y, titulo, font="Times-Bold", size=9)
    conceptos = (
        "PAGO DE NÓMINA",
        "COMPRA EN COMERCIO",
        "TRANSFERENCIA SPEI",
        "RETIRO CAJERO",
        "PAGO DE SERVICIO",
        "COMISIÓN",
    )
    dia = inicio
    for i in range(rng.randint(6, 12)):
        dia += timedelta(days=rng.randint(1, 3))
        if dia > ctx.fecha_emision:
            break
        yy = y - 18 - i * 15
        concepto = rng.choice(conceptos)
        draw_fitted(c, 45, yy, fecha_dmy(dia), font="Times-Roman", size=8.5)
        draw_fitted(c, 120, yy, concepto, font="Times-Roman", size=8.5)
        columna = 500 if concepto == "PAGO DE NÓMINA" else 420
        draw_fitted(c, columna, yy, _monto(ctx, 50, 9000), font="Times-Roman", size=8.5)
    _pie(c)
    return Rendered(pdf=finish(c, buffer), fields=f)


# ---------------------------------------------------------------------------
# Teléfono e internet (reservado para test)
# ---------------------------------------------------------------------------
def render_telefono(ctx: DocContext) -> Rendered:
    rng = ctx.rng
    f = _campos(ctx, fea, ctx.fecha_emision.isoformat())
    buffer = io.BytesIO()
    c = new_canvas(buffer, title="Factura de telefonía")
    dy = rng.uniform(-6, 4)
    acento = HexColor("#E65100")

    c.setFillColor(acento)
    c.rect(0, 0, 28, PAGE_H, stroke=0, fill=1)
    draw_fitted(
        c,
        50,
        PAGE_H - 60 + dy,
        "Telecomunicaciones Altamar",
        font="Helvetica-Bold",
        size=18,
        color=acento,
    )
    draw_fitted(
        c, 50, PAGE_H - 74 + dy, "Telefonía e internet - empresa ficticia", size=8, color=GRIS
    )
    telefono = f"311 555 {rng.randint(1000, 9999)}"
    draw_fitted(c, 50, PAGE_H - 110 + dy, "Número telefónico", size=8, color=GRIS)
    draw_fitted(c, 50, PAGE_H - 126 + dy, telefono, font="Helvetica-Bold", size=16)

    # Caja de datos del cliente a la derecha
    bx, by, bw, bh = 320, PAGE_H - 290 + dy, 250, 200
    c.setStrokeColor(acento)
    c.roundRect(bx, by, bw, bh, 8, stroke=1, fill=0)
    draw_fitted(
        c, bx + 10, by + bh - 18, "DATOS DEL CLIENTE", font="Helvetica-Bold", size=9, color=acento
    )
    numero = f["numero_exterior"] + (f" INT {f['numero_interior']}" if f["numero_interior"] else "")
    pares = (
        ("NOMBRE", f["titular"]),
        ("DIRECCIÓN", f"{f['calle']} {numero}"),
        ("COLONIA", f["colonia"]),
        ("C.P.", f["codigo_postal"]),
        ("CIUDAD", f["ciudad"]),
        ("ESTADO", f["estado"]),
        ("FECHA DE EXPEDICIÓN", f["fecha_emision"]),
    )
    for i, (etiqueta, valor) in enumerate(pares):
        yy = by + bh - 40 - i * 23
        draw_fitted(c, bx + 10, yy + 8, etiqueta, size=6, color=GRIS)
        draw_fitted(c, bx + 10, yy - 2, valor, font="Helvetica-Bold", size=8.5, max_width=bw - 20)

    # Cargos del mes
    y = PAGE_H - 170 + dy
    draw_fitted(c, 50, y, "RESUMEN DE CARGOS", font="Helvetica-Bold", size=10)
    for i, concepto in enumerate(("Renta mensual", "Internet 100 Mbps", "Llamadas", "IVA")):
        draw_fitted(c, 50, y - 20 - i * 16, concepto, size=9)
        draw_fitted(c, 220, y - 20 - i * 16, _monto(ctx, 20, 600), size=9)
    draw_fitted(c, 50, y - 100, "TOTAL", font="Helvetica-Bold", size=12)
    draw_fitted(c, 220, y - 100, _monto(ctx, 300, 1500), font="Helvetica-Bold", size=12)
    _pie(c)
    return Rendered(pdf=finish(c, buffer), fields=f)


DISENOS: dict[str, Callable[[DocContext], Rendered]] = {
    "luz": render_luz,
    "agua": render_agua,
    "banco": render_banco,
    "telefono": render_telefono,
}


def template_name(diseno: str) -> str:
    return f"comprobante_{diseno}"


def render(ctx: DocContext, diseno: str) -> Rendered:
    return DISENOS[diseno](ctx)
