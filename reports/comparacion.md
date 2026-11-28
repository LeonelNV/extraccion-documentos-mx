# Comparación de extractores de imagen, split test

Generado por `eval/evaluate_llm.py`. No editar a mano. Solo escaneos y fotos (los digitales van por la capa de texto). Todos los extractores leen los mismos documentos.

Costo: tokens que reporta Bedrock x precios de AWS Price List API (servicio AmazonBedrock), precios bajo demanda, nivel estándar (us-east-1, consultados el 2026-11-27).

Imagen para C1: JPEG en color, 1600 px de lado mayor. Prompt v3.

## Resumen

| Extractor | Documentos | 100% correctos | Campos correctos | p50 | p95 | Costo por documento | Respuestas inválidas |
|---|---:|---:|---:|---:|---:|---:|---:|
| A: OCR + reglas | 169 | 53.8% | 72.1% | 2.7 s | 7.1 s | $0 | 0 |
| B: OCR + Nova Micro | 169 | 27.8% | 70.7% | 3.4 s | 6.7 s | $0.00006 | 0 |
| B: OCR + Nova Lite | 169 | 37.3% | 73.7% | 3.7 s | 6.9 s | $0.00011 | 0 |
| B: OCR + Nova Pro | 169 | 50.3% | 77.7% | 4.0 s | 7.3 s | $0.00143 | 0 |
| C1: Nova Lite (imagen) | 169 | 12.4% | 58.3% | 1.3 s | 2.7 s | $0.00019 | 0 |
| C1: Nova Pro (imagen) | 169 | 13.6% | 59.3% | 1.9 s | 3.0 s | $0.00254 | 0 |
| C1: Qwen3 VL 235B A22B (imagen) | 169 | 75.1% | 95.9% | 2.6 s | 4.0 s | $0.00179 | 0 |

## Documentos con todos los campos correctos, por tipo y modalidad

| Documento | Modalidad | n | A: OCR + reglas | B: OCR + Nova Micro | B: OCR + Nova Lite | B: OCR + Nova Pro | C1: Nova Lite (imagen) | C1: Nova Pro (imagen) | C1: Qwen3 VL 235B A22B (imagen) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| comprobante_domicilio | escaneo | 15 | 60.0% | 46.7% | 53.3% | 60.0% | 20.0% | 13.3% | 93.3% |
| comprobante_domicilio | foto | 33 | 33.3% | 18.2% | 18.2% | 24.2% | 3.0% | 21.2% | 69.7% |
| csf | escaneo | 18 | 77.8% | 44.4% | 66.7% | 77.8% | 0.0% | 0.0% | 77.8% |
| csf | foto | 4 | 25.0% | 0.0% | 25.0% | 25.0% | 0.0% | 0.0% | 50.0% |
| curp | escaneo | 22 | 86.4% | 77.3% | 77.3% | 86.4% | 68.2% | 63.6% | 100.0% |
| curp | foto | 5 | 60.0% | 60.0% | 60.0% | 60.0% | 40.0% | 0.0% | 100.0% |
| ine | escaneo | 27 | 81.5% | 14.8% | 40.7% | 66.7% | 0.0% | 0.0% | 74.1% |
| ine | foto | 45 | 26.7% | 4.4% | 11.1% | 28.9% | 0.0% | 0.0% | 60.0% |
| comprobante, diseño no visto | escaneo y foto | 20 | 30.0% (46.2% campos) | 30.0% (50.6% campos) | 30.0% (51.2% campos) | 35.0% (53.1% campos) | 15.0% (56.9% campos) | 20.0% (58.8% campos) | 90.0% (98.1% campos) |

## comprobante_domicilio: exactitud por campo

| Campo | A: OCR + reglas | B: OCR + Nova Micro | B: OCR + Nova Lite | B: OCR + Nova Pro | C1: Nova Lite (imagen) | C1: Nova Pro (imagen) | C1: Qwen3 VL 235B A22B (imagen) |
|---|---:|---:|---:|---:|---:|---:|---:|
| calle | 52.1% | 54.2% | 50.0% | 60.4% | 29.2% | 37.5% | 93.8% |
| numero_exterior | 54.2% | 56.2% | 56.2% | 56.2% | 47.9% | 52.1% | 87.5% |
| numero_interior | 54.2% | 52.1% | 64.6% | 62.5% | 72.9% | 64.6% | 91.7% |
| colonia | 50.0% | 54.2% | 54.2% | 54.2% | 54.2% | 43.8% | 97.9% |
| codigo_postal | 58.3% | 60.4% | 60.4% | 62.5% | 47.9% | 68.8% | 97.9% |
| ciudad | 58.3% | 52.1% | 45.8% | 52.1% | 41.7% | 50.0% | 97.9% |
| estado | 58.3% | 58.3% | 56.2% | 58.3% | 68.8% | 75.0% | 100.0% |
| fecha_emision | 62.5% | 58.3% | 60.4% | 60.4% | 77.1% | 70.8% | 97.9% |

