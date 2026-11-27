# Resultados: ruta de texto (texto_reglas), split test

Generado por `make eval`. No editar a mano.

## Router y clasificador

| Métrica | Documentos | Exactitud |
|---|---:|---:|
| Router (texto vs. imagen) | 300 | 100.0% |
| Clasificador de texto | 131 | 89.3% |
| Clasificador: comprobante_domicilio | | 48.1% |
| Clasificador: csf | | 100.0% |
| Clasificador: curp | | 100.0% |
| Clasificador: ine | | 100.0% |
| Clasificador: plantilla no vista en train | 14 | 0.0% |

## Parser de texto: curp

48 documentos digitales · 100.0% con todos los campos correctos · latencia p50 155 ms, p95 181 ms · costo $0

| Campo | n | Exactitud | CER |
|---|---:|---:|---:|
| curp | 48 | 100.0% | 0.000 |
| nombre | 48 | 100.0% | 0.000 |
| apellido_paterno | 48 | 100.0% | 0.000 |
| apellido_materno | 48 | 100.0% | 0.000 |
| fecha_nacimiento | 48 | 100.0% | 0.000 |
| sexo | 48 | 100.0% | 0.000 |
| entidad_nacimiento | 48 | 100.0% | 0.000 |
| nacionalidad | 48 | 100.0% | 0.000 |

## Parser de texto: csf

53 documentos digitales · 100.0% con todos los campos correctos · latencia p50 192 ms, p95 221 ms · costo $0

| Campo | n | Exactitud | CER |
|---|---:|---:|---:|
| rfc | 53 | 100.0% | 0.000 |
| curp | 53 | 100.0% | 0.000 |
| nombre | 53 | 100.0% | 0.000 |
| apellido_paterno | 53 | 100.0% | 0.000 |
| apellido_materno | 53 | 100.0% | 0.000 |
| codigo_postal | 53 | 100.0% | 0.000 |
| calle | 53 | 100.0% | 0.000 |
| numero_exterior | 53 | 100.0% | 0.000 |
| numero_interior | 53 | 100.0% | 0.000 |
| colonia | 53 | 100.0% | 0.000 |
| ciudad | 53 | 100.0% | 0.000 |
| municipio | 53 | 100.0% | 0.000 |
| estado | 53 | 100.0% | 0.000 |
