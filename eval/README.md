# eval/

## `make eval`: dataset sintético

```bash
make eval                                                      # split test: lo que se reporta
uv run python eval/evaluate.py --split val --errores 10 --no-save   # desarrollo
uv run python eval/evaluate.py --sin-ocr                       # solo la ruta de texto
```

Los documentos digitales van por la capa de texto (`texto_reglas`); los escaneos y fotos, por
el extractor A (`ocr_reglas`: Tesseract + las mismas reglas). Necesita Tesseract y `make
tessdata`. El OCR corre en paralelo (`--workers`, 4 por omisión) y se guarda en
`data/cache/ocr/` (ignorado por git) por hash del PDF y configuración: la segunda corrida no
repite el OCR. La latencia reportada es la medida al hacer el OCR.

Por cada documento del split mide:

- **Router:** si fue por la ruta correcta. Digital va a texto; escaneo y foto van a imagen.
- **Clasificador de palabras clave:** si reconoce el tipo de documento, por separado con el texto del PDF y con el del OCR. Se reporta aparte el diseño de comprobante que no aparece en train.
- **Extracción, por tipo de documento y modalidad (digital, escaneo, foto):**
  - exactitud por campo tras normalizar;
  - CER;
  - porcentaje de documentos con todos los campos correctos;
  - latencia p50/p95 (lectura del PDF, OCR si aplica, clasificación y parser);
  - costo, que es $0 para las reglas.

## `make train-clasificador`: el clasificador entrenado

Entrena TF-IDF + regresión logística con el texto de train (capa de texto u OCR), elige la
regularización y el umbral de "no reconocido" en val y lo compara con el de palabras clave en
test, sobre los mismos documentos. Escribe `models/clasificador/` (no se versiona) y
`reports/clasificador.md` y `.csv`. Detalle del protocolo en `training/train_clasificador.py`.

La comparación normaliza según el tipo de campo:

| Campo | Cómo se compara |
|---|---|
| Nombres | Mayúsculas, sin acentos, con Ñ |
| Domicilio | Abreviaturas expandidas ("AV." = "AVENIDA") |
| Fechas | Como fecha (`17/05/1990` = `1990-05-17`) |
| CP | A 5 dígitos |
| Estado | Por entidad (`NAY.` = `Nayarit`) |
| Sexo | Por código (`HOMBRE` = `H`) |

Un valor no encontrado nunca cuenta como acierto. La lógica está en `src/docextract/evaluation.py`.

Escribe:

- `reports/resultados.md` y `.csv`: se versionan, y de ahí salen los números del README;
- `reports/runs/<fecha>_<split>.json`: el detalle de cada corrida, con commit y semilla del dataset. No se versiona.

**Higiene:** las reglas se desarrollan mirando train y val; test solo se usa para reportar.

## `make eval-private`: documentos reales

Mide la extracción con tus propios documentos **sin que sus datos salgan de tu equipo**.

```
data/real/curp/*.pdf        constancias de CURP descargadas de RENAPO
data/real/csf/*.pdf         constancias de situación fiscal descargadas del SAT
data/real/ine/*.pdf         opcional: credenciales escaneadas o fotografiadas
data/real/comprobante/*.pdf opcional: comprobantes de domicilio
data/real/etiquetas.json    opcional: {"curp/archivo.pdf": {"curp": "...", "nombre": "..."}}
```

Los PDFs sin capa de texto se leen con el extractor A (OCR) si Tesseract está instalado,
**sin caché**: el texto reconocido no se escribe a disco. Si ya corriste `make
train-clasificador`, también cuenta cuántos documentos clasifica bien el modelo entrenado.

`data/real/` está en `.gitignore` y el hook de pre-commit rechaza cualquier archivo ahí.

**Sin etiquetas** mide lo que se puede comprobar sin conocer la respuesta:

- si va por la ruta de texto (o se leyó por OCR) y si se clasifica bien, con palabras clave y con el modelo entrenado;
- qué campos se encontraron;
- si la CURP y el RFC pasan su dígito verificador;
- si el nombre y la fecha son coherentes con la CURP;
- si el RFC es coherente con la CURP;
- si el CP, el estado, el municipio y la colonia son coherentes con SEPOMEX.

Si hay exactamente una CURP y una CSF, también compara la CURP y el nombre entre ambas.

**Con `etiquetas.json`** agrega la exactitud por campo.

**Privacidad:**

- Solo imprime conteos ("1/1 CURP con dígito verificador válido").
- Nunca imprime ni escribe valores extraídos, nombres de archivo (pueden llevar tu nombre) ni mensajes de error (algunos incluyen el dato de entrada): de un error solo cuenta el tipo.
- No escribe nada a disco.

Las pruebas lo verifican con archivos cuyo nombre contiene datos.

## `make esqueleto`: la estructura de un documento real, sin sus datos

Cuando un campo no se encuentra en un documento real, hace falta saber cómo está organizado
sin ver sus datos. `make esqueleto` lee los PDFs de `data/real/` igual que el parser y muestra:

- páginas, fuentes y tamaños;
- palabras que pdfplumber juntó: una etiqueta pegada a su valor (`Postal:99999`) o dos palabras sin espacio;
- cada línea con la posición x de cada palabra;
- qué etiquetas encuentra el parser y si el valor va en la misma línea, abajo o vacío.

Una palabra solo se muestra tal cual si es parte de una etiqueta o título conocido, con las
mismas mayúsculas; todo lo demás se reemplaza por su forma (`JUÁREZ 12` → `AAAAAA 99`). Se ve la
longitud de cada palabra, no su contenido. Igual que `eval-private`, no imprime nombres de
archivo ni mensajes de error y no escribe a disco. **Revisa la salida antes de compartirla.**
