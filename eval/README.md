# eval/

## `make eval`: dataset sintético

```bash
make eval                                                      # split test: lo que se reporta
uv run python eval/evaluate.py --split val --errores 10 --no-save   # desarrollo
```

Por cada documento del split mide:

- **Router:** si fue por la ruta correcta. Digital va a texto; escaneo y foto van a imagen.
- **Clasificador de texto:** si reconoce el tipo de documento. Se reporta por separado el diseño de comprobante que no aparece en train.
- **Parsers:**
  - exactitud por campo tras normalizar;
  - CER;
  - porcentaje de documentos con todos los campos correctos;
  - latencia p50/p95 (lectura del PDF + clasificación + parser);
  - costo, que es $0 para las reglas.

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

Mide la ruta de texto con tus propios documentos **sin que sus datos salgan de tu equipo**.

```
data/real/curp/*.pdf        constancias de CURP descargadas de RENAPO
data/real/csf/*.pdf         constancias de situación fiscal descargadas del SAT
data/real/etiquetas.json    opcional: {"curp/archivo.pdf": {"curp": "...", "nombre": "..."}}
```

`data/real/` está en `.gitignore` y el hook de pre-commit rechaza cualquier archivo ahí.

**Sin etiquetas** mide lo que se puede comprobar sin conocer la respuesta:

- si va por la ruta de texto y si se clasifica bien;
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
