# Resultados: ruta de texto y extractor A (OCR + reglas), split test

Generado por `make eval`. No editar a mano. Los documentos digitales van por la capa de texto (`texto_reglas`); los escaneos y fotos, por el extractor A (`ocr_reglas`: Tesseract + las mismas reglas). Costo: $0 (sin servicios externos).

## Resumen por documento y modalidad

| Documento | Modalidad | Extractor | Documentos | 100% correctos | p50 | p95 |
|---|---|---|---:|---:|---:|---:|
| curp | digital | `texto_reglas` | 48 | 100.0% | 319 ms | 456 ms |
| curp | escaneo | `ocr_reglas` | 22 | 86.4% | 6029 ms | 6901 ms |
| curp | foto | `ocr_reglas` | 5 | 60.0% | 6758 ms | 6980 ms |
| csf | digital | `texto_reglas` | 53 | 100.0% | 364 ms | 477 ms |
| csf | escaneo | `ocr_reglas` | 18 | 77.8% | 4707 ms | 5061 ms |
| csf | foto | `ocr_reglas` | 4 | 25.0% | 4029 ms | 4449 ms |
| ine | digital | `texto_reglas` | 3 | 100.0% | 134 ms | 159 ms |
| ine | escaneo | `ocr_reglas` | 27 | 81.5% | 2677 ms | 3003 ms |
| ine | foto | `ocr_reglas` | 45 | 26.7% | 2515 ms | 3175 ms |
| comprobante_domicilio | digital | `texto_reglas` | 27 | 100.0% | 32 ms | 51 ms |
| comprobante_domicilio | escaneo | `ocr_reglas` | 15 | 60.0% | 2724 ms | 3338 ms |
| comprobante_domicilio | foto | `ocr_reglas` | 33 | 33.3% | 2366 ms | 3249 ms |

## Comprobante de diseño no visto en train

Las reglas del comprobante se escribieron sin este diseño: mide la generalización.

| Modalidad | Documentos | 100% correctos | Campos correctos |
|---|---:|---:|---:|
| digital | 14 | 100.0% | 100.0% |
| escaneo | 7 | 57.1% | 73.2% |
| foto | 13 | 15.4% | 31.7% |

## Router y clasificador de palabras clave

| Métrica | Documentos | Exactitud |
|---|---:|---:|
| Router (texto vs. imagen) | 300 | 100.0% |
| Clasificador, texto del PDF | 131 | 89.3% |
| · comprobante_domicilio | | 48.1% |
| · csf | | 100.0% |
| · curp | | 100.0% |
| · ine | | 100.0% |
| · plantilla no vista en train | 14 | 0.0% |
| Clasificador, texto del OCR | 169 | 79.9% |
| · comprobante_domicilio | | 33.3% |
| · csf | | 100.0% |
| · curp | | 96.3% |
| · ine | | 98.6% |
| · plantilla no vista en train | 20 | 0.0% |

## curp: exactitud por campo

| Campo | digital | escaneo | foto |
|---|---:|---:|---:|
| curp | 100.0% (CER 0.000) | 86.4% (CER 0.136) | 60.0% (CER 0.211) |
| nombre | 100.0% (CER 0.000) | 86.4% (CER 0.136) | 80.0% (CER 0.200) |
| apellido_paterno | 100.0% (CER 0.000) | 86.4% (CER 0.136) | 80.0% (CER 0.200) |
| apellido_materno | 100.0% (CER 0.000) | 86.4% (CER 0.136) | 80.0% (CER 0.200) |

## csf: exactitud por campo

