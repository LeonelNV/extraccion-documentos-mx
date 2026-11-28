# Clasificador de documentos: palabras clave vs. TF-IDF + regresión logística

Generado por `make train-clasificador`. No editar a mano. Split test del dataset sintético: 300 documentos (131 con capa de texto, 169 por OCR). Los dos clasificadores reciben el mismo texto.

Modelo: TF-IDF (palabras 1-2, caracteres 3-5) + regresión logística. C = 10.0 (elegido por macro-F1 en val), umbral de no reconocido = 0.71 (percentil 1 de la probabilidad máxima en val). Entrenado con 2000 documentos de train; el diseño de teléfono no está en train ni en val.

## Comparación

| Subconjunto | Documentos | Palabras clave: exactitud | ML: exactitud | Palabras clave: macro-F1 | ML: macro-F1 |
|---|---:|---:|---:|---:|---:|
| Todos | 300 | 84.0% | 98.3% | 0.886 | 0.991 |
| Texto del PDF (digitales) | 131 | 89.3% | 100.0% | 0.912 | 1.000 |
| Texto del OCR (escaneos y fotos) | 169 | 79.9% | 97.0% | 0.869 | 0.984 |
| Comprobante de diseño no visto (teléfono) | 34 | 0.0% | 94.1% | 0.000 | 0.242 |

Latencia de clasificar (sin contar el OCR): palabras clave p50 2.33 ms; ML p50 4.13 ms, p95 6.73 ms.

Las métricas con macro-F1 cuentan "no reconocido" como error. En el diseño no visto todos los documentos son comprobantes, así que su macro-F1 promedia clases sin documentos; ahí la métrica útil es la exactitud.

## Palabras clave: por clase (todos)

| Clase | n | Precisión | Recall | F1 |
|---|---:|---:|---:|---:|
| curp | 75 | 100.0% | 98.7% | 0.993 |
| ine | 75 | 100.0% | 98.7% | 0.993 |
| csf | 75 | 100.0% | 100.0% | 1.000 |
| comprobante_domicilio | 75 | 100.0% | 38.7% | 0.558 |

Matriz de confusión (filas: tipo real; columnas: predicho):

| Real \ Predicho | curp | ine | csf | comprobante_domicilio | no_reconocido |
|---|---:|---:|---:|---:|---:|
| curp | 74 | 0 | 0 | 0 | 1 |
| ine | 0 | 74 | 0 | 0 | 1 |
| csf | 0 | 0 | 75 | 0 | 0 |
| comprobante_domicilio | 0 | 0 | 0 | 29 | 46 |

## ML: por clase (todos)

| Clase | n | Precisión | Recall | F1 |
|---|---:|---:|---:|---:|
| curp | 75 | 100.0% | 98.7% | 0.993 |
| ine | 75 | 100.0% | 100.0% | 1.000 |
| csf | 75 | 100.0% | 100.0% | 1.000 |
| comprobante_domicilio | 75 | 100.0% | 94.7% | 0.973 |

Matriz de confusión (filas: tipo real; columnas: predicho):

| Real \ Predicho | curp | ine | csf | comprobante_domicilio | no_reconocido |
|---|---:|---:|---:|---:|---:|
| curp | 74 | 0 | 0 | 0 | 1 |
| ine | 0 | 75 | 0 | 0 | 0 |
| csf | 0 | 0 | 75 | 0 | 0 |
| comprobante_domicilio | 0 | 0 | 0 | 71 | 4 |