## csf: exactitud por campo

| Campo | A: OCR + reglas | B: OCR + Nova Micro | B: OCR + Nova Lite | B: OCR + Nova Pro | C1: Nova Lite (imagen) | C1: Nova Pro (imagen) | C1: Qwen3 VL 235B A22B (imagen) |
|---|---:|---:|---:|---:|---:|---:|---:|
| rfc | 90.9% | 72.7% | 81.8% | 81.8% | 81.8% | 77.3% | 100.0% |
| curp | 77.3% | 68.2% | 77.3% | 77.3% | 36.4% | 36.4% | 95.5% |
| nombre | 86.4% | 90.9% | 95.5% | 95.5% | 95.5% | 95.5% | 100.0% |
| apellido_paterno | 86.4% | 90.9% | 90.9% | 90.9% | 95.5% | 100.0% | 100.0% |
| apellido_materno | 86.4% | 90.9% | 90.9% | 90.9% | 95.5% | 95.5% | 100.0% |
| codigo_postal | 95.5% | 95.5% | 95.5% | 95.5% | 90.9% | 77.3% | 100.0% |
| calle | 90.9% | 63.6% | 90.9% | 90.9% | 4.5% | 31.8% | 77.3% |
| numero_exterior | 100.0% | 95.5% | 100.0% | 100.0% | 95.5% | 90.9% | 100.0% |
| numero_interior | 100.0% | 100.0% | 90.9% | 100.0% | 81.8% | 81.8% | 95.5% |
| colonia | 100.0% | 100.0% | 100.0% | 100.0% | 90.9% | 77.3% | 100.0% |
| ciudad | 100.0% | 95.5% | 100.0% | 100.0% | 86.4% | 63.6% | 100.0% |
| municipio | 100.0% | 95.5% | 100.0% | 100.0% | 81.8% | 68.2% | 100.0% |
| estado | 100.0% | 100.0% | 100.0% | 100.0% | 90.9% | 95.5% | 100.0% |

## curp: exactitud por campo

| Campo | A: OCR + reglas | B: OCR + Nova Micro | B: OCR + Nova Lite | B: OCR + Nova Pro | C1: Nova Lite (imagen) | C1: Nova Pro (imagen) | C1: Qwen3 VL 235B A22B (imagen) |
|---|---:|---:|---:|---:|---:|---:|---:|
| curp | 81.5% | 81.5% | 81.5% | 81.5% | 85.2% | 85.2% | 100.0% |
| nombre | 85.2% | 88.9% | 92.6% | 96.3% | 88.9% | 70.4% | 100.0% |
| apellido_paterno | 85.2% | 88.9% | 88.9% | 96.3% | 81.5% | 74.1% | 100.0% |
| apellido_materno | 85.2% | 88.9% | 92.6% | 96.3% | 85.2% | 70.4% | 100.0% |

## ine: exactitud por campo

| Campo | A: OCR + reglas | B: OCR + Nova Micro | B: OCR + Nova Lite | B: OCR + Nova Pro | C1: Nova Lite (imagen) | C1: Nova Pro (imagen) | C1: Qwen3 VL 235B A22B (imagen) |
|---|---:|---:|---:|---:|---:|---:|---:|
| curp | 54.2% | 50.0% | 45.8% | 52.8% | 0.0% | 8.3% | 83.3% |
| nombre | 69.4% | 81.9% | 79.2% | 87.5% | 75.0% | 54.2% | 98.6% |
| apellido_paterno | 69.4% | 77.8% | 73.6% | 86.1% | 45.8% | 68.1% | 95.8% |
| apellido_materno | 69.4% | 79.2% | 69.4% | 88.9% | 40.3% | 54.2% | 98.6% |
| fecha_nacimiento | 73.6% | 73.6% | 76.4% | 76.4% | 68.1% | 65.3% | 94.4% |
| sexo | 59.7% | 55.6% | 72.2% | 80.6% | 88.9% | 97.2% | 100.0% |
| calle | 73.6% | 54.2% | 61.1% | 75.0% | 37.5% | 31.9% | 94.4% |
| numero_exterior | 77.8% | 75.0% | 76.4% | 76.4% | 48.6% | 51.4% | 88.9% |
| numero_interior | 76.4% | 72.2% | 83.3% | 81.9% | 81.9% | 77.8% | 90.3% |
| colonia | 77.8% | 65.3% | 76.4% | 77.8% | 29.2% | 29.2% | 95.8% |
| codigo_postal | 76.4% | 79.2% | 79.2% | 79.2% | 38.9% | 40.3% | 97.2% |
| ciudad | 70.8% | 63.9% | 79.2% | 81.9% | 34.7% | 44.4% | 98.6% |
| estado | 70.8% | 73.6% | 80.6% | 80.6% | 65.3% | 66.7% | 100.0% |