| Campo | digital | escaneo | foto |
|---|---:|---:|---:|
| rfc | 100.0% (CER 0.000) | 94.4% (CER 0.009) | 75.0% (CER 0.038) |
| curp | 100.0% (CER 0.000) | 88.9% (CER 0.111) | 25.0% (CER 0.528) |
| nombre | 100.0% (CER 0.000) | 100.0% (CER 0.000) | 25.0% (CER 0.750) |
| apellido_paterno | 100.0% (CER 0.000) | 100.0% (CER 0.000) | 25.0% (CER 0.750) |
| apellido_materno | 100.0% (CER 0.000) | 100.0% (CER 0.000) | 25.0% (CER 0.750) |
| codigo_postal | 100.0% (CER 0.000) | 100.0% (CER 0.000) | 75.0% (CER 0.250) |
| calle | 100.0% (CER 0.000) | 94.4% (CER 0.004) | 75.0% (CER 0.048) |
| numero_exterior | 100.0% (CER 0.000) | 100.0% (CER 0.000) | 100.0% (CER 0.000) |
| numero_interior | 100.0% (CER 0.000) | 100.0% (CER 0.000) | 100.0% (CER 0.000) |
| colonia | 100.0% (CER 0.000) | 100.0% (CER 0.000) | 100.0% (CER 0.000) |
| ciudad | 100.0% (CER 0.000) | 100.0% (CER 0.000) | 100.0% (CER 0.000) |
| municipio | 100.0% (CER 0.000) | 100.0% (CER 0.000) | 100.0% (CER 0.000) |
| estado | 100.0% (CER 0.000) | 100.0% (CER 0.000) | 100.0% (CER 0.000) |

## ine: exactitud por campo

| Campo | digital | escaneo | foto |
|---|---:|---:|---:|
| curp | 100.0% (CER 0.000) | 85.2% (CER 0.113) | 35.6% (CER 0.584) |
| nombre | 100.0% (CER 0.000) | 96.3% (CER 0.037) | 53.3% (CER 0.464) |
| apellido_paterno | 100.0% (CER 0.000) | 96.3% (CER 0.037) | 53.3% (CER 0.459) |
| apellido_materno | 100.0% (CER 0.000) | 96.3% (CER 0.037) | 53.3% (CER 0.469) |
| fecha_nacimiento | 100.0% (CER 0.000) | 100.0% (CER 0.000) | 57.8% (CER 0.367) |
| sexo | 100.0% (CER 0.000) | 88.9% (CER 0.111) | 42.2% (CER 0.578) |
| calle | 100.0% (CER 0.000) | 96.3% (CER 0.037) | 60.0% (CER 0.337) |
| numero_exterior | 100.0% (CER 0.000) | 96.3% (CER 0.037) | 66.7% (CER 0.333) |
| numero_interior | 100.0% (CER 0.000) | 96.3% (CER 0.037) | 64.4% (CER 0.356) |
| colonia | 100.0% (CER 0.000) | 100.0% (CER 0.000) | 64.4% (CER 0.346) |
| codigo_postal | 100.0% (CER 0.000) | 100.0% (CER 0.000) | 62.2% (CER 0.347) |
| ciudad | 100.0% (CER 0.000) | 100.0% (CER 0.000) | 53.3% (CER 0.394) |
| estado | 100.0% (CER 0.000) | 100.0% (CER 0.000) | 53.3% (CER 0.467) |

## comprobante_domicilio: exactitud por campo

| Campo | digital | escaneo | foto |
|---|---:|---:|---:|
| calle | 100.0% (CER 0.000) | 80.0% (CER 0.136) | 39.4% (CER 0.606) |
| numero_exterior | 100.0% (CER 0.000) | 86.7% (CER 0.133) | 39.4% (CER 0.606) |
| numero_interior | 100.0% (CER 0.000) | 86.7% (CER 0.133) | 39.4% (CER 0.606) |
| colonia | 100.0% (CER 0.000) | 66.7% (CER 0.333) | 42.4% (CER 0.576) |
| codigo_postal | 100.0% (CER 0.000) | 86.7% (CER 0.133) | 45.5% (CER 0.545) |
| ciudad | 100.0% (CER 0.000) | 86.7% (CER 0.133) | 45.5% (CER 0.545) |
| estado | 100.0% (CER 0.000) | 86.7% (CER 0.133) | 45.5% (CER 0.545) |
| fecha_emision | 100.0% (CER 0.000) | 100.0% (CER 0.000) | 45.5% (CER 0.518) |
