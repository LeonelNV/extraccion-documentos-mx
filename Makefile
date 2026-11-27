# Cada receta es un solo comando simple para que funcione igual con cmd.exe (make en
# Windows desde PowerShell) y con sh (Git Bash, Linux, CI). Las descripciones con "##"
# las muestra `make help`.

.DEFAULT_GOAL := help
.PHONY: help install lint format test check-data ci synth eval api

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

synth: ## Genera los datos sintéticos (fase 3)
	@echo Pendiente: se implementa en la fase 3.
	@exit 1

eval: ## Evalúa los extractores y escribe reports/ (fase 4 en adelante)
	@echo Pendiente: se implementa a partir de la fase 4.
	@exit 1

api: ## Levanta la API de FastAPI (fase 8)
	@echo Pendiente: se implementa en la fase 8.
	@exit 1
