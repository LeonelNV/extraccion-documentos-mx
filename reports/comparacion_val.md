# Comparación de extractores de imagen, split val

Generado por `eval/evaluate_llm.py`. No editar a mano. Solo escaneos y fotos (los digitales van por la capa de texto). Todos los extractores leen los mismos documentos.

Costo: tokens que reporta Bedrock x precios de AWS Price List API (servicio AmazonBedrock), precios bajo demanda, nivel estándar (us-east-1, consultados el 2026-11-27).

Imagen para C1: JPEG en color, 1600 px de lado mayor. Prompt v3.

## Resumen

| Extractor | Documentos | 100% correctos | Campos correctos | p50 | p95 | Costo por documento | Respuestas inválidas |
|---|---:|---:|---:|---:|---:|---:|---:|
| A: OCR + reglas | 178 | 59.6% | 74.0% | 3.0 s | 8.0 s | $0 | 0 |
| B: OCR + Nova Micro | 178 | 30.9% | 71.1% | 3.7 s | 7.8 s | $0.00006 | 0 |
| B: OCR + Nova Lite | 178 | 44.9% | 74.9% | 3.9 s | 8.1 s | $0.00011 | 0 |
| B: OCR + Nova Pro | 178 | 52.2% | 76.9% | 4.3 s | 8.3 s | $0.00144 | 0 |
| C1: Nova Lite (imagen) | 178 | 11.8% | 60.1% | 1.4 s | 1.9 s | $0.00019 | 1 |
| C1: Nova Pro (imagen) | 178 | 16.9% | 58.1% | 1.9 s | 2.5 s | $0.00253 | 0 |
| C1: Qwen3 VL 235B A22B (imagen) | 178 | 75.3% | 96.2% | 2.6 s | 3.9 s | $0.00179 | 0 |

## Documentos con todos los campos correctos, por tipo y modalidad

| Documento | Modalidad | n | A: OCR + reglas | B: OCR + Nova Micro | B: OCR + Nova Lite | B: OCR + Nova Pro | C1: Nova Lite (imagen) | C1: Nova Pro (imagen) | C1: Qwen3 VL 235B A22B (imagen) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| comprobante_domicilio | escaneo | 29 | 82.8% | 41.4% | 62.1% | 65.5% | 6.9% | 13.8% | 89.7% |
| comprobante_domicilio | foto | 24 | 33.3% | 16.7% | 16.7% | 29.2% | 8.3% | 12.5% | 75.0% |
| csf | escaneo | 21 | 81.0% | 47.6% | 76.2% | 76.2% | 4.8% | 19.0% | 85.7% |
| csf | foto | 7 | 28.6% | 14.3% | 28.6% | 28.6% | 0.0% | 0.0% | 42.9% |
| curp | escaneo | 16 | 87.5% | 75.0% | 81.2% | 87.5% | 62.5% | 68.8% | 93.8% |
| curp | foto | 13 | 38.5% | 23.1% | 38.5% | 38.5% | 46.2% | 61.5% | 100.0% |
| ine | escaneo | 28 | 92.9% | 32.1% | 60.7% | 82.1% | 0.0% | 0.0% | 85.7% |
| ine | foto | 40 | 25.0% | 10.0% | 12.5% | 17.5% | 0.0% | 0.0% | 42.5% |

## comprobante_domicilio: exactitud por campo

| Campo | A: OCR + reglas | B: OCR + Nova Micro | B: OCR + Nova Lite | B: OCR + Nova Pro | C1: Nova Lite (imagen) | C1: Nova Pro (imagen) | C1: Qwen3 VL 235B A22B (imagen) |
|---|---:|---:|---:|---:|---:|---:|---:|
| calle | 77.4% | 69.8% | 67.9% | 75.5% | 43.4% | 39.6% | 96.2% |
| numero_exterior | 79.2% | 79.2% | 79.2% | 81.1% | 56.6% | 54.7% | 94.3% |
| numero_interior | 79.2% | 50.9% | 83.0% | 81.1% | 71.7% | 56.6% | 96.2% |
| colonia | 71.7% | 66.0% | 64.2% | 73.6% | 49.1% | 54.7% | 96.2% |
| codigo_postal | 81.1% | 81.1% | 81.1% | 81.1% | 43.4% | 41.5% | 100.0% |
| ciudad | 81.1% | 64.2% | 69.8% | 66.0% | 47.2% | 47.2% | 100.0% |
| estado | 81.1% | 73.6% | 75.5% | 75.5% | 69.8% | 58.5% | 100.0% |
| fecha_emision | 69.8% | 64.2% | 67.9% | 67.9% | 75.5% | 77.4% | 98.1% |

## csf: exactitud por campo

