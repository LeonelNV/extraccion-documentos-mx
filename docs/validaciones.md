# Validaciones y normalización

Qué se valida, de dónde salen las reglas y qué partes **no** se pudieron verificar contra una fuente oficial. Código en `src/docextract/normalize.py`, `src/docextract/entidades.py` y `src/docextract/validators/`.

## Principios

- **Tres formas de un mismo texto** (`normalize.py`):
  - **Tal como viene en el documento.** Solo se limpian espacios y caracteres invisibles. Es lo que produce un extractor.
  - **Formato de la FEA** (`to_form_format`): mayúsculas, sin acentos, con Ñ. Así guarda la FEA nombres y domicilio, y es el `value` final del formulario.
  - **Clave de comparación:** además quita la puntuación y expande abreviaturas. Solo se usa para comparar.

  Los datos con formato canónico se convierten a él: CURP y RFC (mayúsculas, sin espacios), código postal (5 dígitos) y fechas (`date`).
- **Validadores puros.** Reciben valores y devuelven datos derivados y advertencias (`ExtractionWarning`). No leen archivos (salvo el catálogo de SEPOMEX, que se carga una vez) ni dependen del reloj: la fecha de hoy se pasa como argumento.
- **Los mensajes no llevan datos personales.** Ninguna advertencia incluye la CURP, el RFC, nombres ni domicilios; las pruebas lo comprueban.
- **Ante la duda, advertir y no rechazar.** Cuando una regla no está confirmada, la comparación es tolerante para no marcar como sospechoso un documento correcto.

## Qué valida cada módulo

| Módulo | Valida | Advertencias |
|---|---|---|
| `validators/curp.py` | Formato oficial, fecha real, sexo H/M/X, entidad, dígito verificador. Deriva fecha, sexo y entidad. Compara las 4 primeras letras, la fecha y el sexo contra los datos extraídos. | `CURP_FORMATO_INVALIDO`, `CURP_DIGITO_VERIFICADOR_INVALIDO`, `CURP_NACIDO_EN_EXTRANJERO`, `CURP_DATOS_NO_COINCIDEN` |
| `validators/rfc.py` | Estructura de persona física, fecha, dígito verificador. Cruce de los primeros 10 caracteres con la CURP. | `RFC_FORMATO_INVALIDO`, `RFC_HOMOCLAVE_INVALIDA`, `RFC_GENERICO`, `RFC_NO_COINCIDE_CON_CURP` |
| `validators/names.py` | Nombre y apellidos entre documentos, con distancia de edición y abreviaturas ("MA." = MARIA). | `NOMBRE_NO_COINCIDE` |
| `validators/sepomex.py` | El CP existe; estado, municipio o ciudad y colonia corresponden al CP; sugiere colonias. | `CP_NO_EXISTE`, `CP_NO_COINCIDE_CON_ESTADO`, `CP_NO_COINCIDE_CON_MUNICIPIO`, `COLONIA_NO_ENCONTRADA` |
| `validators/comprobante.py` | Antigüedad del comprobante (3 meses por defecto) y fechas futuras. | `COMPROBANTE_ANTIGUO`, `FECHA_INVALIDA` |

Los umbrales (similitud de nombres 0.90, de colonia y municipio 0.85, antigüedad 3 meses) están en `ValidationConfig` y son **provisionales**: se calibran en la fase 5 con los datos de evaluación.

`build_curp` y `build_rfc` construyen claves a partir de nombre y fecha. Los usa el generador de datos sintéticos (fase 3), y las pruebas los usan para no depender de claves de personas reales.

## Fuentes

