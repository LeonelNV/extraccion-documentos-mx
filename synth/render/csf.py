"""Constancia de situación fiscal sintética: datos de identificación, domicilio por campos y
régimen. El QR trae datos sintéticos, no una URL de la autoridad fiscal."""

import io

from reportlab.lib.colors import HexColor, white

from synth.render.common import (
    PAGE_H,
    PAGE_W,
    DocContext,
    Rendered,
    draw_fitted,
    draw_qr,
    fea,
    fecha_dmy,
    fecha_larga,
    finish,
    new_canvas,
)

TEMPLATE = "csf_constancia"


def render(ctx: DocContext) -> Rendered:
    p, d, rng = ctx.persona, ctx.domicilio, ctx.rng
    # La mitad de las constancias conserva los acentos en mayúsculas.
    estilo = (lambda s: s.upper()) if rng.random() < 0.5 else fea
    fields = {
        "rfc": p.rfc,
        "curp": p.curp,
        "nombre": estilo(ctx.nombre),
        "apellido_paterno": estilo(ctx.apellido_paterno),
        "apellido_materno": estilo(ctx.apellido_materno),
        "codigo_postal": d.codigo_postal,
        "tipo_vialidad": estilo(d.tipo_vialidad),
        "nombre_vialidad": estilo(d.nombre_vialidad),
        "numero_exterior": estilo(d.numero_exterior),
        "numero_interior": estilo(d.numero_interior),
        "colonia": estilo(d.colonia),
        "ciudad": estilo(d.ciudad),
        "municipio": estilo(d.municipio),
        "estado": estilo(d.estado),
    }
    fields["calle"] = f"{fields['tipo_vialidad']} {fields['nombre_vialidad']}"

    inicio = p.fecha_nacimiento.replace(year=p.fecha_nacimiento.year + 18)
    inicio = min(inicio, ctx.reference_date)
    id_cif = "".join(rng.choice("0123456789") for _ in range(11))

    buffer = io.BytesIO()
    c = new_canvas(buffer, title="Constancia de situación fiscal")
    dy = rng.uniform(-6, 6)
    barra = HexColor(rng.choice(("#5B6770", "#6D4C41", "#455A64")))
    gris = HexColor("#555555")

    # Cédula (izquierda) y título (derecha)
    c.setStrokeColor(HexColor("#999999"))
    c.rect(36, PAGE_H - 230 + dy, 250, 190, stroke=1, fill=0)
    draw_fitted(
        c, 46, PAGE_H - 58 + dy, "CÉDULA DE IDENTIFICACIÓN FISCAL", font="Helvetica-Bold", size=9
    )
    draw_qr(c, f"MUESTRA|RFC={p.rfc}|idCIF={id_cif}", 46, PAGE_H - 175 + dy, 105)
    draw_fitted(c, 160, PAGE_H - 90 + dy, fields["rfc"], font="Helvetica-Bold", size=11)
    draw_fitted(c, 160, PAGE_H - 102 + dy, "Registro Federal de Contribuyentes", size=6, color=gris)
    nombre_completo = " ".join(
        v for v in (fields["nombre"], fields["apellido_paterno"], fields["apellido_materno"]) if v
    )
    draw_fitted(
        c, 160, PAGE_H - 125 + dy, nombre_completo, font="Helvetica-Bold", size=8, max_width=120
    )
    draw_fitted(
        c, 160, PAGE_H - 137 + dy, "Nombre, denominación o razón social", size=6, color=gris
    )
    draw_fitted(c, 160, PAGE_H - 160 + dy, f"idCIF: {id_cif}", font="Helvetica-Bold", size=8)
    draw_fitted(
        c, 46, PAGE_H - 220 + dy, "MUESTRA - DOCUMENTO SINTÉTICO SIN VALIDEZ", size=6.5, color=gris
    )

    draw_fitted(
        c, 310, PAGE_H - 70 + dy, "CONSTANCIA DE SITUACIÓN FISCAL", font="Helvetica-Bold", size=13
    )
    lugar = f"{fields['municipio']}, {fields['estado']} A {fecha_larga(ctx.fecha_emision).upper()}"
    draw_fitted(c, 310, PAGE_H - 100 + dy, "Lugar y Fecha de Emisión", size=7, color=gris)
    draw_fitted(
        c, 310, PAGE_H - 112 + dy, lugar, font="Helvetica-Bold", size=8, max_width=PAGE_W - 346
    )

    def seccion(titulo: str, y: float) -> None:
        c.setFillColor(barra)
        c.rect(36, y - 4, PAGE_W - 72, 16, stroke=0, fill=1)
        draw_fitted(c, 42, y, titulo, font="Helvetica-Bold", size=9, color=white)

    def filas(pares: list[tuple[str, str]], y: float, *, columnas: int) -> float:
        ancho = (PAGE_W - 72) / columnas
        for i, (etiqueta, valor) in enumerate(pares):
            col, fila = i % columnas, i // columnas
            x = 42 + col * ancho
            yy = y - fila * 22
            draw_fitted(c, x, yy, etiqueta, font="Helvetica-Bold", size=7.5, max_width=ancho * 0.48)
            draw_fitted(c, x + ancho * 0.5, yy, valor, size=8, max_width=ancho * 0.48)
        return y - ((len(pares) + columnas - 1) // columnas) * 22

    y = PAGE_H - 265 + dy
    seccion("Datos de Identificación del Contribuyente:", y)
    y = filas(
        [
            ("RFC:", fields["rfc"]),
            ("CURP:", fields["curp"]),
            ("Nombre (s):", fields["nombre"]),
            ("Primer Apellido:", fields["apellido_paterno"]),
            ("Segundo Apellido:", fields["apellido_materno"]),
            ("Fecha inicio de operaciones:", fecha_larga(inicio).upper()),
            ("Estatus en el padrón:", "ACTIVO"),
            ("Nombre Comercial:", ""),
        ],
        y - 24,
        columnas=1,
    )

    y -= 12
    seccion("Datos del domicilio registrado", y)
    y = filas(
        [
            ("Código Postal:", fields["codigo_postal"]),
            ("Tipo de Vialidad:", fields["tipo_vialidad"]),
            ("Nombre de Vialidad:", fields["nombre_vialidad"]),
            ("Número Exterior:", fields["numero_exterior"]),
            ("Número Interior:", fields["numero_interior"]),
            ("Nombre de la Colonia:", fields["colonia"]),
            ("Nombre de la Localidad:", fields["ciudad"]),
            ("Nombre del Municipio o Demarcación Territorial:", fields["municipio"]),
            ("Nombre de la Entidad Federativa:", fields["estado"]),
            ("Entre Calle:", ""),
        ],
        y - 24,
        columnas=2,
    )

    y -= 12
    seccion("Regímenes:", y)
    draw_fitted(c, 42, y - 24, "Régimen", font="Helvetica-Bold", size=8)
    draw_fitted(c, 420, y - 24, "Fecha Inicio", font="Helvetica-Bold", size=8)
    draw_fitted(
        c, 42, y - 40, "Régimen de Sueldos y Salarios e Ingresos Asimilados a Salarios", size=8
    )
    draw_fitted(c, 420, y - 40, fecha_dmy(inicio), size=8)

    aviso = "Documento generado con datos ficticios para pruebas de software. No es oficial."
    draw_fitted(c, 42, 60, aviso, size=7, color=gris)
    return Rendered(pdf=finish(c, buffer), fields=fields)