| Campo | A: OCR + reglas | B: OCR + Nova Micro | B: OCR + Nova Lite | B: OCR + Nova Pro | C1: Nova Lite (imagen) | C1: Nova Pro (imagen) | C1: Qwen3 VL 235B A22B (imagen) |
|---|---:|---:|---:|---:|---:|---:|---:|
| rfc | 82.1% | 75.0% | 75.0% | 78.6% | 85.7% | 89.3% | 100.0% |
| curp | 78.6% | 78.6% | 75.0% | 78.6% | 32.1% | 50.0% | 96.4% |
| nombre | 89.3% | 89.3% | 96.4% | 96.4% | 92.9% | 78.6% | 100.0% |
| apellido_paterno | 92.9% | 92.9% | 96.4% | 96.4% | 85.7% | 75.0% | 96.4% |
| apellido_materno | 92.9% | 92.9% | 96.4% | 96.4% | 82.1% | 75.0% | 100.0% |
| codigo_postal | 75.0% | 75.0% | 75.0% | 75.0% | 96.4% | 82.1% | 100.0% |
| calle | 92.9% | 67.9% | 92.9% | 92.9% | 3.6% | 32.1% | 85.7% |
| numero_exterior | 92.9% | 89.3% | 92.9% | 89.3% | 92.9% | 92.9% | 96.4% |
| numero_interior | 96.4% | 96.4% | 100.0% | 96.4% | 89.3% | 85.7% | 100.0% |
| colonia | 100.0% | 100.0% | 100.0% | 100.0% | 82.1% | 75.0% | 100.0% |
| ciudad | 89.3% | 96.4% | 96.4% | 96.4% | 75.0% | 75.0% | 100.0% |
| municipio | 96.4% | 96.4% | 96.4% | 96.4% | 75.0% | 75.0% | 100.0% |
| estado | 100.0% | 100.0% | 100.0% | 100.0% | 96.4% | 89.3% | 100.0% |

## curp: exactitud por campo

| Campo | A: OCR + reglas | B: OCR + Nova Micro | B: OCR + Nova Lite | B: OCR + Nova Pro | C1: Nova Lite (imagen) | C1: Nova Pro (imagen) | C1: Qwen3 VL 235B A22B (imagen) |
|---|---:|---:|---:|---:|---:|---:|---:|
| curp | 65.5% | 65.5% | 65.5% | 65.5% | 82.8% | 79.3% | 100.0% |
| nombre | 72.4% | 89.7% | 86.2% | 86.2% | 89.7% | 89.7% | 96.6% |
| apellido_paterno | 72.4% | 82.8% | 86.2% | 86.2% | 89.7% | 89.7% | 96.6% |
| apellido_materno | 72.4% | 75.9% | 82.8% | 86.2% | 72.4% | 82.8% | 96.6% |

## ine: exactitud por campo

| Campo | A: OCR + reglas | B: OCR + Nova Micro | B: OCR + Nova Lite | B: OCR + Nova Pro | C1: Nova Lite (imagen) | C1: Nova Pro (imagen) | C1: Qwen3 VL 235B A22B (imagen) |
|---|---:|---:|---:|---:|---:|---:|---:|
| curp | 54.4% | 50.0% | 48.5% | 54.4% | 2.9% | 10.3% | 72.1% |
| nombre | 66.2% | 73.5% | 76.5% | 79.4% | 69.1% | 51.5% | 97.1% |
| apellido_paterno | 64.7% | 64.7% | 72.1% | 76.5% | 47.1% | 55.9% | 98.5% |
| apellido_materno | 64.7% | 58.8% | 63.2% | 73.5% | 45.6% | 52.9% | 95.6% |
| fecha_nacimiento | 67.6% | 66.2% | 66.2% | 66.2% | 64.7% | 60.3% | 95.6% |
| sexo | 57.4% | 67.6% | 75.0% | 77.9% | 82.4% | 94.1% | 100.0% |
| calle | 69.1% | 55.9% | 60.3% | 67.6% | 42.6% | 35.3% | 98.5% |
| numero_exterior | 70.6% | 72.1% | 72.1% | 72.1% | 52.9% | 45.6% | 85.3% |
| numero_interior | 70.6% | 67.6% | 79.4% | 77.9% | 72.1% | 66.2% | 94.1% |
| colonia | 69.1% | 63.2% | 66.2% | 67.6% | 39.7% | 38.2% | 98.5% |
| codigo_postal | 67.6% | 67.6% | 69.1% | 67.6% | 47.1% | 29.4% | 94.1% |
| ciudad | 66.2% | 60.3% | 66.2% | 70.6% | 42.6% | 45.6% | 100.0% |
| estado | 69.1% | 66.2% | 69.1% | 72.1% | 64.7% | 58.8% | 100.0% |