| Regla | Fuente | Estado |
|---|---|---|
| Estructura de los 18 caracteres de la CURP | [Instructivo Normativo para la asignación de la CURP](https://dof.gob.mx/nota_detalle_popup.php?codigo=5526717) (DOF, 18/06/2018) y su [modificación](https://dof.gob.mx/nota_detalle_popup.php?codigo=5632965) (DOF, 18/10/2021) | Oficial |
| Casos especiales de la CURP: Ñ, nombres compuestos (MARIA, MA., M., JOSE, J.), partículas (DA, DAS, DE, DEL, DER, DI, DIE, DD, Y, EL, LA, LOS, LAS, LE, LES, MAC, MC, VAN, VON), caracteres especiales, diéresis, sin vocal o consonante interna, un solo apellido; carácter 17 (0-9 hasta 1999, letra desde 2000) | [Reglas para la ejecución de los procedimientos para la asignación de la CURP](https://www.gob.mx/cms/uploads/attachment/file/681698/reglas_para_la_ejecucion_de_los_procedimientos_asignacion_de_la_curp.pdf), RENAPO, cap. 5 | Oficial |
| Sexo "X" en la CURP (personas no binarias) | Lo emite RENAPO; no aparece en el texto de las Reglas consultado | Confirmado por el responsable del proyecto |
| Nombres y claves numéricas de las 32 entidades | Catálogo de SEPOMEX (descarga del 2026-11-26) | Verificado por prueba automática contra el catálogo |
| Claves de dos letras de las entidades en la CURP (AS, BC… NE) | Anexo 03 de las Reglas, **no publicado**; se usan las de uso público | Sin verificar contra el anexo |
| Catálogo de palabras altisonantes de la CURP | Anexo 01 de las Reglas, **no publicado**; se usa la lista de uso público. PEDO y JOTO están confirmadas por los ejemplos de las Reglas | Parcial |
| Dígito verificador de la CURP | Las Reglas dicen que lo asigna "un algoritmo", sin publicarlo; se usa el algoritmo de uso público | Verificado con una CURP real (2026-11-26, `make verificar-claves`) |
| Reglas del RFC: letras, homoclave, dígito verificador, palabras inconvenientes | El SAT no las publica en su sitio; se usa la descripción de uso público derivada de un documento del SAT entregado por solicitud de acceso a la información | Dígito verificador: verificado con un RFC real (2026-11-27). Letras y homoclave: sin verificar; solo se usan para generar datos sintéticos |
| Formato del catálogo de códigos postales | [Correos de México](https://www.correosdemexico.gob.mx/SSLServicios/ConsultaCP/CodigoPostal_Exportar.aspx); formato comprobado con la descarga | Verificado |

### Contradicciones en los ejemplos oficiales

En el punto 1.16 de las Reglas, dos ejemplos ("MARIA JOSE…" y "JOSE MARIA…") usan la **primera letra** del segundo nombre en la posición 16, aunque el texto normativo dice "primera consonante interna del segundo nombre". Lo mismo ocurre en un ejemplo del punto 1.3. El código sigue el texto normativo. Por eso las posiciones 14 a 16 no se comparan contra el nombre extraído; solo se comparan las que las Reglas declaran verificables (las 4 primeras letras, la fecha, el sexo y la entidad).

### Cómo se mitigan las partes sin verificar

- **Palabras altisonantes:** si la CURP trae "X" en la posición 2 y las otras tres letras coinciden con el nombre, se acepta aunque la palabra no esté en nuestra lista.
- **CURP contra RFC:** una "X" en cualquiera de las dos claves se acepta contra cualquier letra, porque RENAPO y el SAT sustituyen cosas distintas (Ñ, palabras inconvenientes). Aun así, las reglas para una persona con un solo apellido difieren entre ambos, por eso una diferencia es advertencia y no error.
- **Homoclave del RFC:** solo se valida el dígito verificador. Los dos caracteres de homonimia los asigna el SAT y no se pueden recalcular con certeza.
- **Dígitos verificadores:** se comprobaron con una CURP y un RFC reales del responsable del proyecto, sin que salieran de su máquina (siguiente sección). Un algoritmo equivocado acertaría ambas por azar con probabilidad de 1/10 × 1/11, menos del 1%. Con más claves, la evidencia sería más fuerte.

## Verificar los dígitos verificadores con claves reales

```bash
make verificar-claves                                   # pide las claves sin mostrarlas
uv run python scripts/verificar_claves.py < claves.txt  # archivo fuera del repo
```

El script solo imprime conteos ("N CURP con dígito verificador correcto"). Nunca escribe las claves en pantalla, en disco ni en logs. Si alguna clave real sale con dígito INCORRECTO, el algoritmo está mal y hay que revisarlo.

## Catálogo de SEPOMEX

```bash
make sepomex   # descarga a data/sepomex/CPdescargatxt.zip y escribe metadata.json
uv run python scripts/download_sepomex.py --from-file CPdescargatxt.zip   # si bajaste el archivo a mano
```

- Correos de México lo ofrece "para uso particular" y no permite su comercialización ni su distribución. Por eso **no se versiona** y las pruebas usan un catálogo ficticio con el mismo formato.
- Formato: TXT en Latin-1, delimitado por `|`. La primera línea es el aviso de uso y la segunda los encabezados. Son 159,527 asentamientos y 31,860 códigos postales (descarga del 2026-11-26).
- En la descarga actual, cada CP pertenece a un solo estado y a un solo municipio. Una prueba lo vuelve a comprobar cuando el catálogo está descargado.
- `d_ciudad` está vacía en dos tercios de los registros (zonas rurales), por eso el campo `ciudad` del formulario se compara contra el municipio y contra la ciudad.
- `metadata.json` guarda la fecha, el origen, el SHA-256 y los conteos, para saber qué versión del catálogo usó cada evaluación.
