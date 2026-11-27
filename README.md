# extraccion-documentos-mx

Extracción automática de datos de documentos oficiales mexicanos (CURP, INE, Constancia de Situación Fiscal y comprobante de domicilio) para prellenar un formulario de alta. La persona sube sus documentos; el sistema extrae, valida y prellena los campos, y la persona solo revisa y confirma.

> **Este repositorio usa solo datos sintéticos.** No contiene ni acepta documentos reales: un hook de pre-commit y la CI bloquean cualquier PDF o imagen fuera de `data/synthetic/` y `docs/img/`, aunque se le cambie la extensión.

## Estado

En desarrollo, en la **fase 2 de 9**. Ya están:

- el esqueleto del repo, las herramientas, la CI y los esquemas de salida (fase 1);
- los validadores y la normalización (fase 2): CURP y RFC con dígito verificador, nombres entre documentos, domicilio contra el catálogo de SEPOMEX y antigüedad del comprobante. Las reglas, sus fuentes y lo que no se pudo verificar están en [docs/validaciones.md](docs/validaciones.md).

Todavía no hay extractores ni resultados; las métricas se publicarán aquí cuando las genere `make eval`.

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
make test      # pruebas
make lint      # ruff
make help      # todos los objetivos
```

Sin el catálogo de SEPOMEX las pruebas pasan igual: usan un catálogo ficticio, y las dos pruebas contra el catálogo real se omiten.

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

## Licencia

[MIT](LICENSE)
