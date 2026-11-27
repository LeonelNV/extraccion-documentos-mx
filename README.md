# extraccion-documentos-mx

Extracción automática de datos de documentos oficiales mexicanos (CURP, INE, Constancia de Situación Fiscal y comprobante de domicilio) para prellenar un formulario de alta. La persona sube sus documentos; el sistema extrae, valida y prellena los campos, y la persona solo revisa y confirma.

> **Este repositorio usa solo datos sintéticos.** No contiene ni acepta documentos reales: un hook de pre-commit y la CI bloquean cualquier PDF o imagen fuera de `data/synthetic/` y `docs/img/`, aunque se le cambie la extensión.

## Estado

En desarrollo, en la **fase 4 de 9**. Ya están:

- el esqueleto del repo, las herramientas, la CI y los esquemas de salida (fase 1);
- los validadores y la normalización (fase 2): CURP y RFC con dígito verificador, nombres entre documentos, domicilio contra el catálogo de SEPOMEX y antigüedad del comprobante. Las reglas, sus fuentes y lo que no se pudo verificar están en [docs/validaciones.md](docs/validaciones.md);
- el generador de datos sintéticos (fase 3): personas ficticias con sus 4 documentos, en PDF digital, escaneo y foto de celular, con su ground truth. Hay un diseño de comprobante reservado para test. Detalles en [synth/README.md](synth/README.md);
- la ruta de texto (fase 4): router (texto vs. imagen), clasificador de texto y parsers de CURP y CSF sobre la capa de texto del PDF, sin ML. Los parsers trabajan sobre palabras con posición, así que en la fase 5 servirán también para el texto del OCR. Incluye `make eval` y `eval_private.py` para medir con documentos reales sin exponer sus datos (ver [eval/README.md](eval/README.md)).

![Documentos sintéticos de muestra](docs/img/muestras-sinteticas.jpg)

## Resultados

Generados por `make eval` sobre el split test del dataset sintético (75 personas, 300 documentos). El detalle está en [reports/resultados.md](reports/resultados.md).

| Componente | Documentos | Resultado |
|---|---:|---|
| Router (texto vs. imagen) | 300 | 100.0% |
| Clasificador de texto | 131 | 89.3% (CURP, CSF e INE: 100%; comprobante: 48.1%) |
| Clasificador, diseño de comprobante no visto en train | 14 | 0.0% |
| Parser de texto, CURP digital | 48 | 100% de documentos con todos los campos correctos; p50 161 ms |
| Parser de texto, CSF digital | 53 | 100% de documentos con todos los campos correctos; p50 261 ms |

Cómo leer estos números:

- **El 100% de los parsers no dice nada de los documentos reales.** Leen la capa de texto que el mismo generador escribió. Lo que sí se mide así es que las reglas no se rompen con nombres compuestos, partículas, Ñ, sin segundo apellido ni números interiores. El dato que importa saldrá de `make eval-private` con documentos reales.
- **El clasificador no generaliza al diseño de comprobante no visto.** No reconoce ninguno de los 14 recibos de teléfono, porque su vocabulario ("Resumen de cargos", "Fecha de expedición") no está en las palabras clave. No se ajustaron mirando test. En la FEA el tipo lo da el campo donde se sube el documento, así que el efecto es una advertencia `DOCUMENTO_NO_RECONOCIDO` que pide revisión, no un error de extracción.

## Cómo va a funcionar

1. **Router:** si el PDF tiene capa de texto (CURP y CSF casi siempre la tienen), se lee directo; si es un escaneo o una foto, pasa a un extractor de imagen.
2. **Extractores de imagen** comparados bajo la misma interfaz: OCR + reglas, OCR + LLM, un modelo multimodal en Amazon Bedrock y Donut con fine-tuning.
3. **Clasificación, normalización y validación:** dígitos verificadores de CURP y RFC, cruce entre documentos y catálogo de códigos postales de SEPOMEX.
4. **Fusión:** un JSON por persona, con la fuente, la confianza y las advertencias de cada campo.

## Contrato de salida

Cada campo del formulario (`curp`, `rfc`, `nombre`, `apellido_paterno`, `apellido_materno`, `fecha_nacimiento`, `nacionalidad`, `calle`, `numero_exterior`, `numero_interior`, `colonia`, `ciudad`, `estado`, `codigo_postal`) tiene esta forma:

```json
{
  "value": "XAXX010101000",
  "confidence": 0.62,
  "source_doc": "csf",
  "warnings": [
    {
      "code": "CONFIANZA_BAJA",
      "message": "La confianza (0.62) está por debajo del umbral de revisión (0.80).",
      "fields": [],
      "docs": []
    }
  ],
  "needs_review": true
}
```

- `needs_review` es verdadero **si y solo si** el campo tiene advertencias, y cada advertencia explica por qué hay que revisarlo.
- `value: null` significa que no se encontró el dato; `""` significa que el documento indica que no existe (por ejemplo, sin apellido materno).
- Los códigos de advertencia son estables (`src/docextract/schemas.py`) y los mensajes nunca incluyen datos extraídos.

## Desarrollo

Requisitos: [uv](https://docs.astral.sh/uv/), git y make (en Windows: `winget install ezwinports.make`).

```bash
make install   # dependencias fijadas en uv.lock y hooks de pre-commit
make sepomex   # catálogo de códigos postales (no se versiona; ver docs/validaciones.md)
make synth     # dataset sintético en data/synthetic/ (no se versiona)
make test      # pruebas
make lint      # ruff
make help      # todos los objetivos
```

Sin el catálogo de SEPOMEX las pruebas pasan igual: usan un catálogo ficticio, y las dos pruebas contra el catálogo real se omiten. `make synth` sí necesita el catálogo.

## Estructura

```
src/docextract/   paquete principal: esquemas, parsers, extractores, validadores y API
synth/            generador de datos sintéticos
training/         fine-tuning de Donut
eval/             evaluación de extractores
app/              demo en Gradio
scripts/          utilidades, incluido el bloqueo de documentos reales
data/synthetic/   datos generados (solo se versionan las muestras de samples/)
data/real/        ignorada por git; nunca se versiona
tests/            pruebas
```

## Trabajo futuro

- **Verificación de autenticidad vía QR del SAT.** La Constancia de Situación Fiscal trae un código QR del SAT. Leerlo y consultarlo permitiría confirmar que la constancia es auténtica, y no solo que sus datos son coherentes. No está implementado: por ahora el sistema no lee códigos QR. Los QR de los documentos sintéticos solo contienen datos de muestra.

## Licencia

[MIT](LICENSE)
