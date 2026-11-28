# Cada receta es un solo comando simple para que funcione igual con cmd.exe (make en
# Windows desde PowerShell) y con sh (Git Bash, Linux, CI). Las descripciones con "##"
# las muestra `make help`.

.DEFAULT_GOAL := help
.PHONY: help install lint format test check-data ci sepomex verificar-claves tessdata synth synth-samples eval train-clasificador eval-private esqueleto api

help: ## Muestra esta ayuda
	@uv run --no-project python scripts/make_help.py Makefile

install: ## Instala dependencias (uv.lock) y los hooks de pre-commit
	uv sync --locked
	uv run pre-commit install

lint: ## Revisa estilo y formato con ruff
	uv run ruff check .
	uv run ruff format --check .

format: ## Corrige formato y errores autocorregibles con ruff
	uv run ruff format .
	uv run ruff check --fix .

test: ## Corre las pruebas
	uv run pytest

check-data: ## Revisa que no haya documentos reales en todo el historial de git
	uv run python scripts/check_no_real_data.py --history

ci: lint check-data test ## Lo mismo que corre CI

sepomex: ## Descarga el catálogo de códigos postales de SEPOMEX a data/sepomex/
	uv run python scripts/download_sepomex.py

verificar-claves: ## Comprueba los dígitos verificadores con CURPs/RFCs reales (solo imprime conteos)
	uv run python scripts/verificar_claves.py

tessdata: ## Descarga los modelos de Tesseract (español) a models/tessdata/ y los verifica
	uv run python scripts/download_tessdata.py

synth: ## Genera el dataset sintético en data/synthetic/ (requiere make sepomex; usa --force)
	uv run python -m synth --force

synth-samples: ## Regenera las muestras versionadas de data/synthetic/samples/
	uv run python -m synth --samples

eval: ## Evalúa texto y OCR (extractor A) sobre el split test y escribe reports/
	uv run python eval/evaluate.py --split test

train-clasificador: ## Entrena el clasificador TF-IDF + regresión logística y escribe reports/clasificador.md
	uv run python training/train_clasificador.py

eval-private: ## Evalúa con tus documentos reales de data/real/ (solo imprime conteos)
	uv run python eval/eval_private.py

esqueleto: ## Estructura de tus documentos de data/real/ con los datos enmascarados
	uv run python eval/esqueleto.py

api: ## Levanta la API de FastAPI (fase 8)
	@echo Pendiente: se implementa en la fase 8.
	@exit 1
